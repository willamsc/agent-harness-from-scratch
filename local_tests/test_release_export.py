"""The release allowlist excludes private state even if accidentally tracked."""
from tools.build_release import allowed


def test_release_excludes_runtime_and_secrets():
    for path in ['.env', '.env.local', 'docs/.env.production', 'runs/chat.json',
                 '.aws/credentials', '.cardinal/config.json', 'data/emails/emails.jsonl',
                 'data/emails.jsonl.gz', 'cardinal_agent/__pycache__/x.pyc', 'private.key',
                 '../escape.py', '/absolute/path', 'unrelated/private.json']:
        assert not allowed(path), path
    for path in ['.env.example', 'pyproject.toml', 'uv.lock', 'README.md', 'LICENSE',
                 'cardinal_agent/app/demo/emails.jsonl', 'docs/15-sim-eval.md', 'data/docs/pto-policy.md']:
        assert allowed(path), path
