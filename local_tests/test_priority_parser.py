"""Additional parser cases agreed during the priority design discussion."""
import copy

import pytest

from cs329z_hw1.adapters import parse_priority, run_priority


@pytest.mark.parametrize("reply, expected", [
    ('{"category":"normal","reason":"No urgent action is needed."}', 'normal'),
    ('```json\n{"category":" URGENT ","reason":"Today."}\n```', 'urgent'),
    ('{"category":"ignore","reason":null}', 'ignore'),
    ('{"category":"high","reason":"An urgent issue."}', 'unknown'),
    ('{"category":42}', 'unknown'),
    ('null', 'unknown'),
    ('[]', 'unknown'),
    ('"abnormal"', 'unknown'),
    ('Either urgent or normal. Final: normal', 'normal'),
    ('Final label: urgent\nFinal answer: IGNORE', 'ignore'),
    ('urgent or normal', 'unknown'),
    ('{"category":"urgent"', 'urgent'),
    ('', 'unknown'),
    ('   ', 'unknown'),
    ('%%% {]', 'unknown'),
])
def test_priority_reply_fallbacks(reply, expected):
    result = parse_priority(reply)
    assert result['category'] == expected
    assert isinstance(result['reason'], str) and result['reason'].strip()


def test_one_call_separate_prompts_and_unchanged_email():
    email = {'date': '2001-06-01', 'from': 'a', 'to': ['b'], 'subject': '', 'body': ''}
    before = copy.deepcopy(email)
    calls = []

    def lm(messages):
        calls.append(messages)
        return '{"category":"normal","reason":"No deadline."}'

    assert run_priority(email, lm)['category'] == 'normal'
    assert len(calls) == 1
    assert [m['role'] for m in calls[0]] == ['system', 'user']
    assert '2001-06-01' in calls[0][1]['content']
    assert email == before


def test_model_failure_is_not_reported_as_a_classification():
    def lm(messages):
        raise RuntimeError('provider unavailable')

    with pytest.raises(RuntimeError, match='provider unavailable'):
        run_priority({}, lm)
