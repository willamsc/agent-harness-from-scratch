"""No-interface refusal, exact polling, and user-source memory integration."""
import json

from cardinal_agent.adapters import run_agent_session, run_format_tool_call
from cardinal_agent.llm import ScriptedLM
from cardinal_agent.types import AgentConfig
from cardinal_agent.user import ScriptedUser
from tests.fixture_tools import make_fixture_tools


def call(name, **args):
    return {'tool_call': {'name': name, 'args': args}}


def test_confirm_without_user_denies_side_effect():
    fx = make_fixture_tools()
    lm = ScriptedLM([call('write_note', text='no'), 'Not executed.'], formatter=run_format_tool_call)
    s = run_agent_session(lm, fx.tools, AgentConfig(mode='confirm'))
    assert s.send('Write a note').status == 'done'
    assert fx.notes == []
    assert next(e for e in s.transcript if e['type'] == 'tool_result')['status'] == 'denied'


def test_steering_does_not_reset_turn_budget_or_poll_twice():
    user = ScriptedUser(steering={0: 'New direction'})
    fx = make_fixture_tools()
    lm = ScriptedLM([call('echo', text='done')], formatter=run_format_tool_call)
    s = run_agent_session(lm, fx.tools, AgentConfig(user=user, max_turns=1))
    assert s.send('Initial request').status == 'max_turns'
    assert user._polls == len(lm.calls) == 1
    assert any(m['content'] == 'New direction' for m in lm.calls[0])


def test_answers_and_steering_are_memory_sources_and_tool_result_is_visible(tmp_path):
    user = ScriptedUser(answers=['Project A uses Python.'], steering={1: 'Project B uses Java.'})
    aux = ScriptedLM(['{"memories":[]}'], repeat_last=True)
    lm = ScriptedLM([call('ask_user', question='Which project and language?'),
                     call('echo', text='acknowledged'), 'Done.'], formatter=run_format_tool_call)
    s = run_agent_session(lm, make_fixture_tools().tools,
                          AgentConfig(user=user, mode='confirm', memory_dir=tmp_path, aux_lm=aux))
    assert s.send('Remember my project details.').status == 'done'
    assert user._polls == len(lm.calls) == 3
    payload = json.loads(aux.calls[-1][1]['content'])
    assert all(t in payload['user_text'] for t in ['Remember my project details.',
                                                  'Project A uses Python.', 'Project B uses Java.'])
    result = next(e for e in s.transcript if e['type'] == 'tool_result' and e['name'] == 'ask_user')
    assert any(result['content'] in m['content'] for m in lm.calls[1])
    assert any(e['type'] == 'user_answer' for e in s.transcript)
    assert not any(e[0] == 'approve' for e in user.log)
