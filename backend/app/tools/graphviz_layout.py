"""
Server-side auto-layout using Graphviz.

Parses mxGraphModel XML, builds a Graphviz directed graph, computes positions
with the ``dot`` (hierarchical) engine, and writes the coordinates back into
mxGeometry attributes.  Containers/groups are handled via Graphviz subgraphs.
"""
from __future__ import annotations

import logging

from lxml import etree

from app.tools._xml_utils import parse_diagram_xml, serialise_diagram

logger = logging.getLogger(__name__)

# Extra padding around the whole diagram (px)
_MARGIN_X = 40
_MARGIN_Y = 40

# Default node dimensions (px) when mxGeometry is missing
_DEFAULT_W = 120
_DEFAULT_H = 60

# Container layout constants
_CONTAINER_PADDING = 30
_CONTAINER_TITLE_HEIGHT = 30

# Graphviz graph-level tuning
_GV_NODESEP = "0.8"
_GV_RANKSEP = "1.2"


def apply_graphviz_layout(xml: str, engine: str = "dot") -> str:
    """
    Re-layout a full mxGraphModel XML string using Graphviz.

    Args:
        xml: Complete mxGraphModel XML (with wrapper).
        engine: Graphviz layout engine (dot, neato, fdp, etc.).

    Returns:
        The XML string with updated mxGeometry positions.
        On any error, returns the original XML unchanged.
    """
    try:
        import graphviz as gv
    except ImportError:
        logger.warning("graphviz package not installed; skipping layout.")
        return xml

    try:
        tree = parse_diagram_xml(xml)
    except etree.XMLSyntaxError:
        logger.warning("Invalid XML; skipping graphviz layout.")
        return xml

    cells = tree.findall(".//mxCell")
    if not cells:
        return xml

    # ── 1. Classify cells ────────────────────────────────────────────────
    vertices: dict[str, etree._Element] = {}
    edges: list[etree._Element] = []
    containers: set[str] = set()
    cell_parent: dict[str, str] = {}

    for cell in cells:
        cid = cell.get("id", "")
        if cid in ("0", "1"):
            continue
        parent = cell.get("parent", "1")
        cell_parent[cid] = parent

        if cell.get("edge") == "1":
            edges.append(cell)
        else:
            vertices[cid] = cell

    # Identify containers: any vertex that is a parent of another vertex
    for cid, pid in cell_parent.items():
        if pid not in ("0", "1") and pid in vertices and cid in vertices:
            containers.add(pid)

    # ── 2. Read node dimensions from mxGeometry ──────────────────────────
    node_sizes: dict[str, tuple[float, float]] = {}
    for cid, cell in vertices.items():
        geo = cell.find("mxGeometry")
        w = float(geo.get("width", str(_DEFAULT_W))) if geo is not None else _DEFAULT_W
        h = float(geo.get("height", str(_DEFAULT_H))) if geo is not None else _DEFAULT_H
        node_sizes[cid] = (w, h)

    # ── 3. Build Graphviz graph ──────────────────────────────────────────
    g = gv.Digraph(engine=engine)
    g.attr(rankdir="TB", nodesep=_GV_NODESEP, ranksep=_GV_RANKSEP, margin="0.5")

    # Build nested subgraph hierarchy for containers.
    # A container may itself be inside another container.
    subgraphs: dict[str, gv.Digraph] = {}

    def _get_target_graph(parent_id: str) -> gv.Digraph:
        """Return the subgraph for *parent_id*, or the root graph."""
        if parent_id in subgraphs:
            return subgraphs[parent_id]
        return g

    # Sort containers so that parents are created before children.
    def _container_depth(cid: str) -> int:
        depth = 0
        cur = cid
        while cell_parent.get(cur, "1") not in ("0", "1"):
            cur = cell_parent[cur]
            depth += 1
        return depth

    for container_id in sorted(containers, key=_container_depth):
        label = vertices[container_id].get("value", "") or ""
        parent_id = cell_parent.get(container_id, "1")
        parent_graph = _get_target_graph(parent_id)
        sg = gv.Digraph(name=f"cluster_{container_id}")
        sg.attr(label=label, style="rounded", margin="20")
        # Add hidden anchor node for edges targeting the container
        sg.node(container_id, label="", shape="point", width="0", height="0")
        parent_graph.subgraph(sg)
        subgraphs[container_id] = sg

    # Add leaf nodes
    for cid, cell in vertices.items():
        if cid in containers:
            continue

        w, h = node_sizes[cid]
        w_inch = str(round(w / 72, 2))
        h_inch = str(round(h / 72, 2))
        label = cell.get("value", "") or ""
        if len(label) > 30:
            label = label[:27] + "..."

        parent = cell_parent.get(cid, "1")
        target_graph = _get_target_graph(parent)

        target_graph.node(
            cid,
            label=label,
            shape="box",
            fixedsize="true",
            width=w_inch,
            height=h_inch,
        )

    # Add edges
    for edge in edges:
        src = edge.get("source", "")
        tgt = edge.get("target", "")
        if src and tgt and (src in vertices) and (tgt in vertices):
            g.edge(src, tgt)

    # ── 4. Run layout ────────────────────────────────────────────────────
    try:
        rendered = g.pipe(format="plain").decode("utf-8")
    except Exception as e:
        logger.warning("Graphviz layout failed: %s", e)
        return xml

    # ── 5. Parse graphviz plain output ───────────────────────────────────
    # Format: "node <name> <x> <y> <w> <h> <label> ..."
    # Coordinates are in inches from bottom-left; we need to flip Y.
    gv_positions: dict[str, tuple[float, float]] = {}
    graph_height = 0.0

    for line in rendered.splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "graph" and len(parts) >= 4:
            graph_height = float(parts[3])
        elif parts[0] == "node" and len(parts) >= 4:
            node_id = parts[1]
            cx = float(parts[2])
            cy = float(parts[3])
            gv_positions[node_id] = (cx, cy)

    if not gv_positions:
        logger.warning("No positions extracted from graphviz output.")
        return xml

    # ── 6. Write positions back to XML ───────────────────────────────────
    for cid, cell in vertices.items():
        if cid not in gv_positions or cid in containers:
            continue

        cx_inch, cy_inch = gv_positions[cid]
        w, h = node_sizes[cid]

        px = cx_inch * 72 - w / 2 + _MARGIN_X
        py = (graph_height - cy_inch) * 72 - h / 2 + _MARGIN_Y

        geo = cell.find("mxGeometry")
        if geo is None:
            geo = etree.SubElement(cell, "mxGeometry")
            geo.set("as", "geometry")
        geo.set("x", str(round(px)))
        geo.set("y", str(round(py)))

    # ── 7. Reposition containers to bound their children ─────────────────
    # Process deepest containers first so inner containers are sized before
    # their parent computes its bounding box.
    for container_id in sorted(containers, key=_container_depth, reverse=True):
        children = [
            cid for cid, pid in cell_parent.items()
            if pid == container_id and cid in vertices
        ]
        if not children:
            continue

        # Find bounding box of children (in absolute coords)
        min_x = min_y = float("inf")
        max_x = max_y = float("-inf")
        for child_id in children:
            c_cell = vertices[child_id]
            c_geo = c_cell.find("mxGeometry")
            if c_geo is None:
                continue
            cx = float(c_geo.get("x", "0"))
            cy = float(c_geo.get("y", "0"))
            cw = float(c_geo.get("width", "0")) if child_id in containers else node_sizes[child_id][0]
            ch = float(c_geo.get("height", "0")) if child_id in containers else node_sizes[child_id][1]
            min_x = min(min_x, cx)
            min_y = min(min_y, cy)
            max_x = max(max_x, cx + cw)
            max_y = max(max_y, cy + ch)

        if min_x == float("inf"):
            continue

        container_x = min_x - _CONTAINER_PADDING
        container_y = min_y - _CONTAINER_PADDING - _CONTAINER_TITLE_HEIGHT
        container_w = (max_x - min_x) + 2 * _CONTAINER_PADDING
        container_h = (max_y - min_y) + 2 * _CONTAINER_PADDING + _CONTAINER_TITLE_HEIGHT

        container_cell = vertices[container_id]
        geo = container_cell.find("mxGeometry")
        if geo is None:
            geo = etree.SubElement(container_cell, "mxGeometry")
            geo.set("as", "geometry")
        geo.set("x", str(round(container_x)))
        geo.set("y", str(round(container_y)))
        geo.set("width", str(round(container_w)))
        geo.set("height", str(round(container_h)))

        # Convert children from absolute to relative coordinates
        for child_id in children:
            c_geo = vertices[child_id].find("mxGeometry")
            if c_geo is None:
                continue
            c_geo.set("x", str(round(float(c_geo.get("x", "0")) - container_x)))
            c_geo.set("y", str(round(float(c_geo.get("y", "0")) - container_y)))

    # ── 8. Clear edge waypoints & fixed connection-point styles ────────
    # After repositioning nodes, old waypoints and entryX/exitX styles
    # become invalid.  Removing them lets draw.io auto-route edges.
    import re

    _EDGE_STYLE_KEYS = re.compile(
        r"(exitX|exitY|exitDx|exitDy|exitPerimeter|"
        r"entryX|entryY|entryDx|entryDy|entryPerimeter)=[^;]*;?"
    )

    for edge in edges:
        # Remove waypoints (mxPoint / Array inside mxGeometry)
        geo = edge.find("mxGeometry")
        if geo is not None:
            for child in list(geo):
                tag = child.tag if isinstance(child.tag, str) else ""
                if tag in ("mxPoint", "Array"):
                    geo.remove(child)

        # Strip fixed connection-point style properties
        style = edge.get("style", "")
        if style:
            cleaned = _EDGE_STYLE_KEYS.sub("", style)
            # Clean up leftover semicolons
            cleaned = re.sub(r";{2,}", ";", cleaned).strip(";")
            if cleaned != style:
                edge.set("style", cleaned)

    # ── 9. Ensure no top-level element has negative coordinates ─────────
    top_level_cells = [
        cell for cid, cell in vertices.items()
        if cell_parent.get(cid, "1") in ("0", "1")
    ]
    if top_level_cells:
        min_top_x = min_top_y = float("inf")
        for cell in top_level_cells:
            geo = cell.find("mxGeometry")
            if geo is not None:
                min_top_x = min(min_top_x, float(geo.get("x", "0")))
                min_top_y = min(min_top_y, float(geo.get("y", "0")))

        shift_x = _MARGIN_X - min_top_x if min_top_x < _MARGIN_X else 0
        shift_y = _MARGIN_Y - min_top_y if min_top_y < _MARGIN_Y else 0

        if shift_x or shift_y:
            for cell in top_level_cells:
                geo = cell.find("mxGeometry")
                if geo is not None:
                    geo.set("x", str(round(float(geo.get("x", "0")) + shift_x)))
                    geo.set("y", str(round(float(geo.get("y", "0")) + shift_y)))

    return serialise_diagram(tree)
