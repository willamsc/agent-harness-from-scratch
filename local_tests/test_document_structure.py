"""Source positions, long paragraphs, and lazy document tool integration."""
import json

from cs329z_hw1 import adapters, data
from cs329z_hw1.agent import cardinal_tools
from cs329z_hw1.pipelines.documents import DocumentIndex
from cs329z_hw1.tokens import count_tokens
from cs329z_hw1.types import AgentConfig


def test_late_match_in_long_paragraph_preserves_source_and_lines():
    text = '# Example\n\n## Details\n\n' + 'ordinary words ' * 180 + 'uniqueneedle final evidence words.\n'
    index = DocumentIndex([{'doc_id': 'unknown', 'title': 'Example', 'text': text}])
    result = index.search('uniqueneedle', 1)[0]
    assert result['category'] == 'general' and result['section'] == 'Details'
    assert result['snippet'] in text and 'uniqueneedle' in result['snippet']
    assert count_tokens(result['snippet']) <= 150
    assert result['start_line'] == result['end_line'] == 5
    assert index.read('unknown', 5)['text'] == text.splitlines()[4]


def test_lazy_document_index_shared_by_search_and_read(monkeypatch, tmp_path):
    calls = []
    docs = [{'doc_id': 'pto-policy', 'title': 'PTO', 'text': '# PTO\n\nAnnual vacation allowance details.'}]
    monkeypatch.setattr(data, 'DOCS_DIR', tmp_path)
    def load():
        calls.append('load')
        return docs
    monkeypatch.setattr(data, 'load_docs', load)
    s = adapters.run_agent_session(None, None, AgentConfig())
    assert calls == []
    result = s.registry.execute('search_docs', {'query': 'vacation'})
    assert result.status == 'ok'
    assert json.loads(result.content)[0]['category'] == 'hr'
    result = s.registry.execute('read_doc', {'doc_id': 'pto-policy', 'start_line': 1})
    assert result.status == 'ok'
    assert json.loads(result.content)['text'] == docs[0]['text']
    assert calls == ['load']
