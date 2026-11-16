"""Summary validation, correction retention, and auxiliary budget bounds."""
import json

import pytest

from cardinal_agent.adapters import run_agent_session, run_format_tool_call
from cardinal_agent.llm import ScriptedLM
from cardinal_agent.tokens import count_message_tokens
from cardinal_agent.types import AgentConfig
from tests.fixture_tools import make_fixture_tools


@pytest.mark.parametrize('summary', [
    'bad JSON',
    json.dumps({k: [] for k in ['goals', 'constraints', 'facts', 'attempts', 'failures', 'pending']}),
    json.dumps({k: ['x' * 9000] for k in ['goals', 'constraints', 'facts', 'attempts', 'failures', 'pending']}),
])
def test_summary_fallback_preserves_user_correction_and_bounds_both_models(summary):
    aux = ScriptedLM([summary], repeat_last=True)
    script = []
    for _ in range(12):
        script += [{'tool_call': {'name': 'big_output', 'args': {'n_lines': 100}}}, 'Done.']
    lm = ScriptedLM(script, formatter=run_format_tool_call)
    s = run_agent_session(lm, make_fixture_tools().tools, AgentConfig(context_budget=4000, aux_lm=aux))
    for i in range(12):
        request = 'Budget is 18450, location Boulder.' if i == 0 else (
            'Correction: budget is now 15000, location remains Boulder.' if i == 1 else f'Check {i}.')
        assert s.send(request).status == 'done'
    assert aux.calls
    assert all(count_message_tokens(m) <= 4000 for m in lm.calls + aux.calls)
    final_text = '\n'.join(m['content'] for m in lm.calls[-1])
    assert '15000' in final_text and 'Boulder' in final_text
    assert any(e['type'] == 'compaction' for e in s.transcript)


def test_impossible_current_request_stops_without_truncating_or_calling_model():
    lm = ScriptedLM([])
    s = run_agent_session(lm, [], AgentConfig(context_budget=100))
    request = 'large request ' * 200
    result = s.send(request)
    assert result.status == 'token_budget' and not lm.calls
    assert result.transcript[0]['content'] == request
