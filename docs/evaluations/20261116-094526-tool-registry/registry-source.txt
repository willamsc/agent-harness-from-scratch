"""Tool registration, side-effect-free validation, and contained execution."""

from copy import deepcopy

from jsonschema import Draft202012Validator

from cs329z_hw1.types import ToolResult, ToolSpec


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
