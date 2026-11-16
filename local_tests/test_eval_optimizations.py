"""Regression cases discovered by the first complete simulation run."""
import json
from concurrent.futures import ThreadPoolExecutor

from cs329z_hw1 import adapters, data
from cs329z_hw1.agent.memory import MemoryStore, MemoryController, explicit_replacement
from cs329z_hw1.llm import ScriptedLM
from cs329z_hw1.types import AgentConfig
from cs329z_hw1.pipelines.documents import DocumentIndex


def test_contrastive_correction_retires_old_value_and_hides_it_in_current_recall(tmp_path):
    store = MemoryStore(tmp_path)
    old = store.save('account number is 12345', key='account number', kind='profile')
    result = {'memories': [{'value': '54321', 'quote': "it's 54321, not 12345", 'scope': 'user',
                           'kind': 'profile', 'key': 'account number', 'supersedes': [old]}]}
    controller = MemoryController(None, AgentConfig(memory_dir=tmp_path,
                                 aux_lm=ScriptedLM([json.dumps(result)])))
    controller.user_text = "Oops, it's 54321, not 12345."
    controller.extract()
    assert store.records()[0]['status'] == 'superseded'
    assert '12345' not in store.recall('account number')
    assert '12345' in store.recall('history account number')
    assert not explicit_replacement('Project B also uses 54321; 12345 is not relevant.', '54321',
                                    {'value': 'account number is 12345'})


def test_duplicate_new_value_still_applies_explicit_supersession(tmp_path):
    store = MemoryStore(tmp_path)
    old = store.save('old', key='setting')
    new = store.save('new', key='setting')
    assert store.save('new', key='setting', supersedes=[old]) == new
    assert store.records()[0]['status'] == 'superseded'
    assert store.records()[1]['supersedes'] == [old]


def test_new_session_has_relevant_current_memory_before_first_model_reply(tmp_path):
    store = MemoryStore(tmp_path)
    old = store.save('account number is 12345', key='account number', kind='profile')
    store.save('54321', key='account number', kind='profile', supersedes=[old],
               source={'quote': "it's 54321, not 12345"})
    lm = ScriptedLM(['Your account number is 54321.'])
    aux = ScriptedLM(['{"memories":[]}'])
    s = adapters.run_agent_session(lm, [], AgentConfig(memory_dir=tmp_path, aux_lm=aux))
    assert '54321' in s.send('What is my account number?').text
    first = '\n'.join(m['content'] for m in lm.calls[0])
    assert '54321' in first and '12345' not in first


def test_digest_cache_single_flight_and_content_invalidation(monkeypatch):
    emails = [{'id': 'one', 'body': 'original'}]
    calls = []
    monkeypatch.setattr(data, 'emails_on', lambda date: emails)
    def digest(day, lm):
        calls.append(day[0]['body'])
        return 'Digest: ' + day[0]['body']
    monkeypatch.setattr(adapters, 'run_daily_digest', digest)
    session = adapters.run_agent_session(None, None, AgentConfig())
    fn = session.registry.tools['daily_digest'].fn
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: fn('2001-06-01'), range(8)))
    assert results == ['Digest: original'] * 8
    assert calls == ['original'] and fn.cache_hits == 7 and fn.cache_misses == 1
    emails[0]['body'] = 'changed'
    assert fn('2001-06-01') == 'Digest: changed'
    assert calls == ['original', 'changed']


def test_retrieval_includes_matching_update_pointer_without_hardcoded_policy_values():
    docs = [{'doc_id': 'old', 'title': 'Travel Policy',
             'text': '# Travel Policy\n\n## Flights\nFlight airfare approval rules and travel class.\n\n' * 5},
            {'doc_id': 'change', 'title': 'Finance Memo: Approval Changes',
             'text': '# Finance Memo: Approval Changes\n\nApproval requirements changed; consult the effective date.'}]
    results = DocumentIndex(docs).search('airfare flight approval class', 3)
    assert any(r['doc_id'] == 'change' and r['document_kind'] == 'update_or_memo' for r in results)
