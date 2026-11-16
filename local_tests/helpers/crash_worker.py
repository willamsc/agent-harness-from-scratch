"""Child process used by SIGKILL recovery tests; no network or credentials."""
import json
import os
from pathlib import Path
import signal
import sys

from cardinal_agent.agent.checkpoint import CheckpointStore, RecoveryRequired
from cardinal_agent.harness import create_session
from cardinal_agent.types import AgentConfig, ToolResult, ToolSpec

home, stage, action = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
recoverable = len(sys.argv) > 4 and sys.argv[4] == 'recoverable'


def ready():
    print('READY', flush=True)
    signal.pause()  # Parent kills the real process at this exact boundary.


def write():
    if stage == 'inside_before_effect':
        ready()
    with (home / 'effects.jsonl').open('a') as handle:
        handle.write(json.dumps({'effect': 'report'}) + '\n')
        handle.flush()
        os.fsync(handle.fileno())
    if stage == 'inside_after_effect':
        ready()
    return 'report saved'


spec = ToolSpec('write', 'Write report', {'type': 'object', 'additionalProperties': False}, write)
if recoverable:
    from cardinal_agent.examples.durable_reports import ReportStore
    reports = ReportStore(home / 'reports.db')
    spec = reports.spec()
    execute = spec.execute_with_id
    def durable_write(args, operation_id):
        result = execute(args, operation_id)
        if action == 'start':
            ready()
        raise RuntimeError('Recovery must query the receipt, never execute again')
    spec.execute_with_id = durable_write
class User:
    def pending_message(self): return None
    def approve(self, call):
        ready()

config = AgentConfig(checkpoint_path=home / 'checkpoint.json',
                     mode='confirm' if stage == 'waiting_approval' else 'auto',
                     user=User() if stage == 'waiting_approval' else None)
if action == 'start':
    original = CheckpointStore.write
    def save(store, state):
        original(store, state)
        if stage == 'before_tool' and state['pending_call']:
            ready()
        if (stage == 'after_result' and state['state']['phase'] == 'running'
                and not state['pending_call'] and any(e['type'] == 'tool_result' for e in state['transcript'])):
            ready()
    CheckpointStore.write = save
    call = {'name': 'create_report', 'args': {'title': 'Weekly', 'body': 'Done'}} if recoverable else {'name': 'write', 'args': {}}
    session = create_session(lambda messages: '<tool_call>' + json.dumps(call) + '</tool_call>', [spec], config)
    session.send('Create report')
else:
    session = create_session(lambda messages: 'Recovered', [spec], config)
    try:
        result = session.resume()
    except RecoveryRequired:
        if action != 'resolve':
            print('UNCERTAIN', flush=True)
            sys.exit(12)
        exists = (home / 'effects.jsonl').exists()
        result = session.resume(ToolResult('ok' if exists else 'tool_error',
                                'Verified report exists' if exists else 'Verified report was not written'))
    print(json.dumps({'status': result.status, 'text': result.text}), flush=True)
