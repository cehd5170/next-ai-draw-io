"""
Internal XML helpers shared across diagram tools.

All public helpers operate on raw XML strings; lxml.etree is used for
structural manipulation so that attribute order, encoding, and namespace
handling are consistent.
"""
from __future__ import annotations

import re
from typing import Literal
from lxml import etree

# ── Wrapper tags that must never appear in raw mxCell XML passed by the LLM ──

_WRAPPER_TAGS: tuple[str, ...] = ("mxGraphModel", "mxfile", "root")
_WRAPPER_RE = re.compile(
    r"<(?:" + "|".join(_WRAPPER_TAGS) + r")[\s>]",
    re.IGNORECASE,
)

# Match the opening of any mxCell element (self-closing or not).
_MXCELL_OPEN_RE = re.compile(r"<mxCell\b", re.IGNORECASE)

# Matches all XML tags to track open/close depth in the completeness fallback.
# Groups: (1) leading slash for close tags, (2) tag name, (3) attrs, (4) trailing slash
_TAG_RE = re.compile(r"<(/?)(\w[\w:.-]*)([^>]*)(/?)>", re.DOTALL)


# ── Wrapper detection / stripping ──────────────────────────────────────────────

def has_wrapper_tags(xml: str) -> bool:
    """Return True if xml contains any mxGraphModel / mxfile / root tags."""
    return bool(_WRAPPER_RE.search(xml))


def strip_wrapper_tags(xml: str) -> str:
    """
    Remove <mxGraphModel>, <mxfile>, and <root> wrapper elements from *xml*,
    returning only the inner mxCell elements.

    This is a best-effort helper; structural parse errors are surfaced to the
    caller via the tool result rather than raised.
    """
    try:
        # Wrap in a temporary root so lxml can parse a fragment.
        wrapped = f"<_tmp_>{xml}</_tmp_>"
        root = etree.fromstring(wrapped.encode())
    except etree.XMLSyntaxError:
        # Fall back to a simple regex strip of the outer wrapper layers.
        for tag in _WRAPPER_TAGS:
            xml = re.sub(
                rf"<{tag}[^>]*>|</{tag}\s*>",
                "",
                xml,
                flags=re.IGNORECASE,
            )
        return xml.strip()

    # Collect all mxCell elements regardless of depth.
    cells = root.findall(".//mxCell")
    if not cells:
        # No mxCell children found – return content of deepest wrapper.
        for tag in _WRAPPER_TAGS:
            el = root.find(f".//{tag}")
            if el is not None:
                parts = [etree.tostring(c, encoding="unicode") for c in el]
                return "\n".join(parts).strip()
        return xml.strip()

    return "\n".join(etree.tostring(c, encoding="unicode") for c in cells)


# ── Reserved-ID detection ─────────────────────────────────────────────────────

_RESERVED_ID_RE = re.compile(r'\bid=["\']([01])["\']')


def has_reserved_ids(xml: str) -> bool:
    """Return True if xml contains id="0" or id="1" (reserved root cells)."""
    return bool(_RESERVED_ID_RE.search(xml))


# ── mxCell presence check ─────────────────────────────────────────────────────

def has_mxcell(xml: str) -> bool:
    """Return True if xml contains at least one <mxCell element."""
    return bool(_MXCELL_OPEN_RE.search(xml))


def has_explicit_vertex_positions(xml: str, *, min_vertices: int = 2) -> bool:
    """
    Return True when the fragment already contains positioned vertex geometry.

    This is used to detect diagrams where the model intentionally laid out
    nodes, in which case server-side auto-layout should usually stay off.
    """
    if not xml or not xml.strip():
        return False

    wrapped = f"<_tmp_>{xml}</_tmp_>"
    parser = etree.XMLParser(recover=True)
    try:
        root = etree.fromstring(wrapped.encode(), parser)
    except etree.XMLSyntaxError:
        return False

    positioned_vertices = 0
    for cell in root.findall(".//mxCell"):
        if cell.get("vertex") != "1":
            continue

        geo = cell.find("mxGeometry")
        if geo is None:
            continue

        if geo.get("x") is None or geo.get("y") is None:
            continue

        positioned_vertices += 1
        if positioned_vertices >= min_vertices:
            return True

    return False


# ── Completeness check ────────────────────────────────────────────────────────

def is_mxcell_xml_complete(xml: str) -> bool:
    """
    Heuristic: decide whether *xml* is a complete (non-truncated) fragment.

    Strategy:
    1. Try a strict lxml parse of ``<_tmp_>{xml}</_tmp_>``.  Success means
       the fragment is well-formed XML, therefore complete.
    2. On parse failure, apply two cheaper checks:
       a. If the last non-whitespace character is not ``>`` the fragment was
          cut off in the middle of a tag or attribute value.
       b. Walk all recognised tags and track open/close depth.  A positive
          final depth means at least one element was opened but not closed.
    """
    return classify_mxcell_xml_fragment(xml) == "complete"


def classify_mxcell_xml_fragment(xml: str) -> Literal["complete", "truncated", "malformed"]:
    """
    Classify a bare mxCell fragment as complete, truncated, or malformed.

    ``truncated`` means the fragment appears cut off and may be continued via
    ``append_diagram``. ``malformed`` means the fragment is not well-formed XML
    and should be regenerated instead of appended to.
    """
    if not xml or not xml.strip():
        return "truncated"

    # 1. Strict XML parse (fastest path for well-formed fragments).
    test = f"<_tmp_>{xml}</_tmp_>"
    try:
        etree.fromstring(test.encode())
        return "complete"
    except etree.XMLSyntaxError:
        pass

    stripped = xml.rstrip()
    if not stripped or stripped[-1] != ">":
        return "truncated"

    depth = 0
    min_depth = 0
    for m in _TAG_RE.finditer(xml):
        slash_start = m.group(1)  # present on </tag>
        slash_end = m.group(4)    # present on <tag/>
        if slash_start:
            depth -= 1
        elif not slash_end:
            depth += 1
        min_depth = min(min_depth, depth)
        # self-closing (<tag/>) contributes 0 net depth

    if depth > 0:
        return "truncated"

    if min_depth < 0 or depth < 0:
        return "malformed"

    return "malformed"


# ── mxGraphModel wrapper ───────────────────────────────────────────────────────

_MXGRAPH_WRAPPER = (
    '<mxGraphModel>\n'
    '  <root>\n'
    '    <mxCell id="0" />\n'
    '    <mxCell id="1" parent="0" />\n'
    '    {cells}\n'
    '  </root>\n'
    '</mxGraphModel>'
)


def add_mxgraph_wrapper(cells_xml: str) -> str:
    """Wrap bare mxCell XML in a full mxGraphModel document."""
    return _MXGRAPH_WRAPPER.format(cells=cells_xml.strip())


# ── Full-document parse / serialise ──────────────────────────────────────────

def parse_diagram_xml(xml: str) -> etree._Element:
    """
    Parse a full diagram XML string (must include mxGraphModel wrapper).
    Raises ``etree.XMLSyntaxError`` on malformed input.
    """
    return etree.fromstring(xml.encode())


def serialise_diagram(root: etree._Element) -> str:
    """Serialise an lxml element tree back to a UTF-8 XML string."""
    return etree.tostring(root, encoding="unicode", pretty_print=True)


def get_root_element(tree: etree._Element) -> etree._Element | None:
    """Return the <root> child of an mxGraphModel element, or None."""
    return tree.find(".//root")


def get_all_cell_ids(tree: etree._Element) -> list[str]:
    """Return all id attribute values found in mxCell elements."""
    return [
        el.get("id", "")
        for el in tree.findall(".//mxCell")
        if el.get("id") is not None
    ]


def recover_partial_xml(xml: str) -> str | None:
    """
    Best-effort recovery of complete mxCell elements from truncated XML.

    Uses lxml's recovery parser to extract all well-formed mxCell elements,
    discarding any trailing incomplete element.  Returns the recovered XML
    string, or None if no complete mxCell could be salvaged.
    """
    if not xml or not xml.strip():
        return None

    wrapped = f"<_tmp_>{xml}</_tmp_>"
    parser = etree.XMLParser(recover=True)
    try:
        root = etree.fromstring(wrapped.encode(), parser)
    except Exception:
        return None

    cells = root.findall(".//mxCell")
    if not cells:
        return None

    return "\n".join(etree.tostring(c, encoding="unicode") for c in cells)
