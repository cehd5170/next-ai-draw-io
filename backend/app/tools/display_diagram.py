"""
display_diagram tool — create a new diagram from scratch.

The LLM passes bare mxCell XML (no wrapper tags).  This module validates
the fragment, optionally strips stray wrappers with a warning, wraps it
into a full mxGraphModel document, and returns the result.

If the XML is detected as truncated (incomplete), the tool signals
``is_truncated=True`` so the orchestrator can prompt the LLM to continue
via ``append_diagram``.
"""
from __future__ import annotations

from app.tools.registry import Tool, ToolContext, ToolResult, register_tool
from app.tools._xml_utils import (
    add_mxgraph_wrapper,
    has_mxcell,
    has_reserved_ids,
    has_wrapper_tags,
    is_mxcell_xml_complete,
    strip_wrapper_tags,
)
from app.prompts.constants import TOOL_SCHEMAS
from app.tools.layout_policy import DEFAULT_DISPLAY_DIAGRAM_LAYOUT, LAYOUT_TO_GV_ENGINE


# ── Execution ─────────────────────────────────────────────────────────────────

async def execute_display_diagram(params: dict, context: ToolContext) -> ToolResult:
    """
    Display a NEW diagram.

    Accepts mxCell XML only (no wrappers).  Validates, optionally strips
    stray wrappers, checks completeness, and wraps for draw.io.
    """
    xml: str = params.get("xml", "")

    # 1. Non-empty check.
    if not xml or not xml.strip():
        return ToolResult(
            success=False,
            content="Parameter 'xml' must be a non-empty string.",
        )

    xml = xml.strip()

    # 2. Wrapper-tag check — strip with warning rather than hard-reject so
    #    that the diagram is still displayed even when the LLM disobeys the
    #    schema.
    warnings: list[str] = []
    if has_wrapper_tags(xml):
        warnings.append(
            "WARNING: xml contained wrapper tags (<mxGraphModel>, <mxfile>, or <root>). "
            "They were stripped automatically.  Send ONLY mxCell elements next time."
        )
        xml = strip_wrapper_tags(xml)
        if not xml.strip():
            return ToolResult(
                success=False,
                content=(
                    "After stripping wrapper tags, no mxCell content remained. "
                    "Please provide only mxCell elements."
                ),
            )

    # 3. Reserved-ID check (id="0" / id="1" are always added by the wrapper).
    if has_reserved_ids(xml):
        return ToolResult(
            success=False,
            content=(
                "xml must NOT include root cells with id=\"0\" or id=\"1\". "
                "Those cells are added automatically — start your IDs from \"2\"."
            ),
        )

    # 4. At least one mxCell element required.
    if not has_mxcell(xml):
        return ToolResult(
            success=False,
            content=(
                "xml must contain at least one <mxCell element. "
                "Provide valid draw.io mxCell XML."
            ),
        )

    # 5. Completeness check — detect truncation before wrapping.
    complete = is_mxcell_xml_complete(xml)
    if not complete:
        # Build a hint showing the last few lines so the LLM knows where
        # to continue from.
        lines = xml.rstrip().splitlines()
        tail = "\n".join(lines[-3:]) if len(lines) > 3 else xml.rstrip()
        message_parts = warnings + [
            f"Diagram XML appears to be truncated (incomplete) — "
            f"{len(lines)} lines / {len(xml)} chars saved so far.  "
            f"Last lines saved:\n{tail}\n\n"
            f"Call append_diagram to continue from EXACTLY where this stopped."
        ]
        return ToolResult(
            success=True,
            content="\n".join(message_parts),
            xml=xml,          # raw partial fragment stored in context
            is_truncated=True,
        )

    # 6. Wrap into full mxGraphModel.
    full_xml = add_mxgraph_wrapper(xml)

    # 7. Apply server-side auto-layout via Graphviz.
    layout = params.get("layout", DEFAULT_DISPLAY_DIAGRAM_LAYOUT)
    if layout != "none":
        from app.tools.graphviz_layout import apply_graphviz_layout

        engine = LAYOUT_TO_GV_ENGINE.get(layout, "dot")
        full_xml = apply_graphviz_layout(full_xml, engine=engine)

    message_parts = warnings + [
        "Diagram created successfully. Do not edit or refine — wait for user feedback."
    ]
    return ToolResult(
        success=True,
        content="\n".join(message_parts),
        xml=full_xml,
        is_truncated=False,
    )


# ── Registration ──────────────────────────────────────────────────────────────

_schema = TOOL_SCHEMAS["display_diagram"]

register_tool(
    Tool(
        name=_schema["name"],
        description=_schema["description"],
        parameters=_schema["parameters"],
        execute=execute_display_diagram,
    )
)
