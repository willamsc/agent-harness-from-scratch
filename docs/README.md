# 项目文档导航

本目录分为当前设计、历史实现笔记和原始评测记录。文件保留原路径，便于旧日志、源码快照和 Git 提交相互追溯。01–15 是逐步开发时的说明，内嵌代码与指标不一定对应当前源码；了解当前行为优先读当前设计和实现文件。

## 推荐阅读顺序

| 阶段 | 文档 | 目的 |
| --- | --- | --- |
| 1 | [项目 README](../README.md) | 了解定位、运行方式、当前版本边界 |
| 2 | [架构](architecture.md) | 理解通用 Harness 与员工助手的依赖方向 |
| 3 | [持久运行时](16-durable-runtime.md) | 理解执行循环、checkpoint、预算与恢复 |
| 4 | [操作幂等与核对](18-operation-reconciliation.md) | 理解操作 ID、确定回执和人工核实 |
| 5 | [真实进程故障测试](17-process-faults.md) | 核对 SIGKILL 场景与真实副作用数量 |
| 6 | [原生工具适配器](20-native-tool-adapters.md) | 理解文本、OpenAI 与 Anthropic 的统一执行路径 |
| 7 | [运行状态](19-run-status.md) | 理解锁探测、任务状态和查询 CLI |
| 8 | [当前 live 验证](21-live-validation.md) | 理解真实调用结果与未通过检查 |
| 9 | [评测目录说明](evaluations/README.md) | 找到原始日志、指标、失败和复现记录 |

## 按技术主题查阅

| 主题 | 实现笔记 | 当前主要代码 |
| --- | --- | --- |
| 邮件分类与摘要 | [01 分类](01-priority.md)、[02 日报](02-daily-digest.md) | `cardinal_agent/adapters.py`、`pipelines/daily_digest.py` |
| 邮件检索与多跳问答 | [03 BM25](03-bm25.md)、[04 问答](04-email-qa.md) | `pipelines/bm25.py`、`pipelines/email_qa.py` |
| 工具注册、验证与协议 | [05 注册表](05-tool-registry.md)、[06 协议](06-tool-protocol.md) | `agent/registry.py`、`agent/protocol.py` |
| 执行循环与业务装配 | [07 双循环](07-agent-loop.md)、[08 工具装配](08-cardinal.md) | `agent/session.py`、`agent/cardinal_tools.py`、`harness.py` |
| 文档检索与证据 | [09 文档](09-search-docs.md) | `pipelines/documents.py` |
| 终端与大输出 | [10 终端](10-terminal.md) | `agent/terminal.py`、`sandbox.py` |
| 上下文压缩 | [11 压缩](11-compaction.md) | `agent/compaction.py` |
| 持久记忆 | [12 记忆](12-memory.md) | `agent/memory.py` |
| 交互、审批与拒绝规则 | [13 交互](13-interactive.md)、[14 安全](14-guardrails.md) | `agent/session.py`、`user.py` |
| 模拟用户评估 | [15 综合评估](15-sim-eval.md) | `simulation/`、`tests/fixtures/personas/` |
| 新增 Harness 工程能力 | [16–20 设计](16-durable-runtime.md)及上方推荐顺序 | `agent/checkpoint.py`、`agent/runs.py`、`models/native.py` |

代码路径均相对于仓库根目录。历史笔记用于理解设计演进，代码示例不是自动同步的 API 文档。

## 使用、交付与项目成熟度

- [本地使用](local-usage.md)：profile、导入、模型配置和常用命令。
- [发布流程](releasing.md)：源码导出、wheel、manifest 与 GitHub Release。
- [本地安装验证](local-release-verification.md)：已执行的独立环境验证。
- [可用性与后续路线](product-readiness.md)：当前能力及尚缺的企业化功能。
- [项目设计与验证概览](project-case-study.md)：核心能力、验证入口与当前边界。
- [命名空间迁移](namespace-migration.md)：历史路径与当前包名的关系。
- [优化复盘](optimization-review.md)：保留成功与失败，不将缓存收益误写成算法提升。

## 最重要的证据入口

- [当前真实模型验证](21-live-validation.md)：原生 46/46、live pytest 12/13、模拟任务 19/20；文本协议 16/20 未通过阈值。

- [当前离线回归：424 通过](evaluations/20261116-062855-harness-resilience/metrics.json)，包含 6 个真实进程故障场景、24 个原生适配器测试；13 个 live 测试未运行。
- [历史模拟用户基线：18/20](evaluations/20261116-120629-sim-eval-live-baseline/metrics.json)：真实模型运行，公开固定场景、带既有缓存，非生产成功率。
- [历史早期指标补录](evaluations/part1-historical.json)：分类、BM25、多跳问答等，缺完整原始日志的项目已明确标注。

许可与来源统一见 [NOTICE](../NOTICE.md) 和 [LICENSE](../LICENSE)。原始评测中的旧名称、失败记录和快照保持原样。
