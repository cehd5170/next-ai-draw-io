"""
Diagram XML utility functions.

Ported from lib/utils.ts — helpers for mxCell/mxGraphModel XML validation,
wrapping, stripping, and completeness checking.
"""

from __future__ import annotations

import re

from lxml import etree

# ---------------------------------------------------------------------------
# Completeness check
# ---------------------------------------------------------------------------

# Matches a self-closing tag end (/>) or the explicit </mxCell> closing tag.
_SELF_CLOSE_STR = "/>"
_MXCELL_CLOSE_STR = "</mxCell>"

# Matches any sequence of closing XML tags (e.g. </root>, </mxGraphModel>)
# optionally separated by whitespace.  Used to verify that nothing but
# wrapper-close tags appears after the last complete mxCell.
_CLOSING_TAGS_SUFFIX_RE = re.compile(r"^(\s*</[^>]+>)*\s*$")


def is_mxcell_xml_complete(xml: str) -> bool:
    """
    Check if mxCell XML output is complete (not truncated).

    Complete XML ends with a self-closing tag (/>) or a closing </mxCell>
    tag, possibly followed only by whitespace or provider wrapper-closing
    tags.

    Returns True if the XML appears complete, False if truncated or empty.
    """
    trimmed = (xml or "").strip()
    if not trimmed:
        return False

    last_self_close = trimmed.rfind(_SELF_CLOSE_STR)
    last_mxcell_close = trimmed.rfind(_MXCELL_CLOSE_STR)

    last_valid_end = max(last_self_close, last_mxcell_close)
    if last_valid_end == -1:
        return False

    # Determine how many characters the ending token occupies.
    if last_mxcell_close > last_self_close:
        end_offset = len(_MXCELL_CLOSE_STR)
    else:
        end_offset = len(_SELF_CLOSE_STR)

    suffix = trimmed[last_valid_end + end_offset :]
    return bool(_CLOSING_TAGS_SUFFIX_RE.match(suffix))


# ---------------------------------------------------------------------------
# Wrapper
# ---------------------------------------------------------------------------

_MXGRAPH_TEMPLATE = (
    '<mxGraphModel>\n'
    '  <root>\n'
    '    <mxCell id="0" />\n'
    '    <mxCell id="1" parent="0" />\n'
    '    {cells}\n'
    '  </root>\n'
    '</mxGraphModel>'
)


def add_mxgraph_wrapper(mxcell_xml: str) -> str:
    """
    Wrap bare mxCell elements in a full mxGraphModel/root structure.

    Adds the two required root cells (id=0, id=1) automatically.
    """
    return _MXGRAPH_TEMPLATE.format(cells=mxcell_xml.strip())


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def is_valid_mxgraph_xml(xml: str) -> bool:
    """
    Validate that *xml* is a well-formed mxGraphModel document.

    Uses lxml for structural validation.  Returns False for any malformed or
    empty input rather than raising.
    """
    if not xml or not xml.strip():
        return False
    try:
        root = etree.fromstring(xml.encode())
        return root.tag == "mxGraphModel"
    except etree.XMLSyntaxError:
        return False


# ---------------------------------------------------------------------------
# Strip wrapper
# ---------------------------------------------------------------------------

_WRAPPER_TAGS: tuple[str, ...] = ("mxGraphModel", "mxfile", "root")


def strip_mxgraph_wrapper(xml: str) -> str:
    """
    Extract bare mxCell elements from a full mxGraphModel XML string.

    Strips <mxGraphModel>, <mxfile>, and <root> wrapper tags, returning
    only the inner mxCell elements joined by newlines.  Falls back to a
    regex-based strip if lxml cannot parse the document.
    """
    if not xml or not xml.strip():
        return ""

    try:
        root = etree.fromstring(xml.encode())
    except etree.XMLSyntaxError:
        # Best-effort regex fallback.
        stripped = xml
        for tag in _WRAPPER_TAGS:
            stripped = re.sub(
                rf"<{tag}[^>]*>|</{tag}\s*>",
                "",
                stripped,
                flags=re.IGNORECASE,
            )
        return stripped.strip()

    # Collect all mxCell descendants.
    cells = root.findall(".//mxCell")
    if not cells:
        return xml.strip()

    return "\n".join(etree.tostring(cell, encoding="unicode") for cell in cells)


# ---------------------------------------------------------------------------
# Minimal diagram detection
# ---------------------------------------------------------------------------

_ID2_RE = re.compile(r'id=["\']2["\']')


def is_minimal_diagram(xml: str) -> bool:
    """
    Return True if the XML represents an empty/minimal diagram.

    A minimal diagram has no cell with id="2" (i.e. no user-added shapes).
    Whitespace is stripped before checking so that formatted and compact XML
    are treated identically.
    """
    if not xml:
        return True
    return not bool(_ID2_RE.search(xml))
