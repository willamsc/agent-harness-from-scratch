"""Record real DeepSeek native-protocol checks and the full live pytest suite.

Usage: python tools/verify_live.py --phase native|suite --out PATH
Uses only public fixtures/fictional reports. Credentials never enter artifacts.
Each phase has a separate empty local cache and cannot overwrite a prior phase.
"""
import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import sqlite3
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


class Recorder:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.count = 0

    def write(self, value):
        with self.lock:
            self.count += 1
            value['record_id'] = self.count
            with gzip.open(self.path, 'at', encoding='utf-8') as handle:
                handle.write(json.dumps(value, ensure_ascii=False) + '\n')


def run_native(out, args):
    import urllib.request
    from openai import OpenAI
    from cardinal_agent.agent.registry import ToolRegistry
    from cardinal_agent.examples.durable_reports import ReportStore
    from cardinal_agent.harness import create_session
    from cardinal_agent.llm import cost_usd
    from cardinal_agent.models import OpenAIChatAdapter, AnthropicMessagesAdapter
    from cardinal_agent.types import AgentConfig, Approval
    from tests.fixture_tools import make_fixture_tools

    key = os.environ['DEEPSEEK_API_KEY']
    client = OpenAI(api_key=key, base_url='https://api.deepseek.com', max_retries=0, timeout=60)
    recorder = Recorder(out / 'native-requests.jsonl.gz')
    ledger, rows = [], []

    def transport(protocol):
        def send(**request):
            if sum(r['estimated_cost_usd'] for r in ledger) >= args.budget:
                raise RuntimeError('Native verification budget reached.')
            started = time.perf_counter()
            actual = deepcopy(request)
            try:
                if protocol == 'openai':
                    actual.update(temperature=0, extra_body={'thinking': {'type': 'disabled'}})
                    response = client.chat.completions.create(**actual).model_dump()
                    usage = response.get('usage') or {}
                    incoming, outgoing = usage.get('prompt_tokens', 0), usage.get('completion_tokens', 0)
                    cached = usage.get('prompt_cache_hit_tokens', 0)
                else:
                    actual.update(temperature=0, thinking={'type': 'disabled'})
                    request_obj = urllib.request.Request('https://api.deepseek.com/anthropic/v1/messages',
                        data=json.dumps(actual).encode(), headers={'x-api-key': key,
                        'anthropic-version': '2023-06-01', 'Content-Type': 'application/json'})
                    with urllib.request.urlopen(request_obj, timeout=60) as raw:
                        response = json.load(raw)
                    usage = response.get('usage') or {}
                    # Anthropic format may report cached tokens separately.
                    cached = usage.get('cache_read_input_tokens', 0)
                    incoming = usage.get('input_tokens', 0) + cached + usage.get('cache_creation_input_tokens', 0)
                    outgoing = usage.get('output_tokens', 0)
                seconds = time.perf_counter() - started
                item = {'protocol': protocol, 'provider': 'deepseek', 'model': args.model,
                        'input_tokens': incoming, 'cached_tokens': cached, 'output_tokens': outgoing,
                        'estimated_cost_usd': cost_usd(args.model, incoming, cached, outgoing), 'seconds': seconds}
                ledger.append(item)
                recorder.write({'request': actual, 'response': response, **item})
                return response
            except Exception as exc:
                recorder.write({'request': actual, 'protocol': protocol, 'error_type': type(exc).__name__,
                                'status_code': getattr(exc, 'status_code', None),
                                'message': str(exc).replace(key, '[REDACTED]'),
                                'seconds': time.perf_counter() - started})
                raise
        return send

    class Deny:
        def pending_message(self): return None
        def approve(self, call): return Approval(False, 'Do not save notes')

    fixtures = json.loads((ROOT / 'tests/fixtures/agent_protocol_requests.json').read_text())
    for protocol, cls in [('openai', OpenAIChatAdapter), ('anthropic', AnthropicMessagesAdapter)]:
        model = cls(transport(protocol), args.model, max_tokens=2048, provider='deepseek')
        for case in fixtures:
            entry = {'protocol': protocol, 'id': case['id'], 'kind': 'native_call_generation'}
            try:
                specs = make_fixture_tools().tools
                reply = model.complete_native([
                    {'role': 'system', 'content': 'Perform the request by making exactly one native tool call. '
                     'Use lookup for directory facts, echo for exact text, and the requested action tool. Do not answer from memory.'},
                    {'role': 'user', 'content': case['request']}], ToolRegistry(specs).schemas())
                call = reply.tool_call
                valid = bool(call and call.name == case['tool'] and ToolRegistry(specs).validate(call.name, call.args) is None)
                if valid and 'args' in case:
                    valid = json.dumps(call.args, sort_keys=True) == json.dumps(case['args'], sort_keys=True)
                if valid and 'contains' in case:
                    valid = all(all(term.lower() in str(call.args.get(k, '')).lower() for term in terms)
                                for k, terms in case['contains'].items())
                entry.update(passed=valid, actual={'name': call.name, 'args': call.args} if call else None,
                             provider_call_id=reply.provider_call_id, expected=case)
            except Exception as exc:
                entry.update(passed=False, error_type=type(exc).__name__)
            rows.append(entry)
            print(protocol, case['id'], 'PASS' if entry['passed'] else 'FAIL', flush=True)

        for kind in ['execution_roundtrip', 'approval_denied', 'receipt_recovery']:
            entry = {'protocol': protocol, 'id': kind, 'kind': kind}
            try:
                if kind != 'receipt_recovery':
                    fx = make_fixture_tools()
                    tools = [fx.spec('add')] if kind == 'execution_roundtrip' else [fx.spec('write_note')]
                    config = AgentConfig(max_turns=4, mode='auto' if kind == 'execution_roundtrip' else 'confirm',
                                         user=None if kind == 'execution_roundtrip' else Deny())
                    session = create_session(model, tools, config)
                    result = session.send('Use add to compute 17 plus 25.' if kind == 'execution_roundtrip'
                                          else 'Use write_note to save buy printer toner.')
                    if kind == 'execution_roundtrip':
                        valid = result.status == 'done' and fx.count('add') == 1 and '42' in result.text
                    else:
                        valid = result.status == 'done' and not fx.notes and any(
                            e['type'] == 'tool_result' and e['status'] == 'denied' for e in result.transcript)
                else:
                    store = ReportStore(out / f'{protocol}-reports.db')
                    spec = store.spec()
                    def stop_after_commit(params, operation_id):
                        store.execute(params, operation_id)
                        raise SystemExit('Injected stop after database commit')
                    spec.execute_with_id = stop_after_commit
                    config = AgentConfig(max_turns=6, checkpoint_path=out / f'{protocol}-checkpoint.json')
                    session = create_session(model, [spec], config)
                    interrupted = False
                    try:
                        session.send('Use create_report to save title Live check and body Saved. Do not change these strings.')
                    except SystemExit:
                        interrupted = True
                    if not interrupted:
                        raise RuntimeError('The real model did not execute the report tool.')
                    session = create_session(model, [store.spec()], config)
                    result = session.resume()
                    with sqlite3.connect(store.path) as db:
                        count = db.execute('SELECT count(*) FROM reports').fetchone()[0]
                    valid = result.status == 'done' and count == 1 and any(
                        e['type'] == 'reconciliation_completed' and e['source'] == 'lookup' for e in result.transcript)
                    entry['report_count'] = count
                entry.update(passed=valid, final=result.text, status=result.status, transcript=result.transcript)
            except Exception as exc:
                entry.update(passed=False, error_type=type(exc).__name__)
            rows.append(entry)
            dump(out / 'native-results.json', rows)
            print(protocol, kind, 'PASS' if entry['passed'] else 'FAIL', flush=True)
    client.close()
    dump(out / 'native-ledger.json', ledger)
    metrics = {'provider': 'deepseek', 'model': args.model, 'cases': len(rows),
               'passed': sum(r['passed'] for r in rows), 'failed': sum(not r['passed'] for r in rows),
               'actual_provider_calls': len(ledger), 'request_attempts': recorder.count, 'local_cache_hits': 0,
               'estimated_cost_usd': sum(r['estimated_cost_usd'] for r in ledger),
               'cost_note': 'Existing repository price table estimate, not the actual provider invoice.',
               'input_tokens': sum(r['input_tokens'] for r in ledger),
               'output_tokens': sum(r['output_tokens'] for r in ledger),
               'by_protocol': {p: {'passed': sum(r['passed'] for r in rows if r['protocol'] == p),
                                   'total': sum(r['protocol'] == p for r in rows)} for p in ['openai', 'anthropic']},
               'scope': 'Both formats served by DeepSeek; not a test of OpenAI or Claude models.'}
    dump(out / 'native-metrics.json', metrics)
    print(json.dumps(metrics, indent=2), flush=True)
    return 0 if all(r['passed'] for r in rows) else 1


def run_suite(out, args):
    import pytest
    from cardinal_agent.llm import LM, read_ledger
    from cardinal_agent.agent.session import AgentSession
    import cardinal_agent.simulation.evaluate as evaluate
    import cardinal_agent.simulation as simulation

    recorder = Recorder(out / 'model-calls.jsonl.gz')
    original = LM.__call__
    original_send = AgentSession.send
    original_eval = evaluate.run_eval
    session_records = Recorder(out / 'session-results.jsonl.gz')

    def observed(self, messages):
        before = self.usage(); started = time.perf_counter()
        record = {'tag': self.tag, 'model': self.model, 'provider': self.provider, 'messages': deepcopy(messages)}
        try:
            text = original(self, messages)
            record['reply'] = text
            return text
        except Exception as exc:
            record['error_type'] = type(exc).__name__
            raise
        finally:
            after = self.usage()
            record.update(seconds=time.perf_counter() - started,
                          usage_delta={k:after[k]-before[k] for k in before if isinstance(before[k], (int,float))})
            recorder.write(record)

    def send(self, message):
        try:
            result = original_send(self, message)
            session_records.write({'user': message, 'text': result.text, 'status': result.status,
                                   'transcript': result.transcript})
            return result
        except Exception as exc:
            session_records.write({'user': message, 'error_type': type(exc).__name__, 'transcript': self.transcript})
            raise

    def run_eval(*a, **kw):
        kw['out_dir'] = out / 'simulated-users'
        records = original_eval(*a, **kw)
        dump(out / 'simulated-user-metrics.json', {'successes': sum(r.success for r in records),
             'total':len(records), 'failures':[r.persona_id for r in records if not r.success],
             'categories':{p:{'passed':sum(r.success for r in records if r.category == p),
                               'total':sum(r.category == p for r in records)} for p in sorted({r.category for r in records})},
             'cost_usd':sum(r.cost_usd for r in records)})
        return records

    LM.__call__, AgentSession.send = observed, send
    evaluate.run_eval = simulation.run_eval = run_eval
    command = ['tests', '-m', 'live', '-s', '-q', '--junitxml=' + str(out / 'pytest.xml')]
    try:
        code = pytest.main(command)
    finally:
        LM.__call__, AgentSession.send = original, original_send
        evaluate.run_eval = simulation.run_eval = original_eval
        dump(out / 'ledger.json', read_ledger())
    rows = read_ledger()
    cases = list(ET.parse(out / 'pytest.xml').getroot().iter('testcase')) if (out / 'pytest.xml').exists() else []
    metrics = {'tests':len(cases),'passed':sum(c.find('failure') is None and c.find('error') is None and c.find('skipped') is None for c in cases),
               'failures':[c.get('classname')+'::'+c.get('name') for c in cases if c.find('failure') is not None or c.find('error') is not None],
               'estimated_cost_usd':sum(r['cost_usd'] for r in rows), 'ledger_calls':len(rows),
               'input_tokens':sum(r['input_tokens'] for r in rows),'output_tokens':sum(r['output_tokens'] for r in rows),
               'cases':[{'name':c.get('classname')+'::'+c.get('name'), 'seconds':float(c.get('time',0)),
                         'passed':c.find('failure') is None and c.find('error') is None} for c in cases],
               'fresh_local_cache_at_start':True,'cost_note':'Repository estimates; provider prompt-cache discounts may apply.'}
    dump(out / 'suite-metrics.json', metrics)
    print(json.dumps(metrics, indent=2), flush=True)
    return int(code)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--phase',choices=['native','suite'],required=True)
    parser.add_argument('--model',default='deepseek-flash')
    parser.add_argument('--budget',type=float,default=2)
    args=parser.parse_args()
    from cardinal_agent.llm import _load_env
    _load_env()
    if not os.environ.get('DEEPSEEK_API_KEY'):
        raise SystemExit('DEEPSEEK_API_KEY is not configured.')
    out=args.out.resolve()/args.phase
    out.mkdir(parents=True,exist_ok=False)
    # Completely separate from historical local cache and other phases.
    cache=ROOT/'.lm_cache'/('live-'+args.out.name+'-'+args.phase)
    if cache.exists(): raise SystemExit('Cache already exists; choose a new output directory.')
    os.environ.update(CARDINAL_LLM_PROVIDER='deepseek',CARDINAL_GRADING_MODEL=args.model,
                      CARDINAL_USER_MODEL=args.model,CARDINAL_JUDGE_MODEL=args.model,
                      CARDINAL_CACHE_DIR=str(cache),CARDINAL_BUDGET_USD=str(args.budget),
                      CARDINAL_DEEPSEEK_THINKING='disabled',CARDINAL_EVAL_CONCURRENCY='4')
    os.environ.pop('CARDINAL_EVAL_SLICE',None)
    files=list((ROOT/'cardinal_agent').rglob('*.py'))+list((ROOT/'tests').rglob('*.py'))+[Path(__file__).resolve()]
    snapshot={str(p.relative_to(ROOT)):p.read_text() for p in files}
    dump(out/'source-snapshot.json',snapshot)
    meta={'started_at':datetime.now(timezone.utc).isoformat(),'argv':sys.argv,'phase':args.phase,
          'base_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
          'working_tree_dirty':bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT)),
          'provider':'deepseek','model':args.model,'temperature':0,'thinking':'disabled','budget_usd':args.budget,
          'cache':'new empty local directory; within-run reuse is recorded', 'platform':platform.platform(),'python':sys.version,
          'dependencies':{n:importlib.metadata.version(n) for n in ['openai','pytest','jsonschema']},
          'source_sha256':{n:hashlib.sha256(s.encode()).hexdigest() for n,s in snapshot.items()},
          'fixtures_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'tests/fixtures').rglob('*.json')}}
    dump(out/'metadata.json',meta)
    started=time.perf_counter()
    try:
        code=run_native(out,args) if args.phase=='native' else run_suite(out,args)
    except Exception as exc:
        meta['fatal_error_type']=type(exc).__name__
        raise
    finally:
        meta.update(ended_at=datetime.now(timezone.utc).isoformat(),wall_seconds=time.perf_counter()-started)
        dump(out/'metadata.json',meta)
    meta['exit_code']=code;dump(out/'metadata.json',meta)
    return code


if __name__=='__main__':
    raise SystemExit(main())
