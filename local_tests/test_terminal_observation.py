"""Save/re-read large observations, without using another command runner."""
import json

from cs329z_hw1 import sandbox
from cs329z_hw1.agent.terminal import terminal_spec
from cs329z_hw1.agent.registry import ToolRegistry
from cs329z_hw1.tokens import count_tokens
from cs329z_hw1.types import AgentConfig


def test_large_output_is_saved_and_middle_can_be_reread(tmp_path):
    config = AgentConfig(workspace=tmp_path, context_budget=6000)
    registry = ToolRegistry([terminal_spec(config)])
    cmd = "python3 -c \"for i in range(12000): print('row %06d ' % i + 'x' * 40)\""
    result = registry.execute('run_terminal', {'cmd': cmd})
    assert result.status == 'ok'
    observation = json.loads(result.content)
    assert observation['preview'] and observation['stdout_chars'] > 600000
    assert count_tokens(result.content) <= 750
    saved = tmp_path / observation['stdout_file']
    assert len(saved.read_text()) == observation['stdout_chars']
    reread = registry.execute('run_terminal', {'cmd': f"grep 'row 006000' {observation['stdout_file']}"})
    assert reread.status == 'ok' and 'row 006000' in reread.content


def test_config_is_forwarded_and_failures_include_all_streams(monkeypatch, tmp_path):
    seen = []
    def execute(cmd, *, workspace, timeout):
        seen.append((cmd, workspace, timeout))
        return sandbox.TerminalResult(stdout='partial', stderr='failure', exit_code=3)
    monkeypatch.setattr(sandbox, 'run_terminal', execute)
    registry = ToolRegistry([terminal_spec(AgentConfig(workspace=tmp_path, terminal_timeout=0.5))])
    result = registry.execute('run_terminal', {'cmd': 'example'})
    assert result.status == 'tool_error'
    observation = json.loads(result.content)
    assert observation['stdout'] == 'partial' and observation['stderr'] == 'failure'
    assert observation['exit_code'] == 3
    assert seen == [('example', tmp_path, 0.5)]
