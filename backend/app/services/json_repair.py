"""
JSON repair utilities for truncated LLM tool-call arguments.

Ported from the repair logic in app/api/chat/route.ts (jsonrepair usage)
and adapted for the Python backend using the ``json-repair`` library.
"""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pre-processing patterns
# ---------------------------------------------------------------------------

# Fix common LLM mistakes: `:=` used instead of `: ` in JSON-like output.
_COLON_EQUALS_RE = re.compile(r":=")
# Fix `= "` used instead of `: "` (assignment syntax leaking into JSON).
_EQUALS_QUOTE_RE = re.compile(r'= "')

# Regex to detect JSON key-value pairs whose values look like XML content
# (used by _fix_unescaped_quotes_in_xml_strings below).
_XML_VALUE_RE = re.compile(
    r'(":\s*")(<[^"]*(?:"[^"]*"[^"]*)*)',
    re.DOTALL,
)


def _fix_unescaped_quotes_in_xml_strings(raw: str) -> str:
    """
    Escape double-quotes that appear *inside* JSON string values.

    This is a best-effort heuristic for the common case where an LLM emits
    XML attribute syntax (``attr="value"``) inside a JSON string field
    without escaping the inner quotes.  Only string values that begin with
    ``<`` (i.e. look like XML fragments) are processed.
    """
    def _escape_inner(m: re.Match) -> str:
        # group(1) is the JSON key-colon-quote prefix; group(2) is the XML content.
        prefix = m.group(1)
        xml_part = m.group(2)
        # Escape any unescaped " inside the XML content.
        escaped = re.sub(r'(?<!\\)"', '\\"', xml_part)
        return prefix + escaped

    return _XML_VALUE_RE.sub(_escape_inner, raw)


def repair_tool_call_json(raw: str) -> dict | None:
    """
    Attempt to parse and repair truncated / malformed JSON from an LLM tool call.

    Processing steps:
    1. Pre-process: fix ``:=`` → ``: `` and ``= "`` → ``: "`` patterns.
    2. Fix unescaped quotes inside XML-like string values.
    3. Try ``json.loads`` directly (fast path for valid JSON).
    4. If that fails, delegate to the ``json_repair`` library.
    5. Return ``None`` if all repair attempts fail.

    Returns the parsed dict on success, or None on failure.
    """
    if not raw or not raw.strip():
        return None

    # Step 1: pre-process common syntactic mistakes.
    processed = _COLON_EQUALS_RE.sub(": ", raw)
    processed = _EQUALS_QUOTE_RE.sub(': "', processed)

    # Step 2: fix unescaped quotes in XML string values.
    processed = _fix_unescaped_quotes_in_xml_strings(processed)

    # Step 3: fast path.
    try:
        result = json.loads(processed)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # Step 4: use json_repair library.
    try:
        from json_repair import repair_json  # noqa: PLC0415 (lazy import)

        repaired_str = repair_json(processed)
        if repaired_str:
            result = json.loads(repaired_str)
            if isinstance(result, dict):
                return result
    except Exception as exc:  # noqa: BLE001
        logger.warning("json_repair failed: %s", exc)

    logger.warning("repair_tool_call_json: all repair attempts failed for input (first 200 chars): %.200s", raw)
    return None


# ---------------------------------------------------------------------------
# Fallback tool inputs
# ---------------------------------------------------------------------------

_FALLBACK_INPUTS: dict[str, dict] = {
    "display_diagram": {"xml": ""},
    "edit_diagram": {"operations": []},
    "append_diagram": {"xml": ""},
    "get_shape_library": {"library": "flowchart"},
}


def get_fallback_tool_input(tool_name: str) -> dict:
    """
    Return a safe, schema-valid fallback input for a known tool.

    Used when JSON repair completely fails so that the orchestrator can
    still produce a well-formed tool result (even if empty/no-op) rather
    than crashing.
    """
    return dict(_FALLBACK_INPUTS.get(tool_name, {}))
