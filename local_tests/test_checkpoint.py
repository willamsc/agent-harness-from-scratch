"""Fault injection for durable boundaries, budgets, policy and locking."""
import json

import pytest

from cardinal_agent.harness import create_session
from cardinal_agent.agent.checkpoint import RecoveryRequired, CheckpointStore
from cardinal_agent.types import AgentConfig, ToolSpec, ToolResult

CALL = '<tool_call>{"name":"write","args":{}}</tool_call>'


def setup(tmp_path, fn, lm, **kwargs):
    config = AgentConfig(checkpoint_path=tmp_path / 'state.json', **kwargs)
    spec = ToolSpec('write', 'Write once', {'type': 'object', 'additionalProperties': False}, fn)
    return create_session(lm, [spec], config)


def test_completed_tool_survives_provider_failure(tmp_path):
    writes = []
    replies = iter([CALL])
    def lm(messages):
        try:
            return next(replies)
        except StopIteration:
            raise ConnectionError('provider down')
    first = setup(tmp_path, lambda: writes.append(1) or 'saved', lm)
    with pytest.raises(ConnectionError):
        first.send('write')
    second = setup(tmp_path, lambda: writes.append(2), lambda messages: 'Done')
    result = second.resume()
    assert result.text == 'Done'
    assert writes == [1]
    assert second._turn_user_messages[0] is second._current_request
    assert any(second._current_request is m for m in second.messages)
    assert len([e for e in result.transcript if e['type'] == 'tool_result']) == 1
    assert any(e['type'] == 'run_resumed' for e in result.transcript)


def test_uncertain_side_effect_never_retried(tmp_path):
    writes = []
    def crash():
        writes.append(1)
        raise KeyboardInterrupt()
    first = setup(tmp_path, crash, lambda messages: CALL)
    with pytest.raises(KeyboardInterrupt):
        first.send('write')
    second = setup(tmp_path, lambda: writes.append(2), lambda messages: 'Confirmed')
    with pytest.raises(RecoveryRequired):
        second.resume()
    with pytest.raises(RecoveryRequired):
        second.send('again')
    result = second.resume(ToolResult('ok', 'Operator verified the write completed'))
    assert result.text == 'Confirmed' and writes == [1]


def test_policy_and_reserved_budget(tmp_path):
    def failed(messages):
        raise TimeoutError()
    first = setup(tmp_path, lambda: None, failed, max_turns=1)
    with pytest.raises(TimeoutError):
        first.send('hello')
    changed = setup(tmp_path, lambda: None, lambda m: 'no', max_turns=2)
    with pytest.raises(ValueError, match='policy'):
        changed.resume()
    matching = setup(tmp_path, lambda: None, lambda m: pytest.fail('budget reset'), max_turns=1)
    assert matching.resume().status == 'max_turns'


def test_single_writer_and_atomic_state(tmp_path):
    path = tmp_path / 'state.json'
    store = CheckpointStore(path)
    store.write({'old': True})
    with store.locked():
        with pytest.raises(RuntimeError, match='already in use'):
            with CheckpointStore(path).locked():
                pass
    store.write({'new': True})
    assert json.loads(path.read_text()) == {'new': True}
    assert not list(tmp_path.glob('.checkpoint-*'))


def test_explicit_empty_tools_do_not_install_business_tools():
    session = create_session(lambda m: 'Hello', [])
    assert session.registry.schemas() == []
    assert session.send('hello').text == 'Hello'


def test_cancel_after_model_returns_prevents_tool(tmp_path):
    writes = []
    def model(messages):
        session.cancel()
        return CALL
    session = setup(tmp_path, lambda: writes.append(1), model)
    assert session.send('write').status == 'cancelled'
    assert writes == []
    assert json.loads((tmp_path / 'state.json').read_text())['state']['phase'] == 'finished'


def test_model_identity_cannot_change_on_resume(tmp_path):
    class Model:
        model = 'first'
        provider = 'fake'
        def __call__(self, messages):
            raise TimeoutError()
    session = setup(tmp_path, lambda: None, Model())
    with pytest.raises(TimeoutError):
        session.send('hello')
    model = Model()
    model.model = 'different'
    with pytest.raises(ValueError, match='policy'):
        setup(tmp_path, lambda: None, model).resume()


def test_cli_resume_existing_profile(tmp_path, monkeypatch):
    from cardinal_agent.app.cli import main
    from cardinal_agent.agent.memory import MemoryController
    import cardinal_agent.llm as llm
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'fake-test-key')
    monkeypatch.setattr(MemoryController, 'context_for', lambda self, text: '')
    monkeypatch.setattr(MemoryController, 'extract', lambda self: [])
    class Model:
        model = 'deepseek-flash'
        provider = 'deepseek'
        fail = True
        def __init__(self, *args, **kwargs): pass
        def __call__(self, messages):
            if self.fail:
                raise ConnectionError('offline')
            return 'Recovered answer'
        def usage(self): return {}
    monkeypatch.setattr(llm, 'LM', Model)
    args = ['--home', str(tmp_path)]
    assert main(args + ['init', '--demo']) == 0
    assert main(args + ['ask', 'hello']) == 1
    record_path = next((tmp_path / 'conversations').glob('*.json'))
    Model.fail = False
    monkeypatch.setattr('builtins.input', lambda prompt: 'exit')
    assert main(args + ['chat', '--resume', record_path.stem]) == 0
    record = json.loads(record_path.read_text())
    assert record['turns'][-1]['resumed']
    assert record['turns'][-1]['assistant'] == 'Recovered answer'
