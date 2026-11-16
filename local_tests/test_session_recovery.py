"""Agreed promise correction, blank reply recovery, and finite retries."""
import pytest

from cs329z_hw1.adapters import run_agent_session, run_format_tool_call
from cs329z_hw1.llm import ScriptedLM
from cs329z_hw1.types import AgentConfig
from tests.fixture_tools import make_fixture_tools


def session(script, **settings):
    lm = ScriptedLM(script, formatter=run_format_tool_call)
    tools = make_fixture_tools()
    return run_agent_session(lm, tools.tools, AgentConfig(**settings)), lm, tools


@pytest.mark.parametrize('promise', ["I'll look that up.", '我去查一下。', 'I will check it now.'])
def test_promise_is_corrected_without_user_repeating_request(promise):
    s, lm, tools = session([promise, {'tool_call': {'name': 'add', 'args': {'a': 2, 'b': 3}}}, 'The answer is 5.'])
    result = s.send('Add two and three.')
    assert result.status == 'done'
    assert tools.count('add') == 1 and len(lm.calls) == 3
    assert any('did not execute' in m['content'] for m in lm.calls[1])


def test_third_promise_stops_and_next_send_can_recover():
    s, lm, tools = session(['我去查一下。'] * 3 + ['Hello.'])
    result = s.send('查一下。')
    assert result.status == 'malformed' and 'unfinished' in result.text
    assert len(lm.calls) == 3 and not tools.calls
    assert s.send('Hi.').status == 'done'


@pytest.mark.parametrize('reply', ['Which policy do you mean?', 'I cannot access that system.',
                                    'I will check it? Please clarify.', 'The answer is 5. I will check it later.'])
def test_substantive_replies_are_not_promises(reply):
    s, lm, _ = session([reply])
    assert s.send('Question').text == reply
    assert len(lm.calls) == 1


def test_empty_reply_recovers_and_repeated_empty_stops():
    s, _, _ = session([' ', 'Answer.'])
    assert s.send('Question').status == 'done'
    s, lm, _ = session([''] * 3)
    assert s.send('Question').status == 'malformed'
    assert len(lm.calls) == 3


def test_corrections_obey_model_budget():
    s, lm, _ = session(["I'll look that up."], max_turns=1)
    assert s.send('Question').status == 'max_turns'
    assert len(lm.calls) == 1
