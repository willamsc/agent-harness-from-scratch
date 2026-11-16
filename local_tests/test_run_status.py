"""Run inspection is read-only and never constructs a provider client."""
import json

import pytest

from cardinal_agent.agent.checkpoint import RecoveryRequired
from cardinal_agent.agent.runs import inspect_run, list_runs
from cardinal_agent.harness import create_session
from cardinal_agent.types import AgentConfig, ToolSpec


def test_states_and_default_summary_privacy(tmp_path):
    path = tmp_path / 'run.json'
    def fail(messages): raise TimeoutError('private failure')
    config = AgentConfig(checkpoint_path=path)
    session = create_session(fail, [], config)
    with pytest.raises(TimeoutError): session.send('private question')
    summary = inspect_run(path)
    assert summary['status'] == 'failed' and summary['resumable']
    assert summary['last_error_type'] == 'TimeoutError'
    assert 'private' not in json.dumps(summary)
    assert 'private question' in json.dumps(inspect_run(path, include_trace=True))
    create_session(lambda m: 'Done', [], config).resume()
    assert inspect_run(path)['status'] == 'completed'
    assert not inspect_run(path)['resumable']
    (tmp_path / 'bad.json').write_text('{')
    assert any(r['status'] == 'unreadable' for r in list_runs(tmp_path))


def test_uncertain_and_interrupted_states(tmp_path):
    path = tmp_path / 'run.json'
    def crash(): raise KeyboardInterrupt()
    spec = ToolSpec('write', 'Write', {'type': 'object'}, crash)
    config = AgentConfig(checkpoint_path=path)
    with pytest.raises(KeyboardInterrupt):
        create_session(lambda m: '<tool_call>{"name":"write","args":{}}</tool_call>', [spec], config).send('Write')
    assert inspect_run(path)['status'] == 'needs_reconciliation'
    assert inspect_run(path)['pending_call']['operation_id']
    assert inspect_run(path)['resume_requires_reconciliation']


def test_cli_runs_without_api_key(tmp_path, monkeypatch, capsys):
    from cardinal_agent.app.cli import main
    monkeypatch.delenv('DEEPSEEK_API_KEY', raising=False)
    args = ['--home', str(tmp_path)]
    assert main(args + ['init']) == 0
    capsys.readouterr()
    config = AgentConfig(checkpoint_path=tmp_path / 'checkpoints' / 'one.json')
    create_session(lambda m: 'Done', [], config).send('Sensitive content')
    assert main(args + ['runs', 'list']) == 0
    output = capsys.readouterr().out
    assert 'completed' in output and 'Sensitive content' not in output
    assert main(args + ['runs', 'show', 'one', '--trace']) == 0
    assert 'Sensitive content' in capsys.readouterr().out
    assert main(args + ['runs', 'show', '../one']) == 2
