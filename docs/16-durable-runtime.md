# 持久运行时：实现与故障边界

本次将项目的主要定位从员工助手扩展为可嵌入的 Agent Harness。员工助手继续作为参考应用。未增加真实邮箱连接器，也未重新运行付费模型评估。

## 通用入口

`cardinal_agent.harness.create_session(model, tools, config)` 使用显式工具列表，不自动加载邮件、文档或终端工具。模型接口仍为消息列表输入、字符串输出。配置中的 memory/user 为显式扩展；业务默认工具保留在应用构建层。现有 adapters API 保持兼容。

相关代码：`cardinal_agent/harness.py`、`agent/session.py`、`types.py`。

## 保存与恢复

配置 `AgentConfig(checkpoint_path=...)` 后，在开始用户轮次、模型请求前、工具执行前、结果记录后和结束时保存状态。文件包含版本、运行 ID、上下文、完整 transcript、预算计数、原始用户来源、待确认调用及策略签名。

`agent/checkpoint.py` 使用同目录临时文件、文件 fsync、原子 replace 和目录 fsync。Linux/WSL 的 flock 保证同一个 checkpoint 同时只有一个发送或恢复操作。锁文件持续存在不代表锁被占用；进程退出后操作系统释放锁。文件是本地可信状态，不是面向不可信上传文件的恢复格式。

模型请求前预留调用次数与输入 token，避免通过反复崩溃重置上限。提供商可能已经产生但尚未返回的输出 token 无法从 checkpoint 准确获知；费用仍应以服务商账单核对，不宣称恢复实现了严格费用上限。

工具调用意图先落盘，随后经过验证、审批和执行；结果加入上下文后再次落盘。两个持久化点之间退出时，调用可能尚未执行，也可能已经完成。恢复不自动重试，包括只读工具。工具提供结果核对回调时先查询回执，查到确定结果后继续；否则暂停并抛出 `RecoveryRequired`。

```python
from cardinal_agent.types import ToolResult
# 先检查真实文件、服务端操作记录等，确认结果后：
result = session.resume(ToolResult('ok', 'Operator verified the operation completed.'))
```

该接口代表人工核实的结果，不会重新调用工具。不要编造确认；不能确认时保持暂停。调用方必须重新提供相同模型、工具函数和数据环境。恢复校验 schema、模型/提供商标识、审批模式、deny rules、路径与预算；无法证明 Python 函数实现或路径内数据没有变化。自定义 callable 没有模型标识时由集成方保证一致性。

此机制避免已持久化结果的自动重放，但不保证任意外部操作恰好一次。工具自身的幂等键、外部事务核对仍需由工具实现。后台记忆提取、用户问答等内部操作没有各自独立事务；崩溃后可能重复模型请求。多 checkpoint 共享同一外部文件也不受这把锁保护。

## CLI 与运行控制

chat/ask 默认写入 profile/checkpoints/ID.json。失败日志会输出会话 ID；`cardinal chat --resume ID` 恢复未完成轮次，必须保持原模型和终端启用选项。已结束的轮次不能当作未完成轮次恢复。CLI 没有提供结果不明工具的自动确认开关，需通过 Python 接口人工处理。

`session.cancel()` 是协作式取消，在下一模型或工具边界检查。若模型返回工具调用前收到取消，则不执行该工具。无法强行打断任意阻塞 Python 函数；终端仍使用已有超时机制。交互 CLI 仍是同步界面，不宣称已有后台任务实时 steering UI。

## 追踪与测试

新增事件包括 run_started/run_resumed/run_finished、model_started、tool_timing。新增事件及工具调用/结果带运行 ID、序号、时间戳；调用/结果以 call_id 关联。旧事件保持兼容，尚未接入 OpenTelemetry，也不是完整的远程 tracing 平台。

`local_tests/test_checkpoint.py` 通过真实临时文件与故障注入，验证结果持久化、执行期间中断、人工核对、预算不重置、策略/模型变化拒绝恢复、锁竞争、取消阻止执行、无业务工具的通用入口及 CLI 恢复。无真实 API 请求。原测试数据与新验证日志分别保留，不能将这些确定性检查换算为生产成功率或用户提效比例。

后续实现补充：[真实进程故障](17-process-faults.md)、[操作幂等与核对](18-operation-reconciliation.md)、[状态查询](19-run-status.md)、[原生工具适配](20-native-tool-adapters.md)。
