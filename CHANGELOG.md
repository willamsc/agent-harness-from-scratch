# Changelog

## Unreleased

- Add runtime-owned operation IDs, optional result lookup, and a transactional SQLite report example.
- Provide `cardinal runs list/show` with lock-aware activity and recovery summaries.
- Normalize OpenAI-compatible Chat Completions and Anthropic Messages client tool calls through the existing approval/execution path.
- Verify recovery using six real SIGKILL/fresh-process scenarios; retain deterministic protocol and fault-test artifacts.
- Current source regression: 424 passed, 13 live tests deselected; no new live-provider accuracy claim.

## 0.1.1

- Use the cardinal_agent runtime namespace and CARDINAL_* settings.
- Provide the cardinal CLI, isolated profiles, validated data import and release artifacts.
- Present product usage and readiness in the main documentation; retain licensing in NOTICE and LICENSE.

## 0.1.0

- Initial local preview and recorded installation verification.
