"""
edit_diagram tool — apply targeted ID-based operations to the current diagram.

Supported operations
--------------------
update  Replace an existing mxCell (matched by id) with new_xml.
add     Insert a new mxCell; validates that the parent cell already exists.
delete  Remove a cell and cascade-delete its children and connected edges.

lxml.etree is used for all structural XML manipulation.
"""
from __future__ import annotations

from lxml import etree

from app.tools.registry import Tool, ToolContext, ToolResult, register_tool
from app.tools._xml_utils import (
    get_all_cell_ids,
    get_root_element,
    parse_diagram_xml,
    serialise_diagram,
)
from app.prompts.constants import TOOL_SCHEMAS


# ── Helpers ───────────────────────────────────────────────────────────────────

def _find_cell(root_el: etree._Element, cell_id: str) -> etree._Element | None:
    """Return the mxCell element with the given id, or None."""
    matches = root_el.findall(f".//mxCell[@id='{cell_id}']")
    return matches[0] if matches else None


def _parse_cell_fragment(new_xml: str) -> etree._Element:
    """
    Parse a single mxCell XML fragment.
    Raises ``etree.XMLSyntaxError`` when the fragment is not valid XML.
    """
    # Strip leading/trailing whitespace so single-element fragments parse cleanly.
    return etree.fromstring(new_xml.strip().encode())


def _parse_cell_fragments(new_xml: str) -> list[etree._Element]:
    """
    Parse one or more mxCell elements from *new_xml*.

    LLMs sometimes pack multiple sibling ``<mxCell>`` elements into a single
    ``new_xml`` value, which ``etree.fromstring`` rejects ("extra content at
    the end of the document").  This helper wraps the input in a temporary
    root, extracts all ``<mxCell>`` children, and returns them as a list.

    Raises ``etree.XMLSyntaxError`` when the fragment is not valid XML at all.
    """
    stripped = new_xml.strip()
    # Fast path: single element.
    try:
        el = etree.fromstring(stripped.encode())
        return [el]
    except etree.XMLSyntaxError:
        pass

    # Multiple siblings — wrap and extract.
    wrapper = etree.fromstring(f"<_tmp_>{stripped}</_tmp_>".encode())
    cells = list(wrapper)  # all direct children
    if not cells:
        raise etree.XMLSyntaxError("No elements found in new_xml", "", 0, 0, "")
    return cells


def _collect_descendant_ids(root_el: etree._Element, parent_id: str) -> list[str]:
    """
    Recursively collect the IDs of all mxCell elements whose parent chain
    leads to *parent_id*.  Only direct and transitive children are included;
    *parent_id* itself is excluded.
    """
    # Build a parent → [children] map for efficient traversal.
    children_map: dict[str, list[str]] = {}
    for cell in root_el.findall(".//mxCell"):
        pid = cell.get("parent")
        cid = cell.get("id")
        if pid and cid:
            children_map.setdefault(pid, []).append(cid)

    result: list[str] = []
    queue: list[str] = list(children_map.get(parent_id, []))
    while queue:
        cid = queue.pop()
        result.append(cid)
        queue.extend(children_map.get(cid, []))
    return result


def _collect_connected_edge_ids(root_el: etree._Element, cell_id: str) -> list[str]:
    """Return IDs of all mxCell edges that have source or target equal to cell_id."""
    ids: list[str] = []
    for cell in root_el.findall(".//mxCell"):
        if cell.get("source") == cell_id or cell.get("target") == cell_id:
            eid = cell.get("id")
            if eid:
                ids.append(eid)
    return ids


def _delete_cells_by_ids(root_el: etree._Element, ids_to_delete: set[str]) -> None:
    """Remove all mxCell elements whose id is in *ids_to_delete* from the tree."""
    for cell_id in ids_to_delete:
        for cell in root_el.findall(f".//mxCell[@id='{cell_id}']"):
            parent = cell.getparent()
            if parent is not None:
                parent.remove(cell)


# ── Operation handlers ────────────────────────────────────────────────────────

def _op_update(
    root_el: etree._Element,
    cell_id: str,
    new_xml: str | None,
    available_ids: list[str],
) -> str | None:
    """Replace the cell matching *cell_id* with *new_xml*.  Returns an error string or None."""
    if not new_xml:
        return "Operation 'update' requires 'new_xml'."

    target = _find_cell(root_el, cell_id)
    if target is None:
        return (
            f"Cell id='{cell_id}' not found. "
            f"Available IDs: {', '.join(available_ids) or '(none)'}."
        )

    try:
        elements = _parse_cell_fragments(new_xml)
    except etree.XMLSyntaxError as exc:
        return f"Invalid XML in 'new_xml' for update of id='{cell_id}': {exc}"

    # The first element replaces the target; any extras are appended
    # (LLMs sometimes bundle a shape + its edge in one new_xml value).
    replacement = elements[0]

    if replacement.tag != "mxCell":
        return f"'new_xml' must be an <mxCell> element, got <{replacement.tag}>."

    parent = target.getparent()
    if parent is None:
        return f"Cell id='{cell_id}' has no parent element in the document."

    idx = list(parent).index(target)
    parent.remove(target)
    parent.insert(idx, replacement)

    for extra in elements[1:]:
        if extra.tag == "mxCell":
            root_el.append(extra)

    return None


def _op_add(
    root_el: etree._Element,
    cell_id: str,
    new_xml: str | None,
    available_ids: list[str],
) -> str | None:
    """Insert *new_xml* as a new mxCell.  Returns an error string or None."""
    if not new_xml:
        return "Operation 'add' requires 'new_xml'."

    # Reject duplicate IDs.
    if _find_cell(root_el, cell_id) is not None:
        return (
            f"A cell with id='{cell_id}' already exists. "
            "Use a unique ID for 'add' operations."
        )

    try:
        elements = _parse_cell_fragments(new_xml)
    except etree.XMLSyntaxError as exc:
        return f"Invalid XML in 'new_xml' for add of id='{cell_id}': {exc}"

    first = elements[0]
    if first.tag != "mxCell":
        return f"'new_xml' must be an <mxCell> element, got <{first.tag}>."

    # Validate that the declared parent exists (skip reserved root cells).
    parent_id = first.get("parent")
    if parent_id and parent_id not in ("0", "1"):
        if _find_cell(root_el, parent_id) is None:
            return (
                f"Parent cell id='{parent_id}' not found. "
                f"Available IDs: {', '.join(available_ids) or '(none)'}."
            )

    # Append all elements (LLMs sometimes bundle multiple cells in one operation).
    for el in elements:
        if el.tag == "mxCell":
            root_el.append(el)
    return None


def _op_delete(
    root_el: etree._Element,
    cell_id: str,
    available_ids: list[str],
) -> str | None:
    """Remove *cell_id* and cascade-delete children and connected edges.  Returns an error string or None."""
    target = _find_cell(root_el, cell_id)
    if target is None:
        return (
            f"Cell id='{cell_id}' not found. "
            f"Available IDs: {', '.join(available_ids) or '(none)'}."
        )

    # Gather everything to remove before mutating the tree.
    descendant_ids = _collect_descendant_ids(root_el, cell_id)
    edge_ids = _collect_connected_edge_ids(root_el, cell_id)

    ids_to_delete: set[str] = {cell_id} | set(descendant_ids) | set(edge_ids)
    _delete_cells_by_ids(root_el, ids_to_delete)
    return None


# ── Main execution ────────────────────────────────────────────────────────────

async def execute_edit_diagram(params: dict, context: ToolContext) -> ToolResult:
    """
    Apply a list of update / add / delete operations to the current diagram.
    """
    operations: list[dict] = params.get("operations", [])

    # 1. Validate operations list.
    if not operations:
        return ToolResult(success=False, content="'operations' must be a non-empty list.")

    # 2. Parse current diagram XML.
    current_xml = context.current_xml
    if not current_xml or not current_xml.strip():
        return ToolResult(
            success=False,
            content=(
                "No diagram is currently displayed.  "
                "Use display_diagram to create one first."
            ),
        )

    try:
        tree = parse_diagram_xml(current_xml)
    except etree.XMLSyntaxError as exc:
        return ToolResult(
            success=False,
            content=f"Current diagram XML is not valid and cannot be edited: {exc}",
        )

    root_el = get_root_element(tree)
    if root_el is None:
        return ToolResult(
            success=False,
            content="Current diagram XML has no <root> element.",
        )

    # 3. Process each operation in order.
    errors: list[str] = []
    applied: list[str] = []

    for i, op in enumerate(operations):
        operation = op.get("operation", "")
        cell_id = op.get("cell_id", "")
        new_xml = op.get("new_xml")  # may be None for delete

        # Per-operation basic validation.
        if operation not in ("update", "add", "delete"):
            errors.append(
                f"Operation[{i}]: unknown operation '{operation}'. "
                "Must be 'update', 'add', or 'delete'."
            )
            continue

        if not cell_id:
            errors.append(f"Operation[{i}]: 'cell_id' must not be empty.")
            continue

        # Snapshot available IDs for error messages (refreshed each iteration
        # so additions/deletions in earlier steps are visible).
        available_ids = get_all_cell_ids(tree)

        error: str | None = None
        if operation == "update":
            error = _op_update(root_el, cell_id, new_xml, available_ids)
        elif operation == "add":
            error = _op_add(root_el, cell_id, new_xml, available_ids)
        elif operation == "delete":
            error = _op_delete(root_el, cell_id, available_ids)

        if error:
            errors.append(f"Operation[{i}] ({operation} id='{cell_id}'): {error}")
        else:
            applied.append(f"{operation} id='{cell_id}'")

    # 4. If any operations failed, report all errors without mutating the
    #    returned XML (we still return the partially-modified tree for the
    #    operations that succeeded — consistent with best-effort editing).
    updated_xml = serialise_diagram(tree)

    if errors:
        error_report = "\n".join(errors)
        if applied:
            success_report = "Applied: " + ", ".join(applied)
            content = f"Some operations failed:\n{error_report}\n\n{success_report}"
        else:
            content = f"All operations failed:\n{error_report}"
        return ToolResult(
            success=False,
            content=content,
            xml=updated_xml if applied else None,
        )

    return ToolResult(
        success=True,
        content="Applied: " + ", ".join(applied),
        xml=updated_xml,
    )


# ── Registration ──────────────────────────────────────────────────────────────

_schema = TOOL_SCHEMAS["edit_diagram"]

register_tool(
    Tool(
        name=_schema["name"],
        description=_schema["description"],
        parameters=_schema["parameters"],
        execute=execute_edit_diagram,
    )
)
