# Cardinal Agent 架构

## 应用入口

cardinal_agent.app.cli 提供初始化、导入、诊断、聊天、单次问答、会话查看和记忆管理。cardinal 命令与 python -m cardinal_agent 使用同一入口。状态存于独立 profile，不向源码目录写用户业务数据。

## 执行与工具

agent.session 管理双循环、预算、用户审批和事件日志。agent.protocol 解析文本调用；agent.registry 用 JSON Schema 验证参数。agent.cardinal_tools 连接文档/邮件流水线，agent.terminal 统一调用受限执行器。

## 知识与状态

pipelines.bm25 使用倒排索引；pipelines.documents 保留章节与行号。agent.memory 存储带范围/时间/来源的事实，agent.compaction 缩减模型上下文，原始日志保持可追溯。

## 当前产品边界

单用户本地 profile、远端模型推理、手动资料导入、同步 CLI；不具备企业 SSO、多人文档权限、实时账号同步或生产可用性承诺。实际验证与后续路线见 local-release-verification.md 和 product-readiness.md。许可信息集中在 NOTICE.md 和 LICENSE。
