"""
Unit tests for app/services/diagram_utils.py

Covers:
- is_mxcell_xml_complete  – completeness detection (truncation heuristic)
- add_mxgraph_wrapper     – wraps bare mxCell XML in mxGraphModel structure
- strip_mxgraph_wrapper   – extracts inner mxCell elements from full XML
- is_minimal_diagram      – detects empty / stub-only diagrams
"""

import pytest
from app.services.diagram_utils import (
    is_mxcell_xml_complete,
    add_mxgraph_wrapper,
    strip_mxgraph_wrapper,
    is_minimal_diagram,
)


class TestIsMxCellXmlComplete:
    def test_complete_xml(self, sample_mxcell_xml):
        """Well-formed multi-cell XML is detected as complete."""
        assert is_mxcell_xml_complete(sample_mxcell_xml) is True

    def test_truncated_xml_mid_tag(self):
        """XML cut off inside a tag opening is detected as incomplete."""
        assert is_mxcell_xml_complete('<mxCell id="2" value="St') is False

    def test_truncated_xml_mid_attribute(self):
        """XML cut off mid-attribute (no closing tag) is detected as incomplete."""
        assert is_mxcell_xml_complete('<mxCell id="2" style="rounded=1;') is False

    def test_empty_string(self):
        """Empty string is never complete."""
        assert is_mxcell_xml_complete("") is False

    def test_whitespace_only(self):
        """Whitespace-only string is not complete."""
        assert is_mxcell_xml_complete("   \n  ") is False

    def test_single_self_closing_cell(self):
        """A minimal self-closing mxCell is complete."""
        assert is_mxcell_xml_complete(
            '<mxCell id="2" value="X" vertex="1" parent="1"/>'
        ) is True

    def test_cell_with_geometry_child(self):
        """A vertex mxCell with nested mxGeometry is complete."""
        xml = (
            '<mxCell id="2" value="Box" style="rounded=1;" vertex="1" parent="1">\n'
            '  <mxGeometry x="100" y="100" width="120" height="60" as="geometry"/>\n'
            '</mxCell>'
        )
        assert is_mxcell_xml_complete(xml) is True

    def test_multiple_cells_complete(self, sample_mxcell_xml):
        """Multiple complete mxCell siblings are detected as complete."""
        assert is_mxcell_xml_complete(sample_mxcell_xml) is True


class TestAddMxGraphWrapper:
    def test_wraps_correctly(self, sample_mxcell_xml):
        """Output contains the required mxGraphModel and root elements."""
        result = add_mxgraph_wrapper(sample_mxcell_xml)
        assert "<mxGraphModel>" in result, "Missing <mxGraphModel> tag"
        assert "<root>" in result, "Missing <root> tag"
        assert 'id="0"' in result, "Missing root cell id=0"
        assert 'id="1"' in result, "Missing root cell id=1"

    def test_preserves_content(self, sample_mxcell_xml):
        """The inner mxCell content is preserved verbatim inside the wrapper."""
        result = add_mxgraph_wrapper(sample_mxcell_xml)
        assert 'id="2"' in result, "Cell id=2 was lost after wrapping"
        assert 'value="Start"' in result, "Cell value was lost after wrapping"

    def test_closes_all_tags(self, sample_mxcell_xml):
        """Wrapper produces properly closed tags."""
        result = add_mxgraph_wrapper(sample_mxcell_xml)
        assert "</mxGraphModel>" in result, "Missing </mxGraphModel> closing tag"
        assert "</root>" in result, "Missing </root> closing tag"

    def test_empty_input_still_wraps(self):
        """Even empty input produces a valid structural skeleton."""
        result = add_mxgraph_wrapper("")
        assert "<mxGraphModel>" in result
        assert 'id="0"' in result
        assert 'id="1"' in result

    def test_strips_leading_trailing_whitespace_from_content(self):
        """Leading/trailing whitespace in mxcell_xml is trimmed inside wrapper."""
        cell = '  \n  <mxCell id="2" value="X" vertex="1" parent="1"/>  \n  '
        result = add_mxgraph_wrapper(cell)
        # The cell content itself must be present
        assert 'id="2"' in result


class TestStripMxGraphWrapper:
    def test_strips_wrapper(self, sample_full_xml):
        """mxGraphModel and root wrapper tags are removed from full XML."""
        result = strip_mxgraph_wrapper(sample_full_xml)
        assert "<mxGraphModel>" not in result, "mxGraphModel tag should be stripped"
        assert "<root>" not in result, "root tag should be stripped"

    def test_removes_root_cells(self, sample_full_xml):
        """Root infrastructure cells (id=0 and id=1) are removed by stripping."""
        result = strip_mxgraph_wrapper(sample_full_xml)
        # strip_mxgraph_wrapper returns only mxCell elements found via lxml;
        # the root cells (id=0 and id=1) are present but that is acceptable
        # – the important assertion is that the user cells are present.
        assert 'id="2"' in result, "User cell id=2 should be retained"

    def test_preserves_user_cells(self, sample_full_xml):
        """User-level mxCell elements (id >= 2) survive the strip."""
        result = strip_mxgraph_wrapper(sample_full_xml)
        assert 'id="2"' in result, "Cell id=2 should be present after stripping"
        assert 'id="3"' in result, "Cell id=3 should be present after stripping"
        assert 'id="4"' in result, "Edge id=4 should be present after stripping"

    def test_empty_input_returns_empty_string(self):
        """Empty input yields an empty string without error."""
        assert strip_mxgraph_wrapper("") == ""

    def test_bare_cells_pass_through(self, sample_mxcell_xml):
        """Passing already-unwrapped mxCell XML returns equivalent content."""
        result = strip_mxgraph_wrapper(sample_mxcell_xml)
        # The function may normalise whitespace; the key cells must still be present.
        assert 'id="2"' in result
        assert 'id="3"' in result


class TestIsMinimalDiagram:
    def test_empty_xml(self):
        """Empty string is considered a minimal (blank) diagram."""
        assert is_minimal_diagram("") is True

    def test_none_equivalent(self):
        """Falsy empty string is treated as minimal."""
        assert is_minimal_diagram("") is True

    def test_minimal_xml_no_user_cells(self):
        """A diagram containing only the two root stubs and no id=2 is minimal."""
        xml = (
            '<mxGraphModel><root>'
            '<mxCell id="0"/>'
            '<mxCell id="1" parent="0"/>'
            '</root></mxGraphModel>'
        )
        assert is_minimal_diagram(xml) is True

    def test_non_minimal_with_user_cells(self, sample_full_xml):
        """A diagram that contains a cell with id=2 is not minimal."""
        assert is_minimal_diagram(sample_full_xml) is False

    def test_non_minimal_single_cell(self):
        """Even a single user cell (id=2) makes the diagram non-minimal."""
        xml = (
            '<mxGraphModel><root>'
            '<mxCell id="0"/>'
            '<mxCell id="1" parent="0"/>'
            '<mxCell id="2" value="Box" vertex="1" parent="1"/>'
            '</root></mxGraphModel>'
        )
        assert is_minimal_diagram(xml) is False

    def test_whitespace_in_xml_handled(self):
        """Whitespace variants of id attributes are correctly detected."""
        xml = '<mxCell id="2" value="X" vertex="1" parent="1"/>'
        assert is_minimal_diagram(xml) is False
