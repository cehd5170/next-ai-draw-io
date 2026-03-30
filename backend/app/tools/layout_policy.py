from __future__ import annotations

from typing import Any
import logging

from app.tools._xml_utils import has_explicit_vertex_positions

logger = logging.getLogger(__name__)

DEFAULT_DISPLAY_DIAGRAM_LAYOUT = "mxHierarchicalLayout"

# Map draw.io layout names to Graphviz engines.
# ``SUPPORTED_AUTO_LAYOUTS`` is derived from this mapping plus ``"none"``.
LAYOUT_TO_GV_ENGINE: dict[str, str] = {
    "mxHierarchicalLayout": "dot",
    "mxCompactTreeLayout": "dot",
    "mxFastOrganicLayout": "neato",
    "mxCircleLayout": "circo",
    "mxRadialTreeLayout": "twopi",
}

SUPPORTED_AUTO_LAYOUTS: set[str] = {*LAYOUT_TO_GV_ENGINE, "none"}


def apply_display_diagram_layout_defaults(
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Ensure ``display_diagram`` always carries a layout hint."""
    if tool_name != "display_diagram":
        return arguments

    normalized = dict(arguments)
    layout = normalized.get("layout")

    if isinstance(layout, str):
        layout = layout.strip()
        if layout in SUPPORTED_AUTO_LAYOUTS:
            normalized["layout"] = layout
            return normalized

    xml = normalized.get("xml")
    if isinstance(xml, str) and has_explicit_vertex_positions(xml):
        normalized["layout"] = "none"
        return normalized

    normalized["layout"] = DEFAULT_DISPLAY_DIAGRAM_LAYOUT
    return normalized
