"""Validation order and immutable configured command policy."""
import pytest

from cardinal_agent.adapters import run_agent_session, run_format_tool_call
from cardinal_agent.cardinal import cardinal_spec
from cardinal_agent.llm import ScriptedLM
from cardinal_agent.types import AgentConfig
from cardinal_agent.user import ScriptedUser


def test_validation_precedes_rules_and_denial_never_asks_or_executes():
    calls = []
    user = ScriptedUser()
    tool = cardinal_spec('run_terminal', 'Test tool', lambda cmd: calls.append(cmd))
    lm = ScriptedLM([{'tool_call': {'name': 'run_terminal', 'args': {}}},
                     {'tool_call': {'name': 'run_terminal', 'args': {'cmd': 'echo blocked'}}},
                     'Not executed.'], formatter=run_format_tool_call)
    config = AgentConfig(user=user, mode='confirm', deny_rules=('blocked',))
    s = run_agent_session(lm, [tool], config)
    config.deny_rules = ()  # Changing caller-owned config does not reconfigure a session.
    assert s.send('Test policy').status == 'done'
    assert [e['status'] for e in s.transcript if e['type'] == 'tool_result'] == ['invalid_args', 'denied']
    assert not calls and not any(e[0] == 'approve' for e in user.log)
    assert next(e for e in s.transcript if e['type'] == 'policy_denial')['rule'] == 'blocked'


def test_invalid_regex_rejected_before_session_can_execute():
    import re
    with pytest.raises(re.error):
        run_agent_session(None, [], AgentConfig(deny_rules=('[',)))
