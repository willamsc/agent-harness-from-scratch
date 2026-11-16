"""Offline checks for the local provider extension; no paid API calls."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from cardinal_agent import llm


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(llm, "_load_env", lambda: None)
    for name in ("CARDINAL_LLM_PROVIDER", "CARDINAL_GRADING_MODEL", "CARDINAL_USER_MODEL",
                 "CARDINAL_JUDGE_MODEL", "CARDINAL_REASONING_EFFORT",
                 "CARDINAL_DEEPSEEK_THINKING", "CARDINAL_BUDGET_USD"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CARDINAL_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-deepseek-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-openrouter-key")
    monkeypatch.setattr(llm, "_NO_TEMPERATURE", set())
    monkeypatch.setattr(llm, "_NO_EFFORT", set())


def fake_client(monkeypatch, finish="stop"):
    import openai

    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="OK"), finish_reason=finish)],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=10,
                              prompt_cache_hit_tokens=60),
    )
    client = Mock()
    client.chat.completions.create.return_value = response
    factory = Mock(return_value=client)
    monkeypatch.setattr(openai, "OpenAI", factory)
    return factory, client


def test_deepseek_request_usage_cache_and_budget(monkeypatch):
    monkeypatch.setenv("CARDINAL_LLM_PROVIDER", "deepseek")
    factory, client = fake_client(monkeypatch)
    lm = llm.LM()
    messages = [{"role": "user", "content": "Hello"}]
    assert lm(messages) == "OK"
    assert factory.call_args.kwargs["base_url"] == llm.DEEPSEEK_URL
    assert factory.call_args.kwargs["api_key"] == "fake-deepseek-key"
    request = client.chat.completions.create.call_args.kwargs
    assert request["model"] == "deepseek-flash"
    assert request["extra_body"] == {"thinking": {"type": "disabled"}}
    row, = llm.read_ledger()
    assert row["cached_tokens"] == 60
    assert row["cost_usd"] == pytest.approx((40 * .30 + 60 * .006 + 10 * 1.20) / 1e6)
    monkeypatch.setenv("CARDINAL_BUDGET_USD", str(row["cost_usd"] / 2))
    assert lm(messages) == "OK"  # Cached responses remain available over budget.
    assert client.chat.completions.create.call_count == 1
    with pytest.raises(llm.BudgetExceeded):
        lm([{"role": "user", "content": "Different"}])


def test_truncation_is_charged_but_not_cached(monkeypatch):
    monkeypatch.setenv("CARDINAL_LLM_PROVIDER", "deepseek")
    _, client = fake_client(monkeypatch, finish="length")
    lm = llm.LM()
    for _ in range(2):
        with pytest.raises(llm.OutputTruncated):
            lm([{"role": "user", "content": "Hello"}])
    assert client.chat.completions.create.call_count == 2
    assert len(llm.read_ledger()) == 2


def test_openrouter_defaults_and_extensions_are_preserved(monkeypatch):
    factory, client = fake_client(monkeypatch)
    lm = llm.LM()
    lm([{"role": "user", "content": "Hello"}])
    assert lm.model == llm.DEFAULT_MODELS["grading"]
    assert factory.call_args.kwargs["base_url"] == llm.OPENROUTER_URL
    assert factory.call_args.kwargs["api_key"] == "fake-openrouter-key"
    assert client.chat.completions.create.call_args.kwargs["extra_body"] == {
        "usage": {"include": True}, "reasoning": {"effort": "low"},
    }


def test_roles_overrides_and_cache_isolation(monkeypatch):
    messages = [{"role": "user", "content": "Hello"}]
    router_key = llm.LM("deepseek-flash")._key(messages)
    monkeypatch.setenv("CARDINAL_LLM_PROVIDER", "deepseek")
    assert all(llm.LM(role).model == "deepseek-flash" for role in llm.DEFAULT_MODELS)
    plain_key = llm.LM()._key(messages)
    assert plain_key != router_key
    monkeypatch.setenv("CARDINAL_DEEPSEEK_THINKING", "enabled")
    assert llm.LM()._key(messages) != plain_key
    monkeypatch.setenv("CARDINAL_JUDGE_MODEL", "deepseek-v4-pro")
    assert llm.LM("judge").model == "deepseek-v4-pro"


def test_missing_key_and_invalid_provider(monkeypatch):
    monkeypatch.setenv("CARDINAL_LLM_PROVIDER", "deepseek")
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
        llm.LM()([{"role": "user", "content": "Hello"}])
    monkeypatch.setenv("CARDINAL_LLM_PROVIDER", "typo")
    with pytest.raises(ValueError, match="CARDINAL_LLM_PROVIDER"):
        llm.LM()
