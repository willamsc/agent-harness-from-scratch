# Cardinal Agent 架构

## 可嵌入的 Harness

`cardinal_agent.harness.create_session` 接受模型 callable、显式 ToolSpec 列表和 AgentConfig，关闭默认业务工具补充。核心负责执行与状态，员工助手负责装配文档、邮件和终端能力。既有 adapters 默认入口保持兼容。

## 应用入口

cardinal_agent.app.cli 提供初始化、导入、诊断、聊天、单次问答、会话查看和记忆管理。cardinal 命令与 python -m cardinal_agent 使用同一入口。状态存于独立 profile，不向源码目录写用户业务数据。

## 执行与工具

agent.session 管理双循环、预算、用户审批和事件日志。agent.protocol 解析文本调用；agent.registry 用 JSON Schema 验证参数。agent.cardinal_tools 连接文档/邮件流水线，agent.terminal 统一调用受限执行器。

## 持久执行与追踪

`agent.checkpoint` 原子写入运行状态，使用本地进程锁限制同一 checkpoint 并发发送/恢复。模型请求前预留预算，工具执行前持久化意图，结果反馈后保存上下文。`session.resume()` 恢复已中断轮次；结果不明工具先使用可选回调核对回执，无法确认时要求人工核实，不自动重试。运行与工具调用有独立 ID，工具耗时和模型失败事件保存在 transcript。此实现不提供分布式锁或通用外部事务。

`session.cancel()` 在执行边界协作停止，不能强行终止任意 Python 工具。设计、代码入口和故障验证见 [持久运行时](16-durable-runtime.md)。

## 知识与状态

pipelines.bm25 使用倒排索引；pipelines.documents 保留章节与行号。agent.memory 存储带范围/时间/来源的事实，agent.compaction 缩减模型上下文，原始日志保持可追溯。

## 当前产品边界

单用户本地 profile、远端模型推理、手动资料导入、同步 CLI；不具备企业 SSO、多人文档权限、实时账号同步或生产可用性承诺。实际验证与后续路线见 local-release-verification.md 和 product-readiness.md。许可信息集中在 NOTICE.md 和 LICENSE。

## 原生协议、操作回执与状态

models.native 将 OpenAI Chat Completions / Anthropic Messages 的客户端工具响应归一化为 NativeReply，再进入同一校验与审批路径。提供商 call ID 与运行时 operation ID 分离保存。

ToolSpec 可成对提供 execute_with_id / lookup_result；恢复时只查询，不自动重试未确认操作。examples.durable_reports 演示 SQLite 事务内去重。agent.runs 结合 checkpoint 和 OS 锁提供 runs list/show，不需要创建模型。
