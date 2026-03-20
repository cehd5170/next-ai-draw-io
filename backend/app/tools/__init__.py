"""
app.tools — diagram tool registry for AI function calling.

Importing this package registers all four diagram tools (display_diagram,
edit_diagram, append_diagram, get_shape_library) into TOOL_REGISTRY as a
side-effect of the individual module imports below.

Public API
----------
TOOL_REGISTRY       dict[str, Tool]     All registered tools keyed by name.
get_tool_definitions() -> list[dict]    Tool specs in OpenAI/litellm format.
dispatch_tool(name, arguments, context) Execute a tool by name.
ToolContext                             Context dataclass passed to tools.
ToolResult                              Result dataclass returned by tools.
"""

# Registry core — must be imported first so that register_tool() is available
# before the individual tool modules execute their module-level calls.
from app.tools.registry import (  # noqa: F401
    TOOL_REGISTRY,
    ToolContext,
    ToolResult,
    Tool,
    register_tool,
    get_tool_definitions,
    dispatch_tool,
)

# Tool modules — each registers itself into TOOL_REGISTRY on import.
import app.tools.display_diagram  # noqa: F401
import app.tools.edit_diagram     # noqa: F401
import app.tools.append_diagram   # noqa: F401
import app.tools.shape_library    # noqa: F401

__all__ = [
    "TOOL_REGISTRY",
    "ToolContext",
    "ToolResult",
    "Tool",
    "register_tool",
    "get_tool_definitions",
    "dispatch_tool",
]
