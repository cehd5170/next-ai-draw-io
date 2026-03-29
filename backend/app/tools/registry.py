"""
Tool registry: dataclasses and registration helpers for diagram tools.
"""
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable


@dataclass
class ToolContext:
    """Context passed to every tool execution."""

    current_xml: str  # Current diagram XML on the canvas (may be empty string)
    shape_library_dir: str  # Absolute path to shape library markdown files
    settings: Any  # Settings instance
    display_layout: str | None = None  # Preferred auto-layout for current diagram


@dataclass
class ToolResult:
    """Result returned by every tool execution."""

    success: bool
    content: str  # Human/LLM-readable result (XML, error, docs, …)
    xml: str | None = None  # Updated diagram XML when the diagram changed
    is_truncated: bool = False  # True when display_diagram output was cut short
    layout: str | None = None  # Auto-layout chosen for display/append flows


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict  # JSON Schema object
    execute: Callable[[dict, ToolContext], Awaitable[ToolResult]]


# ── Global registry ────────────────────────────────────────────────────────────

TOOL_REGISTRY: dict[str, Tool] = {}


def register_tool(tool: Tool) -> None:
    """Add a tool to the global registry."""
    TOOL_REGISTRY[tool.name] = tool


def get_tool_definitions() -> list[dict]:
    """Return all registered tools in litellm / OpenAI function-calling format."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        }
        for tool in TOOL_REGISTRY.values()
    ]


async def dispatch_tool(name: str, arguments: dict, context: ToolContext) -> ToolResult:
    """Look up and execute a registered tool by name."""
    if name not in TOOL_REGISTRY:
        return ToolResult(
            success=False,
            content=f"Unknown tool: '{name}'. Available tools: {', '.join(TOOL_REGISTRY)}",
        )
    return await TOOL_REGISTRY[name].execute(arguments, context)
