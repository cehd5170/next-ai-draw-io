"""
append_diagram tool — continue diagram generation after a truncation.

When display_diagram detects that the LLM's output was cut short
(``is_truncated=True``), the orchestrator asks the LLM to call
append_diagram with the continuation fragment.  This tool:

1. Validates that the fragment looks like a genuine continuation (no wrapper
   tags — if wrappers are present the LLM is restarting, not continuing).
2. Concatenates the fragment onto the partial XML stored in context.
3. Checks whether the combined XML is now complete.
4. If complete, wraps it and returns the full diagram.
5. If still incomplete, stores the combined partial and returns
   ``is_truncated=True`` again.
"""
from __future__ import annotations

from app.tools.registry import Tool, ToolContext, ToolResult, register_tool
from app.tools._xml_utils import (
    add_mxgraph_wrapper,
    has_mxcell,
    has_wrapper_tags,
    is_mxcell_xml_complete,
)
from app.prompts.constants import TOOL_SCHEMAS
from app.tools.layout_policy import normalize_wrapped_xml_for_auto_layout


# ── Execution ─────────────────────────────────────────────────────────────────

async def execute_append_diagram(params: dict, context: ToolContext) -> ToolResult:
    """
    Append a continuation XML fragment to a truncated diagram in progress.
    """
    fragment: str = params.get("xml", "")

    # 1. Non-empty check.
    if not fragment or not fragment.strip():
        return ToolResult(
            success=False,
            content="Parameter 'xml' must be a non-empty continuation fragment.",
        )

    fragment = fragment.strip()

    # 2. Reject wrapper tags — if the LLM included them it is starting fresh
    #    (use display_diagram) rather than continuing.
    if has_wrapper_tags(fragment):
        return ToolResult(
            success=False,
            content=(
                "The continuation fragment contains wrapper tags "
                "(<mxGraphModel>, <mxfile>, or <root>).  "
                "append_diagram only accepts bare mxCell elements.  "
                "If you are starting a new diagram, call display_diagram instead."
            ),
        )

    # 3. Retrieve the partial XML accumulated so far.
    partial: str = context.current_xml or ""

    # 4. Concatenate.
    combined = (partial.rstrip() + "\n" + fragment).strip()

    # 5. Completeness check.
    complete = is_mxcell_xml_complete(combined)

    if complete:
        # Validate that we actually have at least one mxCell.
        if not has_mxcell(combined):
            return ToolResult(
                success=False,
                content=(
                    "Combined XML appears complete but contains no <mxCell elements.  "
                    "Ensure the fragment is valid mxCell XML."
                ),
            )

        layout = context.display_layout
        full_xml = add_mxgraph_wrapper(combined)
        full_xml = normalize_wrapped_xml_for_auto_layout(full_xml, layout)
        return ToolResult(
            success=True,
            content="Diagram completed and displayed successfully.",
            xml=full_xml,
            is_truncated=False,
            layout=layout,
        )

    # 6. Still incomplete — signal for another append_diagram call.
    return ToolResult(
        success=True,
        content=(
            "Continuation received; diagram XML is still incomplete.  "
            "Call append_diagram again with the next fragment."
        ),
        xml=combined,   # raw partial stored in context for the next call
        is_truncated=True,
        layout=context.display_layout,
    )


# ── Registration ──────────────────────────────────────────────────────────────

_schema = TOOL_SCHEMAS["append_diagram"]

register_tool(
    Tool(
        name=_schema["name"],
        description=_schema["description"],
        parameters=_schema["parameters"],
        execute=execute_append_diagram,
    )
)
