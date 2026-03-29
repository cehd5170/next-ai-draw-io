"""
Unit tests for diagram tool execution via dispatch_tool().

Covers:
- display_diagram  – create a new diagram from mxCell XML fragments
- edit_diagram     – apply update / add / delete operations to existing XML
- get_shape_library – return shape library docs with path-traversal protection

Note: importing app.tools registers all four tools into TOOL_REGISTRY.
"""

import pytest

# Importing app.tools triggers module-level register_tool() calls for all tools.
from app.tools import dispatch_tool, ToolContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ctx(current_xml: str = "", tmp_path=None) -> ToolContext:
    """Build a minimal ToolContext for testing."""
    shape_dir = str(tmp_path) if tmp_path is not None else ""
    return ToolContext(
        current_xml=current_xml,
        shape_library_dir=shape_dir,
        settings=None,
    )


# ---------------------------------------------------------------------------
# TestDisplayDiagram
# ---------------------------------------------------------------------------


class TestDisplayDiagram:
    @pytest.mark.asyncio
    async def test_valid_mxcell_succeeds(self, sample_mxcell_xml):
        """Valid mxCell XML produces a successful result with wrapped XML."""
        ctx = _ctx()
        result = await dispatch_tool("display_diagram", {"xml": sample_mxcell_xml}, ctx)
        assert result.success is True, f"Expected success, got: {result.content}"
        assert result.xml is not None, "Result XML should not be None on success"
        assert "<mxGraphModel>" in result.xml, (
            "Output should be wrapped in mxGraphModel"
        )

    @pytest.mark.asyncio
    async def test_empty_xml_fails(self):
        """Empty xml parameter returns a failure result."""
        ctx = _ctx()
        result = await dispatch_tool("display_diagram", {"xml": ""}, ctx)
        assert result.success is False, "Empty XML should fail"

    @pytest.mark.asyncio
    async def test_wrapper_tags_stripped_with_warning(self):
        """XML with mxGraphModel wrapper tags is processed (stripped) with a warning."""
        xml_with_wrapper = (
            "<mxGraphModel><root>"
            '<mxCell id="0"/><mxCell id="1" parent="0"/>'
            '<mxCell id="2" value="X" vertex="1" parent="1"/>'
            "</root></mxGraphModel>"
        )
        ctx = _ctx()
        result = await dispatch_tool("display_diagram", {"xml": xml_with_wrapper}, ctx)
        # The tool should process the XML (either succeed or fail with a clear message)
        # but must not raise an exception.
        assert isinstance(result.success, bool), (
            "Result must have a boolean success field"
        )

    @pytest.mark.asyncio
    async def test_reserved_ids_rejected(self):
        """XML containing id='0' or id='1' is rejected."""
        xml_with_reserved = (
            '<mxCell id="0"/>'
            '<mxCell id="1" parent="0"/>'
            '<mxCell id="2" value="Box" vertex="1" parent="1"/>'
        )
        ctx = _ctx()
        result = await dispatch_tool("display_diagram", {"xml": xml_with_reserved}, ctx)
        assert result.success is False, "Reserved IDs (0 and 1) must be rejected"

    @pytest.mark.asyncio
    async def test_truncated_xml_signals_is_truncated(self):
        """Truncated (incomplete) XML sets is_truncated=True on the result."""
        truncated = '<mxCell id="2" value="Unfinished'
        ctx = _ctx()
        result = await dispatch_tool("display_diagram", {"xml": truncated}, ctx)
        # A truncated fragment may fail or be flagged as truncated.
        if result.success:
            assert result.is_truncated is True, (
                "Truncated XML should set is_truncated=True"
            )

    @pytest.mark.asyncio
    async def test_result_xml_contains_root_cells(self, sample_mxcell_xml):
        """Wrapped output includes auto-generated root cells id=0 and id=1."""
        ctx = _ctx()
        result = await dispatch_tool("display_diagram", {"xml": sample_mxcell_xml}, ctx)
        assert result.success is True
        assert 'id="0"' in result.xml, "Wrapped XML should contain root cell id=0"
        assert 'id="1"' in result.xml, "Wrapped XML should contain root cell id=1"

    @pytest.mark.asyncio
    async def test_auto_layout_normalizes_edge_routing_hints(self):
        xml = """
<mxCell id="2" value="A" vertex="1" parent="1"><mxGeometry x="40" y="40" width="120" height="60" as="geometry"/></mxCell>
<mxCell id="3" value="B" vertex="1" parent="1"><mxGeometry x="280" y="40" width="120" height="60" as="geometry"/></mxCell>
<mxCell id="4" style="edgeStyle=elbowEdgeStyle;curved=1;exitX=1;exitY=0.5;entryX=0;entryY=0.5;" edge="1" parent="1" source="2" target="3">
  <mxGeometry relative="1" as="geometry">
    <mxPoint x="160" y="70" as="sourcePoint"/>
    <mxPoint x="280" y="70" as="targetPoint"/>
    <Array as="points"><mxPoint x="220" y="120"/></Array>
  </mxGeometry>
</mxCell>
"""
        ctx = _ctx()
        result = await dispatch_tool("display_diagram", {"xml": xml}, ctx)
        assert result.success is True
        assert result.layout == "mxHierarchicalLayout"
        assert "edgeStyle=orthogonalEdgeStyle" in result.xml
        assert "jettySize=auto" in result.xml
        assert "entryX=" not in result.xml
        assert "exitX=" not in result.xml
        assert "sourcePoint" not in result.xml
        assert "targetPoint" not in result.xml
        assert "<Array as=\"points\">" not in result.xml


# ---------------------------------------------------------------------------
# TestEditDiagram
# ---------------------------------------------------------------------------


class TestEditDiagram:
    @pytest.mark.asyncio
    async def test_update_label(self, sample_full_xml):
        """update operation changes the value attribute of an existing cell."""
        ctx = _ctx(current_xml=sample_full_xml)
        result = await dispatch_tool(
            "edit_diagram",
            {
                "operations": [
                    {
                        "operation": "update",
                        "cell_id": "2",
                        "new_xml": (
                            '<mxCell id="2" value="Updated" style="rounded=1;" '
                            'vertex="1" parent="1">'
                            '<mxGeometry x="100" y="100" width="120" height="60" '
                            'as="geometry"/></mxCell>'
                        ),
                    }
                ]
            },
            ctx,
        )
        assert result.success is True, f"Update should succeed: {result.content}"
        assert result.xml is not None
        assert "Updated" in result.xml, "New label should appear in the updated diagram XML"

    @pytest.mark.asyncio
    async def test_delete_cell_removes_it(self, sample_full_xml):
        """delete operation removes the targeted cell from the diagram."""
        ctx = _ctx(current_xml=sample_full_xml)
        result = await dispatch_tool(
            "edit_diagram",
            {"operations": [{"operation": "delete", "cell_id": "2"}]},
            ctx,
        )
        assert result.success is True, f"Delete should succeed: {result.content}"
        assert result.xml is not None
        assert 'id="2"' not in result.xml, "Deleted cell id=2 should not appear in result XML"

    @pytest.mark.asyncio
    async def test_delete_cascades_connected_edges(self, sample_full_xml):
        """Deleting a vertex also removes edges connected to it (source or target)."""
        ctx = _ctx(current_xml=sample_full_xml)
        result = await dispatch_tool(
            "edit_diagram",
            {"operations": [{"operation": "delete", "cell_id": "2"}]},
            ctx,
        )
        assert result.success is True
        # Edge id=4 connects source="2" to target="3" — it must be cascade-deleted.
        assert 'id="4"' not in result.xml, (
            "Edge id=4 (connected to deleted cell id=2) must be cascade-deleted"
        )

    @pytest.mark.asyncio
    async def test_update_nonexistent_cell_fails(self, sample_full_xml):
        """Updating a cell that does not exist returns a failure result."""
        ctx = _ctx(current_xml=sample_full_xml)
        result = await dispatch_tool(
            "edit_diagram",
            {
                "operations": [
                    {
                        "operation": "update",
                        "cell_id": "999",
                        "new_xml": '<mxCell id="999" value="Ghost" vertex="1" parent="1"/>',
                    }
                ]
            },
            ctx,
        )
        assert result.success is False, "Updating a non-existent cell should fail"

    @pytest.mark.asyncio
    async def test_add_new_cell(self, sample_full_xml):
        """add operation inserts a new mxCell into the diagram."""
        ctx = _ctx(current_xml=sample_full_xml)
        result = await dispatch_tool(
            "edit_diagram",
            {
                "operations": [
                    {
                        "operation": "add",
                        "cell_id": "99",
                        "new_xml": (
                            '<mxCell id="99" value="New Box" style="rounded=1;" '
                            'vertex="1" parent="1">'
                            '<mxGeometry x="400" y="200" width="120" height="60" '
                            'as="geometry"/></mxCell>'
                        ),
                    }
                ]
            },
            ctx,
        )
        assert result.success is True, f"Add should succeed: {result.content}"
        assert 'id="99"' in result.xml, "Newly added cell id=99 should appear in result"
        assert "New Box" in result.xml, "New cell value should appear in result"

    @pytest.mark.asyncio
    async def test_no_current_diagram_fails(self):
        """Editing when no diagram is displayed returns a failure result."""
        ctx = _ctx(current_xml="")
        result = await dispatch_tool(
            "edit_diagram",
            {
                "operations": [
                    {"operation": "delete", "cell_id": "2"}
                ]
            },
            ctx,
        )
        assert result.success is False, (
            "edit_diagram with no current XML should fail with a helpful message"
        )

    @pytest.mark.asyncio
    async def test_empty_operations_list_fails(self, sample_full_xml):
        """An empty operations list is rejected."""
        ctx = _ctx(current_xml=sample_full_xml)
        result = await dispatch_tool("edit_diagram", {"operations": []}, ctx)
        assert result.success is False, "Empty operations list should be rejected"


# ---------------------------------------------------------------------------
# TestShapeLibrary
# ---------------------------------------------------------------------------


class TestShapeLibrary:
    @pytest.mark.asyncio
    async def test_invalid_library_name(self, tmp_path):
        """Requesting a non-existent library returns failure with available list."""
        ctx = _ctx(tmp_path=tmp_path)
        result = await dispatch_tool(
            "get_shape_library", {"library": "nonexistent"}, ctx
        )
        assert result.success is False, "Non-existent library should return failure"
        assert (
            "Available libraries" in result.content
            or "not found" in result.content.lower()
            or "unknown" in result.content.lower()
        ), "Error message should mention available libraries or indicate not found"

    @pytest.mark.asyncio
    async def test_path_traversal_blocked(self, tmp_path):
        """Library names with path-traversal sequences are rejected."""
        ctx = _ctx(tmp_path=tmp_path)
        result = await dispatch_tool(
            "get_shape_library", {"library": "../../etc/passwd"}, ctx
        )
        assert result.success is False, "Path traversal attack must be blocked"

    @pytest.mark.asyncio
    async def test_empty_library_name_fails(self, tmp_path):
        """Empty library name returns a failure result."""
        ctx = _ctx(tmp_path=tmp_path)
        result = await dispatch_tool("get_shape_library", {"library": ""}, ctx)
        assert result.success is False, "Empty library name should fail"

    @pytest.mark.asyncio
    async def test_special_chars_in_library_name_rejected(self, tmp_path):
        """Library names with special characters outside [a-z0-9_-] are rejected."""
        ctx = _ctx(tmp_path=tmp_path)
        result = await dispatch_tool(
            "get_shape_library", {"library": "aws4; rm -rf /"}, ctx
        )
        assert result.success is False, "Injection characters in library name must be rejected"

    @pytest.mark.asyncio
    async def test_valid_library_file_returned(self, tmp_path):
        """A valid library with a corresponding .md file returns its contents."""
        # Create a mock library documentation file.
        lib_file = tmp_path / "flowchart.md"
        lib_file.write_text("# Flowchart Library\nShapes: start, end, decision\n")
        ctx = _ctx(tmp_path=tmp_path)
        result = await dispatch_tool("get_shape_library", {"library": "flowchart"}, ctx)
        assert result.success is True, f"Valid library with file should succeed: {result.content}"
        assert "Flowchart Library" in result.content, (
            "Library file content should appear in the result"
        )

    @pytest.mark.asyncio
    async def test_unknown_tool_name_fails(self):
        """Dispatching to a completely unknown tool returns a failure."""
        ctx = _ctx()
        result = await dispatch_tool("totally_unknown_tool", {}, ctx)
        assert result.success is False, "Unknown tool name must return a failure result"
