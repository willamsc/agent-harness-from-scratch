"""Exercise real multi-hop control flow with deterministic model decisions."""
import json

import pytest

from cardinal_agent.adapters import run_email_qa
from cardinal_agent.llm import ScriptedLM


def scripted(*replies):
    return ScriptedLM([json.dumps(reply) if isinstance(reply, (dict, list)) else reply for reply in replies])


def test_two_hops_accumulate_deduplicate_and_validate_citations():
    first = {'id': 'em-001', 'body': 'Heron approver is Alice.'}
    second = {'id': 'em-002', 'body': 'Alice works in Boulder 302.'}
    queries = []

    def search(query, k):
        queries.append((query, k))
        return [first] if len(queries) == 1 else [first, second]

    lm = scripted({'query': 'Heron approval'}, {'action': 'search', 'query': 'Alice office'},
                  {'action': 'answer', 'answer': 'Boulder 302',
                   'support': ['em-001', 'invented', 'em-002', 'em-001', {}, 1]})
    assert run_email_qa('Where is the Heron approver?', search, lm) == {
        'answer': 'Boulder 302', 'support': ['em-001', 'em-002']}
    assert queries == [('Heron approval', 10), ('Alice office', 10)]
    last_input = json.loads(lm.calls[-1][1]['content'])
    assert last_input['emails'] == [first, second]
    assert last_input['question'] == 'Where is the Heron approver?'
    assert last_input['searches_remaining'] == 1


def test_search_limit_and_model_limit_even_when_model_keeps_searching():
    queries = []
    lm = ScriptedLM([json.dumps({'action': 'search', 'query': 'again'})], repeat_last=True)
    def search(query, k):
        queries.append(query)
        return []
    assert run_email_qa('original', search, lm) == {'answer': None, 'support': []}
    assert queries == ['again'] * 3
    assert len(lm.calls) == 4
    assert json.loads(lm.calls[-1][1]['content'])['searches_remaining'] == 0


def test_empty_search_can_recover_and_bad_initial_query_uses_question():
    queries = []
    def search(query, k):
        queries.append(query)
        return [] if len(queries) == 1 else [{'id': 'found'}]
    lm = scripted('garbage', {'action': 'search', 'query': 'better'},
                  {'action': 'answer', 'answer': 'fact', 'support': ['found']})
    assert run_email_qa('original', search, lm)['answer'] == 'fact'
    assert queries == ['original', 'better']


@pytest.mark.parametrize('decision', [
    {}, [], 'invalid', {'action': 'search', 'query': []},
    {'action': 'answer', 'answer': None, 'support': []},
    {'action': 'answer', 'answer': 42, 'support': ['found']},
    {'action': 'answer', 'answer': 'fact', 'support': 'found'},
    {'action': 'answer', 'answer': 'fact', 'support': ['invented']},
])
def test_malformed_decisions_and_unsupported_answers_abstain(decision):
    lm = scripted({'query': 'first'}, decision)
    assert run_email_qa('question', lambda q, k: [{'id': 'found'}], lm) == {
        'answer': None, 'support': []}


def test_fenced_json_and_independent_questions():
    lm = scripted('```json\n{"query":"first"}\n```',
                  {'action': 'answer', 'answer': 'fact', 'support': ['old']},
                  {'query': 'second'}, {'action': 'answer', 'answer': 'fact', 'support': ['old']})
    assert run_email_qa('first', lambda q, k: [{'id': 'old'}], lm)['answer'] == 'fact'
    assert run_email_qa('second', lambda q, k: [], lm)['answer'] is None
