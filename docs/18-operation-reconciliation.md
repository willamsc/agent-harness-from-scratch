# 工具幂等与结果核对

目标：允许具备外部回执能力的工具自动核对中断结果；其他工具维持人工处理。

ToolSpec 新增一对可选回调：

```python
execute_with_id(args: dict, operation_id: str) -> Any
lookup_result(args: dict, operation_id: str) -> ToolResult | None
```

两个回调必须同时提供。operation_id 由运行时生成，复用持久化 call_id，不出现在模型参数 schema 中。执行仍先经过参数验证、deny rules 和用户审批，然后由 ToolRegistry 把参数副本与 ID 交给 execute_with_id。普通工具继续使用 fn(**args)。revision 默认 "1"，工具实现或恢复语义改变时由开发者递增。

resume 的顺序：校验模型、策略、工具 schema 和恢复合同；恢复 checkpoint；对未确认调用执行 lookup_result。返回确定的 ok/tool_error/denied ToolResult 时记录证据并继续；返回 None、抛出异常或返回错误类型时保持暂停，绝不自动调用 execute_with_id 重试。人工仍可通过 resume(ToolResult(...)) 提交核实结果，事件注明 lookup/operator 来源。

执行回调必须让外部系统真正支持操作键去重。单独在本地记“开始执行”不能保证外部副作用与本地回执一致。新调用即使参数相同也会生成新 ID；本功能不推断两个模型请求是否代表相同业务意图。

## 可运行示例

`cardinal_agent/examples/durable_reports.py` 实现 ReportStore：

```python
from pathlib import Path
from cardinal_agent.examples.durable_reports import ReportStore
from cardinal_agent.harness import create_session
from cardinal_agent.types import AgentConfig

reports = ReportStore('reports.db')
session = create_session(model, [reports.spec()],
                         AgentConfig(checkpoint_path=Path('.cardinal/report-run.json')))
result = session.send('Create a report titled Weekly with body Done')
```

SQLite 报告表的 operation_id 为主键；报告就是副作用，插入和去重处于同一数据库事务。相同 ID/相同参数返回已有报告，相同 ID/不同参数拒绝。lookup 查询已提交记录，查不到返回 None。它适合演示本地事务边界，不代表任意发邮件或写文件也具有同样保证。

测试见 test_recoverable_tools.py 与真实 SIGKILL 事务场景，覆盖去重、参数冲突、查询失败、无结果暂停和不重复执行。read_only、revision、是否提供恢复回调也加入恢复策略比较。旧 checkpoint 缺少新合同字段时拒绝恢复，不自动迁移。
