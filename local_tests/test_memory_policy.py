"""Explicit-source grounding, scoped corrections and durable isolated stores."""
import json

from cs329z_hw1.agent.memory import MemoryController, MemoryStore
from cs329z_hw1.llm import ScriptedLM
from cs329z_hw1.types import AgentConfig


def test_scoped_correction_does_not_replace_another_project(tmp_path):
    store = MemoryStore(tmp_path)
    a = store.save('Python', 'project:A', 'project_fact', 'language')
    b = store.save('Java', 'project:B', 'project_fact', 'language')
    c = store.save('Java', 'project:A', 'project_fact', 'language', supersedes=[a, b])
    records = {r['id']: r for r in MemoryStore(tmp_path).records()}
    assert records[a]['status'] == 'superseded'
    assert records[b]['status'] == 'active'
    assert records[c]['supersedes'] == [a]
    assert 'Python' not in store.recall('project A language')
    assert 'Python' in store.recall('history project A language')
    assert MemoryStore(tmp_path / 'other').recall('language') == 'No matching memories stored.'


def test_automatic_extraction_requires_quote_and_value_in_user_statement(tmp_path):
    candidates = [
        {'quote': 'Project A uses Python.', 'value': 'Python', 'scope': 'project:A', 'kind': 'project_fact', 'key': 'language'},
        {'quote': 'User prefers Java.', 'value': 'Java', 'scope': 'user', 'kind': 'preference', 'key': 'language'},
        {'quote': 'Project A uses Python.', 'value': 'Java', 'scope': 'project:A', 'kind': 'project_fact', 'key': 'language'},
    ]
    aux = ScriptedLM([json.dumps({'memories': candidates})], repeat_last=True)
    controller = MemoryController(None, AgentConfig(memory_dir=tmp_path, aux_lm=aux))
    controller.user_text = 'Project A uses Python.'
    assert len(controller.extract()) == 1
    controller.extract()
    assert len(controller.store.records()) == 1
    assert controller.store.records()[0]['source']['quote'] == controller.user_text


def test_additional_technology_does_not_implicitly_replace_old_fact(tmp_path):
    store = MemoryStore(tmp_path)
    identifier = store.save('Python', 'project:A', 'project_fact', 'language')
    result = {'memories': [{'quote': 'Project A also uses Java.', 'value': 'Java', 'scope': 'project:A',
                           'kind': 'project_fact', 'key': 'language', 'supersedes': [identifier]}]}
    controller = MemoryController(None, AgentConfig(memory_dir=tmp_path, aux_lm=ScriptedLM([json.dumps(result)])))
    controller.user_text = 'Project A also uses Java.'
    controller.extract()
    assert all(r['status'] == 'active' for r in store.records())


def test_corrupt_store_is_not_silently_overwritten(tmp_path):
    store = MemoryStore(tmp_path)
    store.path.write_text('{broken')
    try:
        store.save('fact')
    except ValueError:
        pass
    assert store.path.read_text() == '{broken'
