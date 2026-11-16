"""Read local run snapshots without constructing a model or loading tools."""
from pathlib import Path

from cardinal_agent.agent.checkpoint import CheckpointStore


def inspect_run(path, *, include_trace=False):
    store = CheckpointStore(path)
    saved = store.read()
    state = saved['state']
    active = store.is_active()
    activity = state.get('activity', 'running')
    if state['phase'] == 'finished':
        status = state.get('status', 'completed')
    elif active:
        status = 'waiting_approval' if activity == 'waiting_approval' else 'running'
    elif state.get('status') == 'failed':
        status = 'failed'
    elif saved.get('pending_call'):
        status = 'needs_reconciliation'
    else:
        status = 'interrupted'
    events = saved['transcript']
    pending = saved.get('pending_call')
    result = {'id': Path(path).stem, 'run_id': saved['run_id'], 'status': status,
              'activity': activity, 'active': active, 'updated_at': saved.get('updated_at'),
              'model_attempts': state['turns'], 'accounted_tokens': state['spent'],
              'tool_calls': sum(e['type'] == 'tool_call' for e in events),
              'tool_results': sum(e['type'] == 'tool_result' for e in events),
              'pending_call': ({'name': pending['name'], 'operation_id': pending['call_id']} if pending else None),
              'last_error_type': state.get('last_error_type'),
              'resumable': state['phase'] == 'running' and not active,
              'resume_requires_reconciliation': bool(pending)}
    if include_trace:
        result['transcript'] = events
    return result


def list_runs(directory):
    results = []
    for path in sorted(Path(directory).glob('*.json')):
        try:
            results.append(inspect_run(path))
        except (ValueError, KeyError, TypeError, OSError):
            results.append({'id': path.stem, 'status': 'unreadable'})
    return results
