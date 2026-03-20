"""
Unit tests for app/services/json_repair.py

Covers:
- repair_tool_call_json  – parse and repair truncated / malformed LLM tool-call JSON
- get_fallback_tool_input – per-tool safe fallback dicts when repair fails
"""

import pytest
from app.services.json_repair import repair_tool_call_json, get_fallback_tool_input


class TestRepairToolCallJson:
    def test_valid_json_passthrough(self):
        """Correctly escaped JSON is parsed without modification."""
        result = repair_tool_call_json('{"xml": "<mxCell id=\\"2\\"/>"}')
        assert result is not None, "Valid JSON should parse successfully"
        assert result["xml"] == '<mxCell id="2"/>', (
            "Inner XML content should be unescaped correctly"
        )

    def test_valid_simple_json(self):
        """A simple valid JSON object with no XML returns the parsed dict."""
        result = repair_tool_call_json('{"operations": []}')
        assert result is not None
        assert result["operations"] == []

    def test_truncated_json_repaired(self):
        """json_repair should recover from truncated JSON (missing closing brace)."""
        result = repair_tool_call_json('{"xml": "<mxCell id=\\"2\\"')
        # json_repair handles this case; result should be a dict (not None)
        assert result is not None, "json_repair should recover from truncated JSON"

    def test_colon_equals_fix(self):
        """':=' syntax (LLM mistake) is converted to ':' before parsing."""
        result = repair_tool_call_json('{"xml" := "test"}')
        assert result is not None, "':=' pre-processing should fix the input"
        assert result.get("xml") == "test", "Value should be correctly extracted"

    def test_equals_quote_fix(self):
        """'= \"' syntax (assignment leak) is normalised to ': \"'."""
        result = repair_tool_call_json('{"xml" = "hello"}')
        # After pre-processing '= "' becomes ': "', making this valid JSON.
        assert result is not None, "'= \"' pre-processing should fix the input"

    def test_completely_invalid_returns_none_or_repaired(self):
        """Severely malformed input either returns None or a repaired dict."""
        result = repair_tool_call_json("not json at all {{{")
        # json_repair may return something or None; we accept both.
        assert result is None or isinstance(result, dict), (
            "Result must be None or a dict for severely broken input"
        )

    def test_empty_string_returns_none(self):
        """Empty input always returns None."""
        assert repair_tool_call_json("") is None

    def test_whitespace_only_returns_none(self):
        """Whitespace-only input returns None."""
        assert repair_tool_call_json("   \n  ") is None

    def test_nested_operations_list(self):
        """Valid JSON with a nested operations list is parsed correctly."""
        raw = '{"operations": [{"operation": "update", "cell_id": "2"}]}'
        result = repair_tool_call_json(raw)
        assert result is not None
        assert len(result["operations"]) == 1
        assert result["operations"][0]["operation"] == "update"

    def test_result_is_dict_not_list(self):
        """Repair always returns a dict or None, never a bare list."""
        result = repair_tool_call_json('["a", "b"]')
        # A JSON array at top level is not a valid tool-call body → None
        assert result is None or isinstance(result, dict)


class TestGetFallbackToolInput:
    def test_display_diagram_fallback(self):
        """display_diagram fallback has an empty 'xml' key."""
        result = get_fallback_tool_input("display_diagram")
        assert result == {"xml": ""}, (
            "display_diagram fallback should be {'xml': ''}"
        )

    def test_edit_diagram_fallback(self):
        """edit_diagram fallback has an empty 'operations' list."""
        result = get_fallback_tool_input("edit_diagram")
        assert result == {"operations": []}, (
            "edit_diagram fallback should be {'operations': []}"
        )

    def test_append_diagram_fallback(self):
        """append_diagram fallback has an empty 'xml' key."""
        result = get_fallback_tool_input("append_diagram")
        assert result == {"xml": ""}, (
            "append_diagram fallback should be {'xml': ''}"
        )

    def test_get_shape_library_fallback(self):
        """get_shape_library fallback has a safe default library name."""
        result = get_fallback_tool_input("get_shape_library")
        assert "library" in result, "get_shape_library fallback must have 'library' key"

    def test_unknown_tool_returns_empty_dict(self):
        """Unknown tool names return an empty dict rather than raising."""
        result = get_fallback_tool_input("unknown_tool_xyz")
        assert result == {}, (
            "Unknown tool should return an empty dict as fallback"
        )

    def test_fallback_returns_copy(self):
        """Each call returns an independent copy to prevent mutation side-effects."""
        a = get_fallback_tool_input("display_diagram")
        b = get_fallback_tool_input("display_diagram")
        a["xml"] = "mutated"
        assert b["xml"] == "", "Fallback dict should be a fresh copy each time"
