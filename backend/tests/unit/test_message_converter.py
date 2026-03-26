"""
Unit tests for the UI Message to litellm message converter.
"""

import json

import pytest

from app.services.message_converter import (
    convert_ui_messages_to_litellm,
    extract_user_text_from_parts,
    has_file_in_parts,
)


class TestConvertUIMessagesToLitellm:
    """Tests for convert_ui_messages_to_litellm."""

    def test_empty_messages(self):
        assert convert_ui_messages_to_litellm([]) == []

    def test_simple_user_text_message(self):
        messages = [
            {
                "id": "msg_1",
                "role": "user",
                "parts": [{"type": "text", "text": "Create a flowchart"}],
            }
        ]
        result = convert_ui_messages_to_litellm(messages)
        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert result[0]["content"] == [{"type": "text", "text": "Create a flowchart"}]

    def test_user_message_with_image(self):
        messages = [
            {
                "id": "msg_1",
                "role": "user",
                "parts": [
                    {"type": "text", "text": "Replicate this"},
                    {"type": "file", "url": "data:image/png;base64,abc", "mediaType": "image/png"},
                ],
            }
        ]
        result = convert_ui_messages_to_litellm(messages)
        assert len(result) == 1
        assert len(result[0]["content"]) == 2
        assert result[0]["content"][0] == {"type": "text", "text": "Replicate this"}
        assert result[0]["content"][1] == {
            "type": "image_url",
            "image_url": {"url": "data:image/png;base64,abc"},
        }

    def test_user_message_with_pdf(self):
        """PDF files use litellm file content block with inline base64."""
        messages = [
            {
                "id": "msg_1",
                "role": "user",
                "parts": [
                    {"type": "text", "text": "Analyze this PDF"},
                    {"type": "file", "url": "data:application/pdf;base64,abc", "mediaType": "application/pdf", "name": "test.pdf"},
                ],
            }
        ]
        result = convert_ui_messages_to_litellm(messages)
        assert len(result) == 1
        assert len(result[0]["content"]) == 2
        assert result[0]["content"][0] == {"type": "text", "text": "Analyze this PDF"}
        assert result[0]["content"][1] == {
            "type": "file",
            "file": {
                "file_data": "data:application/pdf;base64,abc",
                "filename": "test.pdf",
            },
        }

    def test_user_message_with_filename_alias(self):
        messages = [
            {
                "id": "msg_1",
                "role": "user",
                "parts": [
                    {
                        "type": "file",
                        "url": "data:application/pdf;base64,abc",
                        "mediaType": "application/pdf",
                        "filename": "alias.pdf",
                    },
                ],
            }
        ]
        result = convert_ui_messages_to_litellm(messages)
        assert result[0]["content"][0]["file"]["filename"] == "alias.pdf"

    def test_user_message_infers_media_type_from_data_url(self):
        messages = [
            {
                "id": "msg_1",
                "role": "user",
                "parts": [
                    {
                        "type": "file",
                        "url": "data:image/png;base64,abc",
                        "filename": "diagram.png",
                    },
                ],
            }
        ]
        result = convert_ui_messages_to_litellm(messages)
        assert result[0]["content"] == [
            {
                "type": "image_url",
                "image_url": {"url": "data:image/png;base64,abc"},
            }
        ]

    def test_assistant_message_with_text(self):
        messages = [
            {
                "id": "msg_1",
                "role": "assistant",
                "parts": [{"type": "text", "text": "Here is your flowchart"}],
            }
        ]
        result = convert_ui_messages_to_litellm(messages)
        assert len(result) == 1
        assert result[0]["role"] == "assistant"
        assert result[0]["content"] == "Here is your flowchart"

    def test_assistant_message_with_tool_invocation(self):
        messages = [
            {
                "id": "msg_1",
                "role": "assistant",
                "parts": [
                    {"type": "text", "text": "I'll create a diagram"},
                    {
                        "type": "tool-invocation",
                        "toolCallId": "call_123",
                        "toolName": "display_diagram",
                        "state": "result",
                        "input": {"xml": "<mxCell/>"},
                        "output": "Displayed",
                    },
                ],
            }
        ]
        result = convert_ui_messages_to_litellm(messages)
        # Should produce assistant message + tool result message
        assert len(result) == 2

        # Assistant message with tool_calls
        assert result[0]["role"] == "assistant"
        assert result[0]["content"] == "I'll create a diagram"
        assert len(result[0]["tool_calls"]) == 1
        assert result[0]["tool_calls"][0]["id"] == "call_123"
        assert result[0]["tool_calls"][0]["function"]["name"] == "display_diagram"
        assert json.loads(result[0]["tool_calls"][0]["function"]["arguments"]) == {"xml": "<mxCell/>"}

        # Tool result message
        assert result[1]["role"] == "tool"
        assert result[1]["tool_call_id"] == "call_123"
        assert result[1]["content"] == "Displayed"

    def test_skips_system_messages(self):
        messages = [
            {"role": "system", "parts": [{"type": "text", "text": "System prompt"}]},
            {"role": "user", "parts": [{"type": "text", "text": "Hello"}]},
        ]
        result = convert_ui_messages_to_litellm(messages)
        assert len(result) == 1
        assert result[0]["role"] == "user"

    def test_passthrough_litellm_format(self):
        """Messages without parts (already in litellm format) are passed through."""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        result = convert_ui_messages_to_litellm(messages)
        assert len(result) == 2
        assert result[0] == {"role": "user", "content": "Hello"}
        assert result[1] == {"role": "assistant", "content": "Hi there"}

    def test_filters_invalid_tool_calls(self):
        """Tool invocations with empty/invalid inputs are filtered out."""
        messages = [
            {
                "id": "msg_1",
                "role": "assistant",
                "parts": [
                    {
                        "type": "tool-invocation",
                        "toolCallId": "call_bad",
                        "toolName": "display_diagram",
                        "state": "call",
                        "input": {},
                    },
                    {"type": "text", "text": "Some text"},
                ],
            }
        ]
        result = convert_ui_messages_to_litellm(messages)
        assert len(result) == 1
        assert result[0]["role"] == "assistant"
        assert "tool_calls" not in result[0]
        assert result[0]["content"] == "Some text"

    def test_multi_turn_conversation(self):
        """Full multi-turn conversation with tool use."""
        messages = [
            {
                "id": "msg_1",
                "role": "user",
                "parts": [{"type": "text", "text": "Draw a flowchart"}],
            },
            {
                "id": "msg_2",
                "role": "assistant",
                "parts": [
                    {"type": "text", "text": "Creating a flowchart"},
                    {
                        "type": "tool-invocation",
                        "toolCallId": "call_1",
                        "toolName": "display_diagram",
                        "state": "result",
                        "input": {"xml": "<mxCell id='2'/>"},
                        "output": "Displayed",
                    },
                ],
            },
            {
                "id": "msg_3",
                "role": "user",
                "parts": [{"type": "text", "text": "Add a box"}],
            },
        ]
        result = convert_ui_messages_to_litellm(messages)
        # user + assistant + tool result + user = 4 messages
        assert len(result) == 4
        assert result[0]["role"] == "user"
        assert result[1]["role"] == "assistant"
        assert result[2]["role"] == "tool"
        assert result[3]["role"] == "user"

    def test_reasoning_parts_skipped(self):
        """Reasoning/thinking parts are not included in output."""
        messages = [
            {
                "id": "msg_1",
                "role": "assistant",
                "parts": [
                    {"type": "reasoning", "text": "Let me think..."},
                    {"type": "text", "text": "Here's the answer"},
                ],
            }
        ]
        result = convert_ui_messages_to_litellm(messages)
        assert len(result) == 1
        assert result[0]["content"] == "Here's the answer"


class TestExtractUserTextFromParts:
    def test_text_part(self):
        parts = [{"type": "text", "text": "Hello world"}]
        assert extract_user_text_from_parts(parts) == "Hello world"

    def test_string_part(self):
        parts = ["Hello world"]
        assert extract_user_text_from_parts(parts) == "Hello world"

    def test_empty_parts(self):
        assert extract_user_text_from_parts([]) == ""

    def test_no_text_part(self):
        parts = [{"type": "file", "url": "data:image/png;base64,..."}]
        assert extract_user_text_from_parts(parts) == ""


class TestHasFileInParts:
    def test_image_file(self):
        parts = [{"type": "file", "url": "data:image/png;base64,...", "mediaType": "image/png"}]
        assert has_file_in_parts(parts) is True

    def test_no_image(self):
        parts = [{"type": "text", "text": "Hello"}]
        assert has_file_in_parts(parts) is False

    def test_pdf_file_detected(self):
        parts = [{"type": "file", "url": "data:application/pdf;base64,...", "mediaType": "application/pdf"}]
        assert has_file_in_parts(parts) is True

    def test_file_detected_when_media_type_is_in_data_url(self):
        parts = [{"type": "file", "url": "data:image/png;base64,..."}]
        assert has_file_in_parts(parts) is True

    def test_image_type_part(self):
        parts = [{"type": "image", "url": "data:image/png;base64,..."}]
        assert has_file_in_parts(parts) is True
