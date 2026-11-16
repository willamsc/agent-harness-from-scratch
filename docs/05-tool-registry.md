# 实现笔记 5：工具注册表（tool_registry）

## 1. 要做什么

本题是 Agent 运行时 的第一步：把多个 Python 工具函数注册到统一的入口，向模型展示工具说明，独立验证调用，再执行并统一封装结果。不调用 LLM，也不在本题实现工具调用文本协议、Agent 循环或审批功能。

输入为课程 ToolSpec 列表。每个工具带 name、description、parameters（JSON Schema）、fn 和 read_only。返回对象必须提供 schemas、validate、execute，保持适配接口不变。

## 2. 已确认的方案

- 用字典按名称保存工具，按输入顺序注册；Python 字典保持插入顺序。
- 使用题目指定的 Draft202012Validator，每个工具创建一个验证器，复用参数规则。
- validate 只检查，不执行工具，方便后续先验证、再审批、最后执行。
- execute 先复用 validate，合法后调用一次 fn(**args)。
- 普通验证或执行异常转成 ToolResult，一次失败不破坏后续调用。

课程使用正常且唯一的工具名与合法 Schema；当前不额外设计重复注册策略，字典重复键将保留最后的工具定义。read_only 保存于工具信息，但本题不执行审批策略。

## 3. 三个方法

### schemas()

按注册顺序返回列表，每项恰好包含 name、description、parameters。不包含 fn 或 read_only。返回的 parameters 使用深拷贝，避免调用方修改导出的规则时污染验证器。构造验证器时也拷贝 Schema。

### validate(name, args)

先按名称精确查找，不改大小写或去空格。工具不存在返回 unknown_tool；参数不符合 JSON Schema 返回 invalid_args 和错误说明；通过时返回 None。这个过程不能调用 fn，也不应修改传入参数。

参数验证检查 required、type、enum、上下界、additionalProperties 等 Schema 约束，不把字符串数字自动转成数值，也不自动填入默认值。

### execute(name, args)

调用 validate，若有错误直接返回；否则调用 fn(**args)，成功返回 ToolResult("ok", str(value))。即使返回值是 None、列表或字典，也使用 Python 的 str，不强制改成 JSON。

函数抛出普通 Exception 或返回值转换失败时，返回 tool_error，content 包含异常文本；空异常文本使用异常类名，保证错误有说明。这里捕获 Exception，不吞掉 KeyboardInterrupt、SystemExit 等进程控制信号。

| 情况 | 状态 | 工具执行次数 |
| --- | --- | --- |
| 名称不存在 | unknown_tool | 0 |
| 参数不合法 | invalid_args | 0 |
| 工具抛异常 | tool_error | 1 |
| 成功 | ok | 1 |

## 4. 例子

工具 add(a, b) 的 Schema 要求两个数字：

```python
registry.validate("add", {"a": 2, "b": 3})  # None；尚未计算
registry.execute("add", {"a": 2, "b": 3})   # ToolResult("ok", "5")
registry.execute("add", {"a": 2})           # invalid_args；不执行
registry.execute("missing", {})             # unknown_tool
```

后续确认模式可以在 validate 通过后询问用户，而不是先执行再询问。execute 内仍会验证，确保直接调用也有保护。注册表本身不能替代业务授权或 sandbox。

## 5. 完整实现

实现位置：cardinal_agent/agent/registry.py。

```python
"""Tool registration, side-effect-free validation, and contained execution."""

from copy import deepcopy

from jsonschema import Draft202012Validator

from cardinal_agent.types import ToolResult, ToolSpec


class ToolRegistry:
    """Keep tool lookup separate from executing a validated call."""

    def __init__(self, tools: list[ToolSpec]):
        self.tools = {tool.name: tool for tool in tools}
        self._validators = {
            name: Draft202012Validator(deepcopy(tool.parameters))
            for name, tool in self.tools.items()
        }

    def schemas(self) -> list[dict]:
        # Do not expose mutable schemas to callers or include Python functions.
        return [
            {"name": tool.name, "description": tool.description,
             "parameters": deepcopy(self._validators[tool.name].schema)}
            for tool in self.tools.values()
        ]

    def validate(self, name: str, args: dict) -> ToolResult | None:
        try:
            if name not in self.tools:
                return ToolResult("unknown_tool", f"Unknown tool: {name}")
            self._validators[name].validate(args)
        except Exception as exc:
            return ToolResult("invalid_args", str(exc) or type(exc).__name__)
        return None

    def execute(self, name: str, args: dict) -> ToolResult:
        error = self.validate(name, args)
        if error is not None:
            return error
        try:
            value = self.tools[name].fn(**args)
            return ToolResult("ok", str(value))
        except Exception as exc:
            return ToolResult("tool_error", str(exc) or type(exc).__name__)

```

Adapter 接入：

```python
def run_tool_registry(tools: list[ToolSpec]):
    from cardinal_agent.agent.registry import ToolRegistry
    return ToolRegistry(tools)
```

## 6. 测试数据与结果

本题无需真实模型测试，也没有新增补充测试；课程自带测试已经覆盖注册顺序、Schema 输出、各类返回值、验证不执行、缺参数、错误类型、额外参数、未知工具、工具异常以及失败后恢复。

本次执行本题测试并回归 业务流水线 与 local_tests：

```bash
.venv/bin/python -m pytest tests/test_tool_registry.py tests/test_priority.py tests/test_daily_digest.py tests/test_bm25.py tests/test_email_qa.py local_tests -o addopts= -m 'not live' -q --junitxml=<本次记录目录>/junit.xml
```

本题基准测试 **44 项通过**；合计 **149 项通过**，6 个 live 测试未执行，pytest 报告耗时 5.79 秒。模型调用 0 次，API 费用 0。

完整记录：[本次评测目录](evaluations/20261116-094526-tool-registry/)，包括 [原始输出](evaluations/20261116-094526-tool-registry/output.log)、metadata.json、metrics.json、junit.xml、实现差异及新增模块快照。metadata 的 base_commit 对应测试前已提交版本，当前实现由差异、快照和 SHA-256 标识，而不是假称已在该 base_commit 内。

没有性能对照基线，不能声称提高了多少速度或任务成功率。当前可报告的是验证规则与异常隔离行为在公开测试中通过，不能把测试通过率直接当成真实模型调用的成功率。

## 7. 手写参考与局限

先写空注册表及 schemas，再写 validate，最后写 execute；用一个 add 工具和一个主动抛异常的工具验证流程即可。注意合法验证返回 None，不要误判；成功内容必须是 str(return_value)，不能直接把对象放入 content。

本题只验证参数结构，不判断模型选择的工具是否符合用户意图。工具自身可能有副作用、改变传入的嵌套对象或执行很久，注册表不提供事务回滚、深拷贝执行参数或超时机制。工具函数的线程安全由工具实现负责。完整 Agent 后续会增加协议、预算、审批、终端隔离与拒绝规则。
