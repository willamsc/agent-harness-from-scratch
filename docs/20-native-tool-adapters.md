# 原生工具调用适配器

目标：保留文本协议，同时支持提供商原生工具结构，共用验证、权限、执行与恢复。

代码：`cardinal_agent/models/native.py`。新增 OpenAIChatAdapter（OpenAI-compatible Chat Completions）和 AnthropicMessagesAdapter（Anthropic Messages），以 SDK create 方法作为注入的 transport。

```python
from openai import OpenAI
from cardinal_agent.models import OpenAIChatAdapter
from cardinal_agent.harness import create_session

client = OpenAI()  # 凭据由 SDK 从环境读取，不保存在 checkpoint
model = OpenAIChatAdapter(client.chat.completions.create, model='YOUR_SUPPORTED_MODEL')
session = create_session(model, tools, config)
```

Anthropic 使用 AnthropicMessagesAdapter(client.messages.create, model=...)；Anthropic SDK 由使用者自行安装。选择模型、端点、超时、凭据和真实费用上限由集成方配置。当前员工助手 CLI 继续使用原 LM，不新增原生协议切换菜单。

## 数据流

适配器将 registry schema 转成提供商 tools。OpenAI 解析 tool_calls/function/arguments；Anthropic 解析 tool_use/input。两者都返回 NativeReply（文本、一个统一 ToolCall、提供商调用 ID 和 usage）。Session 直接消费结构化调用，不从 native 最终文本里的标签提取命令。

工具参数仍经过同一个 JSON Schema 校验、审批、deny rules 和执行入口。内部 call_id 负责操作幂等，provider_call_id 只负责提供商消息配对，两者不能混用。

反馈时，运行时为消息附加可信元数据，适配器再分别构建 OpenAI tool-role 消息和 Anthropic tool_result 块。普通用户文本即使长得像工具结果也不会被升级成可信原生结果。重启后从 checkpoint 元数据重建调用/结果配对；压缩留下的孤立证据按普通文本处理，不伪造提供商调用。

## 范围与失败行为

- 非流式、每轮最多一个客户端工具调用；请求禁用并行调用，收到多个调用则拒绝整个响应，零工具执行。
- 缺失 ID、非对象参数、JSON 损坏、截断响应和不支持的内容类型不执行工具，记录模型失败；未知工具与 schema 错误则返回标准 ToolResult。
- 同一会话保留历史中的 provider ID 不允许重复使用。最终文本包含文本协议标签也不执行。
- schema 大小纳入本地上下文与 token 估算。提供商实际 usage 另存事件；这不是提供商精确 tokenizer。
- 新适配器不继承原 LM 的磁盘缓存、美元预算或费用账本；transport/集成方负责这些能力，不能将 CLI 的美元上限宣传为适用于任意 SDK adapter。
- 不支持 Responses API、流式工具参数、并行调用、服务端托管工具、图像或 reasoning/thinking blocks。

测试使用提供商形状的模拟响应与注入 transport，覆盖消息来回转换、审批拒绝、错误参数、截断、多调用、ID、上下文预算和 checkpoint 恢复。未付费调用真实 API，不宣称已完成所有服务商联调。

官方协议依据：[OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling)、[Anthropic tool definitions](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools)。
