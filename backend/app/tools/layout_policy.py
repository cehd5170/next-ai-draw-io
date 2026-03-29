from __future__ import annotations

from typing import Any
import logging

from lxml import etree

from app.tools._xml_utils import parse_diagram_xml, serialise_diagram

logger = logging.getLogger(__name__)

DEFAULT_DISPLAY_DIAGRAM_LAYOUT = "mxHierarchicalLayout"
SUPPORTED_AUTO_LAYOUTS = {
    "none",
    "mxHierarchicalLayout",
    "mxFastOrganicLayout",
    "mxCircleLayout",
    "mxCompactTreeLayout",
    "mxRadialTreeLayout",
}


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

    normalized["layout"] = DEFAULT_DISPLAY_DIAGRAM_LAYOUT
    return normalized


def normalize_wrapped_xml_for_auto_layout(xml: str, layout: str | None) -> str:
    """Remove fixed edge routing hints so draw.io can reroute after layout."""
    if layout not in SUPPORTED_AUTO_LAYOUTS or layout == "none":
        return xml

    try:
        tree = parse_diagram_xml(xml)
    except etree.XMLSyntaxError:
        logger.warning("Skipping auto-layout normalization for invalid wrapped XML.")
        return xml

    edge_defaults = {
        "edgeStyle": "orthogonalEdgeStyle",
        "rounded": "0",
        "orthogonalLoop": "1",
        "jettySize": "auto",
        "html": "1",
    }
    drop_style_keys = {
        "curved",
        "elbow",
        "entryX",
        "entryY",
        "entryDx",
        "entryDy",
        "entryPerimeter",
        "exitX",
        "exitY",
        "exitDx",
        "exitDy",
        "exitPerimeter",
        "perimeterSpacing",
        "sourcePerimeterSpacing",
        "targetPerimeterSpacing",
    }

    for edge in tree.findall(".//mxCell[@edge='1']"):
        style_items = [
            item.strip()
            for item in str(edge.get("style") or "").split(";")
            if item.strip()
        ]
        style_map: dict[str, str] = {}
        flag_items: list[str] = []

        for item in style_items:
            if "=" in item:
                key, value = item.split("=", 1)
                if key in drop_style_keys:
                    continue
                style_map[key] = value
            elif item not in flag_items:
                flag_items.append(item)

        style_map.update(edge_defaults)
        ordered_items = [f"{key}={value}" for key, value in style_map.items()]
        if flag_items:
            ordered_items.extend(flag_items)
        edge.set("style", ";".join(ordered_items) + ";")

        geometry = edge.find("./mxGeometry")
        if geometry is None:
            continue

        for child in list(geometry):
            if child.tag == "Array":
                geometry.remove(child)
                continue
            if child.tag == "mxPoint":
                geometry.remove(child)

    return serialise_diagram(tree)
