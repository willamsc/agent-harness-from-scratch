"""Business-independent entry point for explicit tools and model callables."""
from dataclasses import replace

from cardinal_agent.agent.session import AgentSession
from cardinal_agent.types import AgentConfig, ToolSpec


def create_session(lm, tools: list[ToolSpec], config: AgentConfig | None = None):
    """Build a runtime without loading the employee-assistant tool bundle.

    Model contract: messages -> text. Tools remain Python callables with JSON
    schemas. Optional memory/user interfaces are explicitly configured.
    """
    return AgentSession(lm, tools, replace(config or AgentConfig(), app_extensions=False))
