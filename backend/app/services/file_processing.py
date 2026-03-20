"""
File / message processing helpers used by the /chat route.

Ported from lib/chat-helpers.ts (validateFileParts, replaceHistoricalToolInputs,
isMinimalDiagram).
"""

from __future__ import annotations

import math
import re
from typing import Any

# ---------------------------------------------------------------------------
# File part validation
# ---------------------------------------------------------------------------

_XML_PLACEHOLDER = "[XML content replaced - see current diagram XML in system context]"


def validate_file_parts(
    messages: list[Any],
    max_file_size: int,
    max_files: int,
) -> None:
    """
    Inspect the **last message** for file/image parts and raise ``ValueError``
    if limits are exceeded.

    Parameters
    ----------
    messages:
        Conversation history (each element is a dict with at least a
        ``"parts"`` key whose value is a list of content parts).
    max_file_size:
        Maximum allowed decoded byte size for a single file.
    max_files:
        Maximum number of file/image parts in the last message.

    Raises
    ------
    ValueError
        When too many files are attached or when any file exceeds the size
        limit.
    """
    if not messages:
        return

    last_message = messages[-1]
    parts: list[Any] = []

    if isinstance(last_message, dict):
        parts = last_message.get("parts", []) or []
    elif hasattr(last_message, "parts"):
        parts = last_message.parts or []

    file_parts = [
        p
        for p in parts
        if isinstance(p, dict) and p.get("type") in ("file", "image")
    ]

    if len(file_parts) > max_files:
        raise ValueError(
            f"Too many files. Maximum {max_files} allowed."
        )

    for part in file_parts:
        # Data URLs: "data:<mime>;base64,<data>"
        data_url: str = part.get("url") or part.get("data") or ""
        if data_url.startswith("data:"):
            try:
                b64_data = data_url.split(",", 1)[1]
            except IndexError:
                b64_data = ""
            if b64_data:
                # Base64 encodes 3 bytes as 4 chars; use ceil for exact upper bound.
                decoded_size = math.ceil(len(b64_data) * 3 / 4)
                if decoded_size > max_file_size:
                    mb = max_file_size / (1024 * 1024)
                    raise ValueError(
                        f"File exceeds {mb:.0f}MB limit."
                    )


# ---------------------------------------------------------------------------
# Historical tool-input replacement
# ---------------------------------------------------------------------------


def replace_historical_tool_inputs(messages: list[Any]) -> list[Any]:
    """
    Replace ``display_diagram`` and ``edit_diagram`` tool inputs in history
    with a lightweight placeholder.

    This keeps long conversations token-efficient by discarding large XML
    payloads that are no longer the authoritative canvas state.  The current
    diagram XML is always injected via the system context instead.

    Tool calls with missing/invalid inputs are filtered out entirely (they
    arise from interrupted streaming and confuse some APIs).

    Operates on litellm-format messages (dicts with ``"role"`` and
    ``"content"`` keys where content may be a list of parts).
    """
    if not messages:
        return messages

    result: list[Any] = []

    for message in messages:
        if not isinstance(message, dict):
            result.append(message)
            continue

        if message.get("role") != "assistant":
            result.append(message)
            continue

        content = message.get("content")
        if not isinstance(content, list):
            result.append(message)
            continue

        new_content = []
        for part in content:
            if not isinstance(part, dict) or part.get("type") != "tool-call":
                new_content.append(part)
                continue

            tool_name = part.get("toolName") or part.get("name") or ""
            tool_input = part.get("input")

            # Drop tool calls with missing/invalid inputs (interrupted streaming).
            if (
                not tool_input
                or not isinstance(tool_input, dict)
                or len(tool_input) == 0
            ):
                continue

            if tool_name in ("display_diagram", "edit_diagram", "append_diagram"):
                new_content.append(
                    {
                        **part,
                        "input": {
                            "placeholder": _XML_PLACEHOLDER,
                        },
                    }
                )
            else:
                new_content.append(part)

        # Keep the message only if it still has content parts.
        if new_content:
            result.append({**message, "content": new_content})

    return result


# ---------------------------------------------------------------------------
# Minimal diagram detection
# ---------------------------------------------------------------------------

_ID2_RE = re.compile(r'id=["\']2["\']')


def is_minimal_diagram(xml: str) -> bool:
    """
    Return True when *xml* represents an effectively empty draw.io canvas.

    A diagram is considered minimal when it contains no cell with ``id="2"``
    (the first user-added element).  Whitespace is irrelevant to the check.
    """
    if not xml:
        return True
    stripped = xml.replace(" ", "").replace("\t", "").replace("\n", "")
    return not bool(_ID2_RE.search(stripped))
