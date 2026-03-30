"""
Convert AI SDK UIMessage format to litellm-compatible messages.

The Vercel AI SDK ``DefaultChatTransport`` sends messages in UIMessage format
where each message has a ``parts`` array.  litellm (and OpenAI-compatible APIs)
expect a ``content`` array with different part types.

UIMessage part types
--------------------
- ``{type: "text", text: "..."}``
- ``{type: "file", url: "data:...", mediaType: "..."}``
- ``{type: "tool-invocation", toolCallId: "...", toolName: "...",
     state: "partial-call"|"call"|"output-available"|"output-error"|"result",
     input: {...}, output: "...", errorText: "..."}``
- ``{type: "reasoning", text: "..."}``

litellm message format
----------------------
User messages::

    {"role": "user", "content": [
        {"type": "text", "text": "..."},
        {"type": "image_url", "image_url": {"url": "data:..."}}
    ]}

Assistant messages (with tool calls)::

    {"role": "assistant", "content": "optional text",
     "tool_calls": [{"id": "...", "type": "function",
                      "function": {"name": "...", "arguments": "{...}"}}]}

Tool result messages::

    {"role": "tool", "tool_call_id": "...", "name": "...", "content": "..."}
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

_DIAGRAM_TOOL_OUTPUT_PLACEHOLDER = (
    "[Diagram tool output replaced - see current diagram XML in system context]"
)


def _get_part_url(part: dict[str, Any]) -> str:
    return str(part.get("url") or part.get("data") or "")


def _get_part_media_type(part: dict[str, Any]) -> str:
    media_type = str(part.get("mediaType") or part.get("mimeType") or "")
    if media_type:
        return media_type

    url = _get_part_url(part)
    if url.startswith("data:"):
        import re

        match = re.match(r"^data:([^;,]+)[;,]", url)
        if match:
            return match.group(1)

    return ""


def _get_part_filename(part: dict[str, Any], default: str) -> str:
    return str(part.get("filename") or part.get("name") or default)


def _get_part_text_fallback(part: dict[str, Any]) -> str:
    return str(part.get("textFallback") or part.get("extractedText") or "")


def convert_ui_messages_to_litellm(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Convert a list of AI SDK UIMessages (with ``parts``) to litellm-format
    messages (with ``content`` / ``tool_calls``).

    Messages that are already in litellm format (have ``content`` but no
    ``parts``) are passed through unchanged.

    Parameters
    ----------
    messages:
        List of message dicts, each with at least ``role`` and either
        ``parts`` (UIMessage format) or ``content`` (litellm format).

    Returns
    -------
    list[dict]
        Messages in litellm-compatible format.
    """
    result: list[dict[str, Any]] = []

    for msg in messages:
        if not isinstance(msg, dict):
            continue

        role = msg.get("role", "")

        # Skip system messages — they are handled separately.
        if role == "system":
            continue

        parts = msg.get("parts")

        # If no parts, it's probably already in litellm format — pass through.
        if parts is None:
            result.append(msg)
            continue

        if not isinstance(parts, list):
            result.append(msg)
            continue

        if role == "user":
            converted = _convert_user_message(parts)
            if converted:
                # Log content types for debugging file handling
                ctypes = [c.get("type", "?") for c in converted]
                logger.info("User message converted: %d parts, types=%s", len(converted), ctypes)
                result.append({"role": "user", "content": converted})

        elif role == "assistant":
            converted_msgs = _convert_assistant_message(parts)
            result.extend(converted_msgs)

        else:
            # Unknown role — pass through.
            result.append(msg)

    # Filter out messages with empty content.
    result = [
        m for m in result
        if m.get("content") or m.get("tool_calls")
    ]

    return result


def _convert_user_message(parts: list[Any]) -> list[dict[str, Any]]:
    """Convert UIMessage user parts to litellm content array."""
    content: list[dict[str, Any]] = []

    for part in parts:
        if not isinstance(part, dict):
            # Plain string part.
            if isinstance(part, str) and part.strip():
                content.append({"type": "text", "text": part})
            continue

        ptype = part.get("type", "")

        if ptype == "text":
            text = part.get("text", "")
            if text:
                content.append({"type": "text", "text": text})

        elif ptype == "file":
            # File parts may be images, PDFs, or other files.
            url = _get_part_url(part)
            media_type = _get_part_media_type(part)
            filename = _get_part_filename(part, "file")
            text_fallback = _get_part_text_fallback(part).strip()
            logger.info(
                "File part: mediaType=%r, has_url=%s, url_prefix=%s, name=%r",
                media_type,
                bool(url),
                url[:60] if url else "",
                filename,
            )

            if not url:
                if text_fallback:
                    label = "PDF" if media_type == "application/pdf" else "File"
                    content.append({
                        "type": "text",
                        "text": f"[{label}: {filename}]\n{text_fallback}",
                    })
                    logger.info(
                        "File part missing inline payload; used text fallback. name=%r",
                        filename,
                    )
                    continue

                logger.info(
                    "File part has no 'url' or 'data' field; skipping metadata-only attachment. name=%r",
                    filename,
                )
                continue
            if not media_type:
                logger.warning(
                    "File part has no 'mediaType' or 'mimeType' field; skipping. name=%r, url_prefix=%s",
                    filename,
                    url[:60] if url else "",
                )
                continue

            if media_type.startswith("image/"):
                content.append({
                    "type": "image_url",
                    "image_url": {"url": url},
                })
            elif media_type == "application/pdf":
                pdf_filename = _get_part_filename(part, "document.pdf")
                if url.startswith("data:"):
                    # Base64 data URL — litellm converts to each
                    # provider's native format (OpenAI file, Anthropic
                    # document, Bedrock BedrockDocumentBlock, etc.).
                    content.append({
                        "type": "file",
                        "file": {
                            "file_data": url,
                            "filename": pdf_filename,
                        },
                    })
                elif url.startswith("http://") or url.startswith("https://"):
                    # Regular URL — store separately so downstream
                    # handlers can fetch the PDF when needed.
                    content.append({
                        "type": "file",
                        "file": {
                            "file_url": url,
                            "filename": pdf_filename,
                            **({"text_fallback": text_fallback} if text_fallback else {}),
                        },
                    })
                elif text_fallback:
                    # Unrecognised URL scheme but we have extracted text.
                    content.append({
                        "type": "text",
                        "text": f"[PDF: {pdf_filename}]\n{text_fallback}",
                    })
                else:
                    logger.warning(
                        "PDF part has unrecognised url scheme; skipping. name=%r, url_prefix=%s",
                        pdf_filename,
                        url[:60],
                    )
            else:
                # Other non-image files: include as text with metadata.
                content.append({
                    "type": "text",
                    "text": f"[Attached file: {_get_part_filename(part, 'file')} ({media_type})]",
                })

        elif ptype == "image":
            # Direct image part (less common, but possible).
            url = part.get("url", part.get("data", ""))
            if url:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": url},
                })

    return content


def _convert_assistant_message(parts: list[Any]) -> list[dict[str, Any]]:
    """
    Convert UIMessage assistant parts to litellm messages.

    An assistant message with tool invocations may produce multiple litellm
    messages:
    1. An assistant message with text + tool_calls
    2. One or more tool-result messages (role="tool")
    """
    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    tool_results: list[dict[str, Any]] = []

    for part in parts:
        if not isinstance(part, dict):
            if isinstance(part, str) and part.strip():
                text_parts.append(part)
            continue

        ptype = part.get("type", "")

        if ptype == "text":
            text = part.get("text", "")
            if text:
                text_parts.append(text)

        elif ptype == "reasoning":
            # Reasoning/thinking tokens — skip for history (not needed by litellm).
            pass

        elif ptype == "tool-invocation":
            tool_call_id = part.get("toolCallId", "")
            tool_name = part.get("toolName", "")
            state = part.get("state", "")
            tool_input = part.get("input", {})

            if not tool_call_id or not tool_name:
                continue

            # Skip tool calls with invalid/empty inputs.
            if (
                not tool_input
                or not isinstance(tool_input, dict)
                or len(tool_input) == 0
            ):
                continue

            # Serialize input to JSON string for litellm format.
            try:
                args_str = json.dumps(tool_input, ensure_ascii=False)
            except (TypeError, ValueError):
                args_str = "{}"

            tool_calls.append({
                "id": tool_call_id,
                "type": "function",
                "function": {
                    "name": tool_name,
                    "arguments": args_str,
                },
            })

            # If the tool has been executed, add a tool result message.
            # AI SDK UIMessage uses "result" (legacy), "output-available"
            # (success), or "output-error" (failure) for completed tools.
            if state in ("result", "output-available", "output-error"):
                if state == "output-error":
                    output = part.get("errorText", "") or part.get("output", "")
                else:
                    output = part.get("output", "")

                if isinstance(output, dict):
                    if tool_name in {"display_diagram", "edit_diagram", "append_diagram"}:
                        output = _DIAGRAM_TOOL_OUTPUT_PLACEHOLDER
                    else:
                        output = json.dumps(output, ensure_ascii=False)
                elif output is None:
                    output = ""
                else:
                    output = str(output)

                tool_results.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "name": tool_name,
                    "content": output,
                })

    # Build the assistant message.
    messages: list[dict[str, Any]] = []

    assistant_msg: dict[str, Any] = {"role": "assistant"}

    if text_parts:
        assistant_msg["content"] = "\n".join(text_parts)
    else:
        assistant_msg["content"] = ""

    if tool_calls:
        assistant_msg["tool_calls"] = tool_calls

    # Only add the assistant message if it has content or tool calls.
    if assistant_msg.get("content") or assistant_msg.get("tool_calls"):
        messages.append(assistant_msg)

    # Add tool results after the assistant message.
    messages.extend(tool_results)

    return messages


def extract_user_text_from_parts(parts: list[Any]) -> str:
    """
    Extract the text content from user message parts.

    Used for cache lookup and Langfuse tracing.
    """
    for part in parts:
        if isinstance(part, dict) and part.get("type") == "text":
            return part.get("text", "")
        if isinstance(part, str):
            return part
    return ""


def has_file_in_parts(parts: list[Any]) -> bool:
    """Return True if any part is a file with an image or PDF MIME type."""
    for part in parts:
        if not isinstance(part, dict):
            continue
        ptype = part.get("type", "")
        if ptype == "file":
            media_type = _get_part_media_type(part)
            if media_type and (
                media_type.startswith("image/") or media_type == "application/pdf"
            ):
                return True
        if ptype == "image":
            return True
    return False
