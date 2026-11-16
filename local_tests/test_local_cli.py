"""Local product flows use isolated profiles and never need paid API calls."""
import json
from pathlib import Path

from cs329z_hw1.app.cli import main, import_emails, import_docs


def test_demo_initialization_and_offline_search(tmp_path, capsys):
    home = tmp_path / 'profile'
    args = ['--home', str(home)]
    assert main(args + ['init', '--demo']) == 0
    assert main(args + ['demo', 'Aurora owner']) == 0
    output = capsys.readouterr().out
    assert 'Morgan Lee' in output and 'no API call' in output
    config = json.loads((home / 'config.json').read_text())
    assert config['demo_data'] and 'api_key' not in config
    assert main(args + ['init']) == 2


def test_import_validation_does_not_replace_valid_archive(tmp_path):
    home = tmp_path / 'profile'
    assert main(['--home', str(home), 'init', '--demo']) == 0
    archive = home / 'data/emails.jsonl'
    before = archive.read_bytes()
    source = tmp_path / 'bad.jsonl'
    source.write_text('{"id":"incomplete"}\n')
    assert main(['--home', str(home), 'import', 'emails', str(source), '--replace']) == 2
    assert archive.read_bytes() == before


def test_import_dates_normalized_and_duplicate_ids_rejected(tmp_path):
    home = tmp_path / 'profile'
    source = tmp_path / 'mail.jsonl'
    email = {'id': 'a', 'date': '2026-11-16T08:00:00+08:00', 'from': 'a', 'to': [], 'subject': '', 'body': ''}
    source.write_text(json.dumps(email) + '\n')
    import_emails(source, home)
    saved = json.loads((home / 'data/emails.jsonl').read_text())
    assert saved['date'] == '2026-11-16T00:00:00Z'
    source.write_text((json.dumps(email) + '\n') * 2)
    try:
        import_emails(source, home, replace=True)
    except ValueError:
        pass
    assert json.loads((home / 'data/emails.jsonl').read_text()) == saved


def test_document_import_requires_explicit_replace_and_bounds_lines(tmp_path):
    home = tmp_path / 'profile'
    source = tmp_path / 'Policy.md'
    source.write_text('# Policy\n\nOriginal policy text.\n')
    import_docs(source, home)
    source.write_text('# Policy\n\nUpdated policy text.\n')
    assert main(['--home', str(home), 'init']) == 0
    assert main(['--home', str(home), 'import', 'docs', str(source)]) == 2
    assert main(['--home', str(home), 'import', 'docs', str(source), '--replace']) == 0
    source.write_text('x' * 6001)
    assert main(['--home', str(home), 'import', 'docs', str(source), '--replace']) == 2
    assert 'Updated' in (home / 'data/docs/policy.md').read_text()


def test_profile_memory_deletion_and_history_path_validation(tmp_path):
    home = tmp_path / 'profile'
    assert main(['--home', str(home), 'init']) == 0
    from cs329z_hw1.agent.memory import MemoryStore
    store = MemoryStore(home / 'memory')
    identifier = store.save('explicit test fact')
    assert main(['--home', str(home), 'memory', '--forget', identifier]) == 0
    assert store.records() == []
    assert main(['--home', str(home), 'history', '--show', '../config']) == 2
    assert main(['--home', str(home), 'configure', '--budget', 'nan']) == 2


def test_cli_chat_is_confirm_only_and_saves_after_failure(tmp_path, monkeypatch, capsys):
    from cs329z_hw1 import adapters
    from cs329z_hw1.types import AgentResult
    home = tmp_path / 'profile'
    assert main(['--home', str(home), 'init', '--demo', '--model', 'deepseek-flash']) == 0
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-not-a-real-key')
    configs = []
    class Session:
        transcript = [{'type': 'user', 'content': 'hello'}]
        def send(self, message):
            raise RuntimeError('simulated failure')
    def factory(lm, tools, config):
        configs.append((tools, config))
        return Session()
    monkeypatch.setattr(adapters, 'run_agent_session', factory)
    assert main(['--home', str(home), 'ask', 'hello']) == 1
    tools, config = configs[0]
    assert config.mode == 'confirm' and all(t.name != 'run_terminal' for t in tools)
    record = json.loads(next((home / 'conversations').glob('*.json')).read_text())
    assert record['turns'][0]['status'] == 'error'
    assert 'test-not-a-real-key' not in json.dumps(record)
