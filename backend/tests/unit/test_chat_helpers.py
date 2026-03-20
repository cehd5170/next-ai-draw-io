"""
Unit tests for app/services/file_processing.py

Covers:
- validate_file_parts              – enforces per-message file count and size limits
- replace_historical_tool_inputs   – redacts large XML payloads in chat history
"""

import pytest
from app.services.file_processing import validate_file_parts, replace_historical_tool_inputs

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_XML_PLACEHOLDER = "[XML content replaced"


def _make_image_message(data: str) -> dict:
    """Construct a message dict with a single image part using the 'parts' key."""
    return {"parts": [{"type": "image", "data": data}]}


def _make_n_image_messages(n: int, data_size: int = 10) -> list[dict]:
    """Return a list with one message containing *n* image parts."""
    parts = [
        {"type": "image", "data": "data:image/png;base64," + "A" * data_size}
        for _ in range(n)
    ]
    return [{"parts": parts}]


# ---------------------------------------------------------------------------
# TestValidateFileParts
# ---------------------------------------------------------------------------


class TestValidateFileParts:
    def test_valid_single_file(self):
        """A single small image within both limits should not raise."""
        messages = [_make_image_message("data:image/png;base64," + "A" * 100)]
        validate_file_parts(messages, 2 * 1024 * 1024, 5)  # should not raise

    def test_valid_multiple_files_at_limit(self):
        """Exactly max_files images at the limit should not raise."""
        messages = _make_n_image_messages(5, data_size=10)
        validate_file_parts(messages, 2 * 1024 * 1024, 5)  # should not raise

    def test_too_many_files_raises(self):
        """Exceeding max_files raises ValueError with a descriptive message."""
        messages = _make_n_image_messages(6)
        with pytest.raises(ValueError, match="(?i)too many|maximum"):
            validate_file_parts(messages, 2 * 1024 * 1024, 5)

    def test_file_too_large_raises(self):
        """A file whose base64 exceeds the byte limit raises ValueError."""
        # 3 MB of base64 characters encodes to ~2.25 MB of raw bytes
        large_data = "data:image/png;base64," + "A" * (3 * 1024 * 1024)
        messages = [_make_image_message(large_data)]
        with pytest.raises(ValueError, match="(?i)exceeds|limit|MB"):
            validate_file_parts(messages, 2 * 1024 * 1024, 5)

    def test_configurable_size_limit_allows_larger_file(self):
        """With a 3 MB limit, a ~2.5 MB file should be accepted."""
        # 2.5 MB * (4/3) ≈ 3.33 MB of base64 characters → decoded ≈ 2.5 MB
        data = "data:image/png;base64," + "A" * int(2.5 * 1024 * 1024)
        messages = [_make_image_message(data)]
        validate_file_parts(messages, 3 * 1024 * 1024, 5)  # should not raise

    def test_empty_messages_list_is_valid(self):
        """An empty messages list should not raise."""
        validate_file_parts([], 2 * 1024 * 1024, 5)

    def test_message_with_no_parts_is_valid(self):
        """A message with no parts key should not raise."""
        messages = [{"role": "user", "content": "Hello"}]
        validate_file_parts(messages, 2 * 1024 * 1024, 5)

    def test_text_parts_not_counted_as_files(self):
        """Text-type parts should not be counted toward the file limit."""
        text_parts = [{"type": "text", "text": "hello"}] * 10
        messages = [{"parts": text_parts}]
        validate_file_parts(messages, 2 * 1024 * 1024, 5)  # should not raise

    def test_only_last_message_is_checked(self):
        """Only the final message in the list is validated for file limits."""
        # Earlier messages can have many files without triggering the limit.
        old_message = _make_n_image_messages(10)[0]
        valid_last = _make_image_message("data:image/png;base64," + "A" * 10)
        messages = [old_message, valid_last]
        validate_file_parts(messages, 2 * 1024 * 1024, 5)  # should not raise

    def test_file_type_also_counted(self):
        """Parts with type='file' count toward the file limit (not just 'image')."""
        parts = [
            {"type": "file", "data": "data:application/pdf;base64," + "A" * 10}
            for _ in range(6)
        ]
        messages = [{"parts": parts}]
        with pytest.raises(ValueError):
            validate_file_parts(messages, 2 * 1024 * 1024, 5)


# ---------------------------------------------------------------------------
# TestReplaceHistoricalToolInputs
# ---------------------------------------------------------------------------


class TestReplaceHistoricalToolInputs:
    def _make_tool_call_message(self, tool_name: str, input_data: dict) -> dict:
        """Build an assistant message with a tool-call content part."""
        return {
            "role": "assistant",
            "content": [
                {
                    "type": "tool-call",
                    "toolName": tool_name,
                    "input": input_data,
                }
            ],
        }

    def test_replaces_display_diagram_xml(self):
        """display_diagram tool input XML is replaced with a placeholder."""
        messages = [
            self._make_tool_call_message(
                "display_diagram", {"xml": "<mxCell ...big xml...>"}
            ),
            {"role": "user", "content": "looks good"},
        ]
        result = replace_historical_tool_inputs(messages)
        # The assistant message should still be present
        assert len(result) >= 1
        tool_msg = result[0]
        assert tool_msg["role"] == "assistant"
        new_input = tool_msg["content"][0]["input"]
        assert _XML_PLACEHOLDER in str(new_input), (
            "display_diagram XML should be replaced with the placeholder"
        )

    def test_replaces_edit_diagram_xml(self):
        """edit_diagram tool input is replaced with a placeholder."""
        messages = [
            self._make_tool_call_message(
                "edit_diagram",
                {"operations": [{"operation": "update", "cell_id": "2", "new_xml": "..."}]},
            ),
        ]
        result = replace_historical_tool_inputs(messages)
        new_input = result[0]["content"][0]["input"]
        assert _XML_PLACEHOLDER in str(new_input), (
            "edit_diagram input should be replaced with the placeholder"
        )

    def test_replaces_append_diagram_xml(self):
        """append_diagram tool input is replaced with a placeholder."""
        messages = [
            self._make_tool_call_message("append_diagram", {"xml": "<mxCell id='5'/>"}),
        ]
        result = replace_historical_tool_inputs(messages)
        new_input = result[0]["content"][0]["input"]
        assert _XML_PLACEHOLDER in str(new_input)

    def test_non_diagram_tool_preserved(self):
        """get_shape_library tool calls are NOT replaced."""
        messages = [
            self._make_tool_call_message("get_shape_library", {"library": "aws4"}),
        ]
        result = replace_historical_tool_inputs(messages)
        assert result[0]["content"][0]["input"] == {"library": "aws4"}, (
            "Non-diagram tool input should be preserved verbatim"
        )

    def test_user_messages_unchanged(self):
        """User role messages pass through without modification."""
        messages = [{"role": "user", "content": "make me a diagram"}]
        result = replace_historical_tool_inputs(messages)
        assert result == messages, "User messages should be unchanged"

    def test_empty_messages_returns_empty(self):
        """Empty input returns an empty list."""
        assert replace_historical_tool_inputs([]) == []

    def test_tool_call_with_empty_input_filtered_out(self):
        """Tool calls with empty/None input are filtered out entirely."""
        messages = [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool-call",
                        "toolName": "display_diagram",
                        "input": {},  # empty — indicates interrupted streaming
                    }
                ],
            }
        ]
        result = replace_historical_tool_inputs(messages)
        # The message with an empty-input tool call should be dropped.
        assert len(result) == 0 or result[0].get("content") == [], (
            "Tool calls with empty inputs should be filtered out"
        )

    def test_assistant_message_without_tool_calls_unchanged(self):
        """Assistant text messages (no tool calls) pass through unchanged."""
        messages = [
            {"role": "assistant", "content": [{"type": "text", "text": "Here is your diagram."}]},
        ]
        result = replace_historical_tool_inputs(messages)
        assert result[0]["content"][0]["text"] == "Here is your diagram."
