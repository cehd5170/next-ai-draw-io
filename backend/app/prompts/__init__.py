"""
Prompts package for the AI diagram assistant backend.

Public API:
    get_system_prompt        - Build the full system prompt for a given model and style preference.
    build_xml_context        - Build the XML context system message injected each chat turn.
    should_use_extended_prompt - Return True for models that need the extended (4 000-token) prompt.
    VALIDATION_SYSTEM_PROMPT - System prompt for the VLM-based diagram quality validator.
    TOOL_SCHEMAS             - JSON Schema definitions for all four diagram tools.
    SHAPE_LIBRARY_NAMES      - List of supported shape/icon library names.
"""

from app.prompts.system import (
    get_system_prompt,
    build_xml_context,
    should_use_extended_prompt,
    DEFAULT_SYSTEM_PROMPT,
    EXTENDED_ADDITIONS,
    MINIMAL_STYLE_INSTRUCTION,
    STYLE_INSTRUCTIONS,
)
from app.prompts.validation import VALIDATION_SYSTEM_PROMPT
from app.prompts.constants import TOOL_SCHEMAS, SHAPE_LIBRARY_NAMES

__all__ = [
    "get_system_prompt",
    "build_xml_context",
    "should_use_extended_prompt",
    "DEFAULT_SYSTEM_PROMPT",
    "EXTENDED_ADDITIONS",
    "MINIMAL_STYLE_INSTRUCTION",
    "STYLE_INSTRUCTIONS",
    "VALIDATION_SYSTEM_PROMPT",
    "TOOL_SCHEMAS",
    "SHAPE_LIBRARY_NAMES",
]
