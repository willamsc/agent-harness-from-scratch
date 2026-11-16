import sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
import datetime,hashlib,importlib.metadata,json,os,platform,shutil,subprocess,threading,time,traceback
from zoneinfo import ZoneInfo
from cs329z_hw1 import adapters
from cs329z_hw1.llm import LM,_load_env,read_ledger
from cs329z_hw1.simulation import load_personas,run_eval,adapter_agent_factory,format_table
from cs329z_hw1.simulation import evaluate
_load_env()
start=datetime.datetime.now(ZoneInfo('Asia/Shanghai'))
folder=Path('docs/evaluations')/(start.strftime('%Y%m%d-%H%M%S')+'-sim-eval-live-baseline')
folder.mkdir(parents=True)
run_dir=Path('runs')/('sim-'+start.strftime('%Y%m%d-%H%M%S'))
lock=threading.Lock()
calls=[];instances={};original=LM.__call__
def captured(self,messages):
    t=time.perf_counter();item={'tag':self.tag,'model':self.model,'provider':self.provider,'request_sha256':hashlib.sha256(json.dumps(messages,sort_keys=True,ensure_ascii=False).encode()).hexdigest()}
    with lock: instances[id(self)]=self
    try:
        reply=original(self,messages)
        item['reply']=reply
        return reply
    except Exception as exc:
        item['error']=type(exc).__name__+': '+str(exc)
        raise
    finally:
        item['wall_seconds']=time.perf_counter()-t
        with lock: calls.append(item)
LM.__call__=captured
original_run_persona=evaluate.run_persona
log=(folder/'output.log').open('w')
def emit(text):
    with lock:
        print(text,flush=True);log.write(text+'\n');log.flush()
def progress(*args,**kwargs):
    r=original_run_persona(*args,**kwargs)
    emit(f'{r.persona_id}: {"PASS" if r.success else "FAIL"}; {r.seconds:.2f}s; new USD {r.cost_usd:.6f}')
    return r
evaluate.run_persona=progress
personas=load_personas(Path('tests/fixtures/personas'))
files=[p for p in Path('cs329z_hw1').rglob('*.py')]
metadata={'started_at':start.isoformat(),'timezone':'Asia/Shanghai','base_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'working_tree_dirty':bool(subprocess.check_output(['git','status','--porcelain'],text=True).strip()),'command':[sys.executable,'/tmp/run_recorded_sim_eval.py'],'plan':'Course run_eval first 3 then remaining 17, concurrency=4, no implementation changes between batches; same output directory.','run_dir':str(run_dir),'python':sys.version,'platform':platform.platform(),'cpu_count':os.cpu_count(),'dependencies':{d:importlib.metadata.version(d) for d in ['pytest','jsonschema','numpy','openai','python-dotenv']},'implementation_sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files},'fixture_sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in Path('tests/fixtures').rglob('*.json')},'model_cache':'Existing cache enabled, no new salt. Workspace paths may prevent reuse.','configured_budget_usd':os.environ.get('CS329Z_BUDGET_USD'),'proxy_note':'Proxy variables unset only for this process. No keys or full environment recorded.'}
(folder/'metadata.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n')
(folder/'implementation-snapshot.json').write_text(json.dumps({str(p):p.read_text() for p in files},ensure_ascii=False,indent=2)+'\n')
records=[];error=None;t=time.perf_counter()
try:
    records+=run_eval(personas[:3],adapter_agent_factory(adapters),concurrency=4,out_dir=run_dir)
    emit('First batch completed: '+str(sum(r.success for r in records))+'/3. Continuing remaining 17.')
    records+=run_eval(personas[3:],adapter_agent_factory(adapters),concurrency=4,out_dir=run_dir)
    table=format_table(records,verbose=True)
    (run_dir/'summary.txt').write_text(table+'\n')
    emit(table)
except Exception:
    error=traceback.format_exc();emit(error)
finally:
    metadata.update({'ended_at':datetime.datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'wall_seconds':time.perf_counter()-t,'error':error,'completed_records':len(list(run_dir.glob('*.json'))) if run_dir.exists() else 0,'actual_models':[{'tag':lm.tag,'provider':lm.provider,'model':lm.model,'temperature':lm.temperature,'max_tokens':lm.max_tokens,'reasoning_effort':lm.reasoning_effort,'usage':lm.usage()} for lm in instances.values()]})
    (folder/'metadata.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n')
    (folder/'model-calls.json').write_text(json.dumps(calls,ensure_ascii=False,indent=2)+'\n')
    ledger=[r for r in read_ledger() if r.get('ts',0)>=start.timestamp() and r.get('tag','').startswith('sim_eval/')]
    (folder/'ledger.json').write_text(json.dumps(ledger,indent=2)+'\n')
    if run_dir.exists(): shutil.copytree(run_dir,folder/'records')
    log.close()
    print('ARTIFACTS='+str(folder),flush=True)
sys.exit(1 if error else 0)
