"""Run deterministic regressions and retain reproducible fault-test artifacts."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'docs/evaluations' /
                        (datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S') + '-harness-resilience'))
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)  # Never overwrite previous measurements.
    command = [sys.executable, '-m', 'pytest', 'tests', 'local_tests', '-m', 'not live',
               '--junitxml=' + str(out / 'pytest.xml')]
    files = sorted(set(list((ROOT / 'cardinal_agent').rglob('*.py')) +
                       list((ROOT / 'local_tests').rglob('*.py')) + [Path(__file__).resolve()]))
    snapshot = {str(p.relative_to(ROOT)): p.read_text(encoding='utf-8') for p in files}
    (out / 'source-snapshot.json').write_text(json.dumps(snapshot, indent=2), encoding='utf-8')
    metadata = {'started_at': datetime.now(timezone.utc).isoformat(), 'command': command,
                'base_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                'working_tree_dirty': bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT)),
                'python': sys.version, 'platform': platform.platform(), 'cpu_count': os.cpu_count(),
                'dependencies': {name: importlib.metadata.version(name) for name in
                                 ('pytest', 'jsonschema', 'openai', 'numpy', 'python-dotenv')},
                'source_sha256': {name: hashlib.sha256(content.encode()).hexdigest()
                                  for name, content in snapshot.items()},
                'fixture_sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                   for p in (ROOT / 'tests/fixtures').rglob('*.json')},
                'live_model_calls': 0, 'transport': 'deterministic fakes only',
                'fault_method': 'SIGKILL child process; recovery in a fresh process',
                'scope': 'Local correctness/fault tests; no production success rate or speedup claim'}
    (out / 'changes.diff').write_bytes(subprocess.check_output(['git', 'diff'], cwd=ROOT))
    (out / 'metadata.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    env = dict(os.environ, CARDINAL_TEST_ARTIFACTS=str(out / 'artifacts'))
    with (out / 'pytest.log').open('w') as handle:
        result = subprocess.run(command, cwd=ROOT, env=env, stdout=handle, stderr=subprocess.STDOUT)
    metadata.update(ended_at=datetime.now(timezone.utc).isoformat(), exit_code=result.returncode)
    (out / 'metadata.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    if (out / 'pytest.xml').exists():
        cases = list(ET.parse(out / 'pytest.xml').getroot().iter('testcase'))
        metrics = {'tests': len(cases), 'failures': sum(c.find('failure') is not None for c in cases),
                   'errors': sum(c.find('error') is not None for c in cases),
                   'skipped': sum(c.find('skipped') is not None for c in cases),
                   'case_seconds_sum': sum(float(c.get('time', 0)) for c in cases),
                   'sigkill_cases': sum(c.get('classname', '').endswith('test_process_recovery') for c in cases),
                   'native_adapter_cases': sum(c.get('classname', '').endswith('test_native_models') for c in cases)}
        matches = re.findall(r'(\d+) deselected', (out / 'pytest.log').read_text())
        metrics['deselected'] = int(matches[-1]) if matches else 0
        metrics['passed'] = metrics['tests'] - metrics['failures'] - metrics['errors'] - metrics['skipped']
        (out / 'metrics.json').write_text(json.dumps(metrics, indent=2), encoding='utf-8')
        print(json.dumps(metrics, indent=2))
    print('Recorded verification:', out)
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
