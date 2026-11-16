"""Check actual tool wiring, lazy initialization, and model separation."""
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from cs329z_hw1 import adapters, data
from cs329z_hw1.agent import cardinal_tools
from cs329z_hw1.cardinal import cardinal_spec
from cs329z_hw1.types import AgentConfig


@pytest.fixture
def setup_archive(monkeypatch, tmp_path):
    emails = [{"id": "em-one", "date": "2001-06-01T00:00:00Z", "subject": "Heron",
               "body": "Heron " * 100},
              {"id": "em-two", "date": "2001-06-01T01:00:00Z", "subject": "Other", "body": "Different"}]
    counts = {"load": 0, "build": 0}
    monkeypatch.setattr(data, "EMAILS_PATH", tmp_path / 'emails.jsonl')
    def load():
        counts['load'] += 1
        return emails
    original = cardinal_tools.BM25Index
    def build(docs):
        counts['build'] += 1
        return original(docs)
    monkeypatch.setattr(data, 'load_emails', load)
    monkeypatch.setattr(cardinal_tools, 'BM25Index', build)
    return emails, counts


def test_lazy_read_and_concurrent_search_share_one_index(setup_archive):
    emails, counts = setup_archive
    s = adapters.run_agent_session(lambda messages: 'Hello', None, AgentConfig())
    assert counts == {'load': 0, 'build': 0}
    result = s.registry.execute('read_email', {'email_id': 'em-one'})
    assert json.loads(result.content) == emails[0]
    assert counts == {'load': 1, 'build': 0}
    other = adapters.run_agent_session(lambda messages: 'Hello', None, AgentConfig())
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: other.registry.execute('search_emails', {'query': 'Heron'}), range(8)))
    assert counts == {'load': 1, 'build': 1}
    for result in results:
        item = json.loads(result.content)[0]
        assert item['id'] == 'em-one' and len(item['snippet']) == 400 and item['snippet_truncated']
    assert s.registry.execute('read_email', {'email_id': 'missing'}).status == 'tool_error'
    assert json.loads(s.registry.execute('search_emails', {'query': 'absent'}).content) == []


def test_workflows_use_auxiliary_model_and_full_search_results(setup_archive, monkeypatch):
    emails, _ = setup_archive
    agent_lm = object()
    aux_lm = object()
    def qa(question, search, lm):
        assert lm is aux_lm and question == 'question'
        assert search('Heron', 5) == [emails[0]]
        return {'answer': 'Heron', 'support': ['em-one']}
    def digest(day, lm):
        assert lm is aux_lm and day == emails
        return 'Digest'
    monkeypatch.setattr(adapters, 'run_email_qa', qa)
    monkeypatch.setattr(adapters, 'run_daily_digest', digest)
    monkeypatch.setattr(data, 'emails_on', lambda date: emails if date == '2001-06-01' else [])
    s = adapters.run_agent_session(agent_lm, None, AgentConfig(aux_lm=aux_lm))
    assert json.loads(s.registry.execute('email_qa', {'question': 'question'}).content)['answer'] == 'Heron'
    assert s.registry.execute('daily_digest', {'date': '2001-06-01'}).content == 'Digest'


def test_configured_tools_do_not_duplicate_or_change_input(tmp_path):
    custom = cardinal_spec('ask_user', 'Custom', lambda question: 'Custom answer')
    tools = [custom]
    s = adapters.run_agent_session(None, tools, AgentConfig(user=object(), memory_dir=tmp_path))
    assert list(s.registry.tools) == ['ask_user', 'remember', 'recall']
    assert tools == [custom]
    assert s.registry.execute('ask_user', {'question': 'Hi'}).content == 'Custom answer'
    assert s.registry.execute('recall', {'query': 'Hi'}).status == 'ok'
