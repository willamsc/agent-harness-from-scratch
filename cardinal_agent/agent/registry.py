"""Tool registration, side-effect-free validation, and contained execution."""

from copy import deepcopy

from jsonschema import Draft202012Validator

from cardinal_agent.types import ToolResult, ToolSpec


class ToolRegistry:
    """Keep tool lookup separate from executing a validated call."""

    def __init__(self, tools: list[ToolSpec]):
        if len({tool.name for tool in tools}) != len(tools):
            raise ValueError('Duplicate tool names are not allowed.')
        for tool in tools:
            if (tool.execute_with_id is None) != (tool.lookup_result is None):
                raise ValueError(f'{tool.name}: execute_with_id and lookup_result must be supplied together.')
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

    def execute(self, name: str, args: dict, *, operation_id: str | None = None) -> ToolResult:
        error = self.validate(name, args)
        if error is not None:
            return error
        try:
            spec = self.tools[name]
            if operation_id is not None and spec.execute_with_id is not None:
                value = spec.execute_with_id(deepcopy(args), operation_id)
            else:
                value = spec.fn(**args)
            return ToolResult("ok", str(value))
        except Exception as exc:
            return ToolResult("tool_error", str(exc) or type(exc).__name__)
