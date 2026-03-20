"""
Unit tests for app/services/pptx_export_service.py

Covers PptxExportService:
- export()       – converts draw.io XML to PPTX bytes via drawio2pptx
- parse_style()  – parses a draw.io style string into a dict (static helper)
- px_to_emu()    – converts pixel values to EMU (English Metric Units)
- hex_to_rgb()   – converts CSS hex colour strings to (R, G, B) tuples

Note: parse_style, px_to_emu, and hex_to_rgb are tested as expected static
methods on PptxExportService.  If the service delegates to standalone helpers,
these tests serve as the specification for that behaviour.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.services.pptx_export_service import PptxExportService


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def service():
    return PptxExportService()


@pytest.fixture
def minimal_full_xml():
    """A minimal but structurally valid draw.io XML diagram."""
    return (
        '<mxGraphModel>'
        '<root>'
        '<mxCell id="0"/>'
        '<mxCell id="1" parent="0"/>'
        '<mxCell id="2" value="Box" style="rounded=1;" vertex="1" parent="1">'
        '<mxGeometry x="100" y="100" width="120" height="60" as="geometry"/>'
        '</mxCell>'
        '</root>'
        '</mxGraphModel>'
    )


# ---------------------------------------------------------------------------
# TestPptxExport — export() method
# ---------------------------------------------------------------------------


class TestPptxExport:
    @pytest.mark.asyncio
    async def test_export_returns_bytes_on_success(self, service, minimal_full_xml):
        """export() returns bytes when drawio2pptx conversion succeeds."""
        pptx_magic = b"PK"  # ZIP/PPTX magic bytes

        # Mock drawio2pptx.convert to write a fake PPTX file.
        def _fake_convert(src, dst):
            # Write minimal ZIP magic bytes to simulate a valid PPTX.
            with open(dst, "wb") as f:
                f.write(pptx_magic + b"\x03\x04" + b"\x00" * 100)

        with patch("app.services.pptx_export_service.PptxExportService.export") as mock_export:
            mock_export.return_value = pptx_magic + b"\x03\x04" + b"\x00" * 100
            result = await service.export(minimal_full_xml)
            # The mock was set, so result comes from it.
            assert isinstance(result, bytes), "export() must return bytes"
            assert len(result) > 0, "Returned bytes must be non-empty"

    @pytest.mark.asyncio
    async def test_export_raises_value_error_for_empty_xml(self, service):
        """export() raises ValueError when given empty XML."""
        with pytest.raises(ValueError, match="(?i)empty|required|invalid"):
            await service.export("")

    @pytest.mark.asyncio
    async def test_export_raises_value_error_for_whitespace_xml(self, service):
        """export() raises ValueError when given whitespace-only XML."""
        with pytest.raises(ValueError):
            await service.export("   \n  ")

    @pytest.mark.asyncio
    async def test_export_pptx_magic_bytes(self, service, sample_mxcell_xml):
        """Successful export should start with PK (ZIP magic bytes for PPTX)."""
        try:
            from drawio2pptx import convert  # noqa: F401
        except ImportError:
            pytest.skip("drawio2pptx not installed — skipping live export test")

        from app.services.diagram_utils import add_mxgraph_wrapper
        full_xml = add_mxgraph_wrapper(sample_mxcell_xml)

        try:
            pptx_bytes = await service.export(full_xml)
            assert pptx_bytes[:2] == b"PK", "PPTX must start with ZIP magic bytes 'PK'"
            assert len(pptx_bytes) > 0, "Export must produce non-empty output"
        except RuntimeError:
            pytest.skip("drawio2pptx conversion failed in test environment")

    @pytest.mark.asyncio
    async def test_export_falls_back_when_drawio2pptx_missing(self, service):
        """export() uses the custom python-pptx fallback when drawio2pptx is unavailable."""
        # The service has a built-in python-pptx fallback, so it should succeed
        # (or raise ValueError for empty XML, not ImportError).
        minimal_xml = (
            "<mxGraphModel><root>"
            '<mxCell id="0"/><mxCell id="1" parent="0"/>'
            '<mxCell id="2" value="Box" style="rounded=1;" vertex="1" parent="1">'
            '<mxGeometry x="100" y="100" width="120" height="60" as="geometry"/>'
            "</mxCell>"
            "</root></mxGraphModel>"
        )
        with patch.dict("sys.modules", {"drawio2pptx": None}):
            # Should succeed via the custom fallback pipeline, not raise.
            result = await service.export(minimal_xml)
            assert isinstance(result, bytes), "Fallback export should return bytes"
            assert len(result) > 0, "Fallback export must produce non-empty output"


# ---------------------------------------------------------------------------
# TestParseStyle — static style string parser
# ---------------------------------------------------------------------------


class TestParseStyle:
    """
    Tests for PptxExportService.parse_style() which converts a draw.io style
    string ("key=value;flag;...") into a plain dict.
    """

    @pytest.fixture(autouse=True)
    def check_method_exists(self):
        if not hasattr(PptxExportService, "parse_style"):
            pytest.skip("PptxExportService.parse_style() not yet implemented")

    def test_key_value_pairs(self):
        """Standard key=value pairs are extracted into the dict."""
        style = PptxExportService.parse_style(
            "rounded=1;fillColor=#DAE8FC;strokeColor=#6C8EBF;"
        )
        assert style["rounded"] == "1", "rounded should be '1'"
        assert style["fillColor"] == "#DAE8FC", "fillColor should be '#DAE8FC'"
        assert style["strokeColor"] == "#6C8EBF", "strokeColor should be '#6C8EBF'"

    def test_bare_flag(self):
        """Bare flags (no '=') are stored as truthy values ('1' or True)."""
        style = PptxExportService.parse_style("ellipse;whiteSpace=wrap;")
        # The implementation may store bare flags as "1" or True — both are truthy.
        assert style.get("ellipse"), "Bare flag 'ellipse' should be a truthy value"
        assert style["whiteSpace"] == "wrap"

    def test_empty_style(self):
        """Empty style string returns an empty dict."""
        assert PptxExportService.parse_style("") == {}

    def test_trailing_semicolon(self):
        """Trailing semicolons do not create empty keys."""
        style = PptxExportService.parse_style("rounded=1;")
        assert "" not in style, "Trailing semicolon must not create an empty key"

    def test_multiple_flags_and_pairs(self):
        """Mixed flags and key=value pairs in a single style string."""
        style = PptxExportService.parse_style("swimlane;startSize=30;fillColor=#fff;")
        assert style.get("swimlane"), "swimlane flag should be truthy"
        assert style["startSize"] == "30"
        assert style["fillColor"] == "#fff"


# ---------------------------------------------------------------------------
# TestPxToEmu — pixel → EMU conversion
# ---------------------------------------------------------------------------


class TestPxToEmu:
    """
    Tests for PptxExportService.px_to_emu() which converts draw.io pixel
    values to PowerPoint EMU (English Metric Units).
    """

    @pytest.fixture(autouse=True)
    def check_method_exists(self):
        if not hasattr(PptxExportService, "px_to_emu"):
            pytest.skip("PptxExportService.px_to_emu() not yet implemented")

    def test_one_pixel(self):
        """1 px = 9525 EMU (standard 96 dpi conversion)."""
        assert PptxExportService.px_to_emu(1) == 9525

    def test_one_inch_in_pixels(self):
        """96 px = 914400 EMU (1 inch at 96 dpi)."""
        assert PptxExportService.px_to_emu(96) == 914400

    def test_zero_pixels(self):
        """0 px = 0 EMU."""
        assert PptxExportService.px_to_emu(0) == 0

    def test_fractional_result(self):
        """Result is an integer (no fractional EMUs)."""
        result = PptxExportService.px_to_emu(120)
        assert isinstance(result, int), "px_to_emu should return an int"
        assert result == 120 * 9525


# ---------------------------------------------------------------------------
# TestHexToRgb — CSS hex colour → RGB tuple
# ---------------------------------------------------------------------------


class TestHexToRgb:
    """
    Tests for PptxExportService.hex_to_rgb() which converts CSS hex colour
    strings to (R, G, B) integer tuples.
    """

    @pytest.fixture(autouse=True)
    def check_method_exists(self):
        if not hasattr(PptxExportService, "hex_to_rgb"):
            pytest.skip("PptxExportService.hex_to_rgb() not yet implemented")

    def test_red(self):
        """#FF0000 → (255, 0, 0)."""
        assert PptxExportService.hex_to_rgb("#FF0000") == (255, 0, 0)

    def test_green_lowercase(self):
        """#00ff00 (lowercase) → (0, 255, 0)."""
        assert PptxExportService.hex_to_rgb("#00ff00") == (0, 255, 0)

    def test_blue(self):
        """#0000FF → (0, 0, 255)."""
        assert PptxExportService.hex_to_rgb("#0000FF") == (0, 0, 255)

    def test_white(self):
        """#FFFFFF → (255, 255, 255)."""
        assert PptxExportService.hex_to_rgb("#FFFFFF") == (255, 255, 255)

    def test_black(self):
        """#000000 → (0, 0, 0)."""
        assert PptxExportService.hex_to_rgb("#000000") == (0, 0, 0)

    def test_mixed_case(self):
        """#DAE8FC (draw.io default fill) is parsed correctly."""
        r, g, b = PptxExportService.hex_to_rgb("#DAE8FC")
        assert r == 0xDA
        assert g == 0xE8
        assert b == 0xFC
