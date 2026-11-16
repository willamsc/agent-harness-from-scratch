"""Terminate real subprocesses, then recover in a separate fresh process."""
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys

import pytest

WORKER = Path(__file__).parent / 'helpers/crash_worker.py'
ROOT = Path(__file__).resolve().parents[1]


def invoke(home, stage, action):
    return [sys.executable, str(WORKER), str(home), stage, action]


@pytest.mark.parametrize('stage,effects', [
    ('before_tool', 0), ('waiting_approval', 0), ('inside_before_effect', 0),
    ('inside_after_effect', 1), ('after_result', 1),
])
def test_sigkill_then_fresh_process_resume(tmp_path, stage, effects):
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    child = subprocess.Popen(invoke(tmp_path, stage, 'start'), cwd=tmp_path,
                             env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert select.select([child.stdout], [], [], 10)[0], 'Worker did not reach fault boundary'
        assert child.stdout.readline().strip() == 'READY'
        from cardinal_agent.agent.runs import inspect_run
        live = inspect_run(tmp_path / 'checkpoint.json')
        assert live['active'] is True
        assert live['status'] == ('waiting_approval' if stage == 'waiting_approval' else 'running')
        child.kill()
        assert child.wait(timeout=5) == -signal.SIGKILL
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        child.stdout.close()
        child.stderr.close()
    saved = json.loads((tmp_path / 'checkpoint.json').read_text())
    assert saved['state']['turns'] == 1
    completed = subprocess.run(invoke(tmp_path, stage, 'resume'), cwd=tmp_path, env=env,
                               capture_output=True, text=True, timeout=10)
    if stage != 'after_result':
        assert completed.returncode == 12 and 'UNCERTAIN' in completed.stdout
        completed = subprocess.run(invoke(tmp_path, stage, 'resolve'), cwd=tmp_path, env=env,
                                   capture_output=True, text=True, timeout=10)
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)['status'] == 'done'
    ledger = tmp_path / 'effects.jsonl'
    count = len(ledger.read_text().splitlines()) if ledger.exists() else 0
    assert count == effects
    final = json.loads((tmp_path / 'checkpoint.json').read_text())
    assert final['state']['turns'] == 2
    assert len([e for e in final['transcript'] if e['type'] == 'tool_result']) == 1
    if os.environ.get('CARDINAL_TEST_ARTIFACTS'):
        directory = Path(os.environ['CARDINAL_TEST_ARTIFACTS']); directory.mkdir(parents=True, exist_ok=True)
        (directory / f'process-{stage}.json').write_text(json.dumps({
            'fault_boundary': stage, 'termination': 'SIGKILL', 'exit_code': -signal.SIGKILL,
            'expected_effects': effects, 'actual_effects': count,
            'attempts_before': saved['state']['turns'], 'attempts_after': final['state']['turns'],
            'operator_reconciliation': stage != 'after_result',
            'final_status': final['state']['status'], 'tool_result_count': 1}, indent=2))


def test_sigkill_recoverable_report_uses_transaction_receipt(tmp_path):
    import sqlite3
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    command = invoke(tmp_path, 'inside_after_effect', 'start') + ['recoverable']
    child = subprocess.Popen(command, cwd=tmp_path, env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert select.select([child.stdout], [], [], 10)[0]
        assert child.stdout.readline().strip() == 'READY'
        child.kill()
        assert child.wait(timeout=5) == -signal.SIGKILL
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        child.stdout.close()
        child.stderr.close()
    result = subprocess.run(invoke(tmp_path, 'inside_after_effect', 'resume') + ['recoverable'],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['status'] == 'done'
    with sqlite3.connect(tmp_path / 'reports.db') as db:
        assert db.execute('SELECT count(*) FROM reports').fetchone()[0] == 1
    saved = json.loads((tmp_path / 'checkpoint.json').read_text())
    assert next(e for e in saved['transcript'] if e['type'] == 'reconciliation_completed')['source'] == 'lookup'
    if os.environ.get('CARDINAL_TEST_ARTIFACTS'):
        directory = Path(os.environ['CARDINAL_TEST_ARTIFACTS']); directory.mkdir(parents=True, exist_ok=True)
        (directory / 'process-transactional-report.json').write_text(json.dumps({
            'fault_boundary': 'after_database_commit_before_tool_result', 'termination': 'SIGKILL',
            'report_count': 1, 'reconciliation_source': 'lookup', 'final_status': saved['state']['status'],
            'transcript': saved['transcript']}, indent=2))
