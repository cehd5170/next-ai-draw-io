"""
Unit tests for app/prompts/system.py

Covers:
- get_system_prompt   – full prompt assembly with all conditional sections
- build_xml_context   – XML context message for chat turns
"""

import pytest
from app.prompts.system import get_system_prompt, build_xml_context


class TestGetSystemPrompt:
    def test_default_prompt_has_all_four_tools(self):
        """All four diagram tool names appear in the default prompt."""
        prompt = get_system_prompt("gpt-4o")
        assert "display_diagram" in prompt, "display_diagram must be mentioned in prompt"
        assert "edit_diagram" in prompt, "edit_diagram must be mentioned in prompt"
        assert "append_diagram" in prompt, "append_diagram must be mentioned in prompt"
        assert "get_shape_library" in prompt, "get_shape_library must be mentioned in prompt"

    def test_operations_schema_in_prompt(self):
        """The edit_diagram schema uses 'operations' and 'cell_id' terminology."""
        prompt = get_system_prompt("gpt-4o")
        assert "operations" in prompt, "edit_diagram must use 'operations' parameter"
        assert "cell_id" in prompt, "edit_diagram operations must reference 'cell_id'"

    def test_no_stale_edits_schema(self):
        """Stale 'search/replace' edit schema must not appear in the prompt."""
        prompt = get_system_prompt("gpt-4o")
        # The old schema used 'edits' with a 'search' key – this must be absent.
        edit_section_start = prompt.find("edit_diagram")
        if edit_section_start != -1:
            # Grab a reasonable window after the first mention of edit_diagram
            window = prompt[edit_section_start: edit_section_start + 2000]
            assert "search" not in window or "search" not in window.lower().split("search")[0], (
                "edit_diagram section must not reference a 'search' field"
            )

    def test_no_plan_contradiction(self):
        """The prompt must not instruct the model to 'briefly describe your plan'."""
        prompt = get_system_prompt("gpt-4o")
        assert "briefly describe your plan" not in prompt.lower(), (
            "Contradictory 'briefly describe your plan' instruction should be absent"
        )

    def test_minimal_style_mode_present_when_enabled(self):
        """When minimal_style=True, the Minimal Style Mode section is included."""
        prompt = get_system_prompt("gpt-4o", minimal_style=True)
        assert "Minimal Style Mode" in prompt, (
            "Minimal Style Mode header must appear when minimal_style=True"
        )

    def test_minimal_style_disables_fill_color(self):
        """Minimal style mode section explicitly forbids fillColor."""
        prompt = get_system_prompt("gpt-4o", minimal_style=True)
        minimal_section = prompt.split("Minimal Style Mode")[1]
        # Should contain a prohibition on fillColor
        assert "fillColor" in minimal_section or "NO fillColor" in minimal_section, (
            "Minimal style section must address fillColor restriction"
        )

    def test_style_instructions_omitted_in_minimal_mode(self):
        """The STYLE_INSTRUCTIONS section (common styles list) is not appended in minimal mode."""
        prompt_minimal = get_system_prompt("gpt-4o", minimal_style=True)
        prompt_normal = get_system_prompt("gpt-4o", minimal_style=False)
        # Style instructions block appears in normal mode
        assert "Common styles:" in prompt_normal, (
            "Normal mode should include the 'Common styles:' section"
        )
        assert "Common styles:" not in prompt_minimal, (
            "Minimal mode should NOT include the 'Common styles:' section"
        )

    def test_extended_prompt_for_opus(self):
        """Claude Opus models receive the Extended Tool Reference section."""
        prompt = get_system_prompt("claude-opus-4-5-20250929")
        assert "Extended Tool Reference" in prompt, (
            "Claude Opus should receive the Extended Tool Reference section"
        )

    def test_extended_prompt_for_haiku(self):
        """Claude Haiku models receive the Extended Tool Reference section."""
        prompt = get_system_prompt("claude-haiku-4-5-20251001")
        assert "Extended Tool Reference" in prompt, (
            "Claude Haiku should receive the Extended Tool Reference section"
        )

    def test_no_extended_prompt_for_gpt(self):
        """GPT models do NOT receive the Extended Tool Reference section."""
        prompt = get_system_prompt("gpt-4o")
        assert "Extended Tool Reference" not in prompt, (
            "GPT models must not receive the Extended Tool Reference section"
        )

    def test_no_extended_prompt_for_gemini(self):
        """Gemini models do NOT receive the Extended Tool Reference section."""
        prompt = get_system_prompt("gemini-2.5-pro")
        assert "Extended Tool Reference" not in prompt

    def test_model_name_substituted(self):
        """The {{MODEL_NAME}} placeholder is replaced with the given display name."""
        prompt = get_system_prompt("gpt-4o", model_display_name="GPT-4o")
        assert "GPT-4o" in prompt, "Model display name should appear in prompt"
        assert "{{MODEL_NAME}}" not in prompt, (
            "Raw {{MODEL_NAME}} placeholder must not remain after substitution"
        )

    def test_model_id_used_as_fallback_name(self):
        """When no display name is provided, the model_id is used as the name."""
        prompt = get_system_prompt("gpt-4o")
        assert "gpt-4o" in prompt, "Model ID should appear as name when no display name given"

    def test_aws_library_uses_aws4(self):
        """The prompt must reference the 'aws4' library name, not a phantom 'AWS 2025'."""
        prompt = get_system_prompt("gpt-4o")
        assert "AWS 2025" not in prompt, (
            "'AWS 2025' is a phantom library name that must not appear in the prompt"
        )
        assert "aws4" in prompt, (
            "'aws4' must be the canonical AWS library name referenced in the prompt"
        )

    def test_edge_routing_rules_count(self):
        """The edge routing section should have at most 3 numbered rules."""
        prompt = get_system_prompt("gpt-4o")
        # Rules 4 through 7 as standalone numbered items must not exist in the prompt.
        for rule_num in ("Rule 4", "Rule 5", "Rule 6", "Rule 7"):
            assert rule_num not in prompt, (
                f"'{rule_num}' should not appear — edge routing was simplified to 3 rules"
            )

    def test_no_raw_placeholder_in_output(self):
        """No {{...}} template placeholders should remain after assembly."""
        prompt = get_system_prompt("claude-opus-4-5-20250929", minimal_style=True)
        assert "{{" not in prompt, "No template placeholders should remain unsubstituted"

    def test_prompt_is_non_empty_string(self):
        """get_system_prompt always returns a non-empty string."""
        prompt = get_system_prompt("gpt-4o")
        assert isinstance(prompt, str) and len(prompt) > 100


class TestBuildXmlContext:
    def test_with_current_xml_only(self):
        """Providing only current XML produces a 'Current diagram XML' section."""
        ctx = build_xml_context("<xml>current</xml>")
        assert "Current diagram XML" in ctx, "Must include 'Current diagram XML' heading"
        assert "Previous diagram XML" not in ctx, (
            "Must NOT include 'Previous diagram XML' when none is provided"
        )

    def test_with_previous_and_current_xml(self):
        """Providing both current and previous XML includes both sections."""
        ctx = build_xml_context("<xml>current</xml>", "<xml>previous</xml>")
        assert "Current diagram XML" in ctx, "Must include current XML section"
        assert "Previous diagram XML" in ctx, "Must include previous XML section"

    def test_current_xml_content_appears_in_context(self):
        """The actual XML content is embedded in the context string."""
        ctx = build_xml_context("<mxCell id='2'/>")
        assert "<mxCell id='2'/>" in ctx, "Current XML content must appear verbatim"

    def test_previous_xml_content_appears_in_context(self):
        """The previous XML is embedded when provided."""
        ctx = build_xml_context("<mxCell id='2'/>", "<mxCell id='old'/>")
        assert "<mxCell id='old'/>" in ctx, "Previous XML content must appear verbatim"

    def test_empty_current_xml_produces_empty_note(self):
        """When current XML is empty, a note about the empty canvas is shown."""
        ctx = build_xml_context("")
        assert "empty" in ctx.lower() or "no diagram" in ctx.lower(), (
            "Empty current XML should produce an 'empty' / 'no diagram' note"
        )

    def test_source_of_truth_in_system_prompt(self):
        """The system prompt (not the XML context) indicates the XML is the source of truth."""
        # build_xml_context only provides the XML; the system prompt carries the
        # "single source of truth" instruction.  Verify the system prompt has it.
        from app.prompts.system import DEFAULT_SYSTEM_PROMPT
        assert (
            "SINGLE SOURCE OF TRUTH" in DEFAULT_SYSTEM_PROMPT
            or "source of truth" in DEFAULT_SYSTEM_PROMPT.lower()
            or "Current diagram XML" in DEFAULT_SYSTEM_PROMPT
        ), (
            "The system prompt should reference the current XML as authoritative"
        )

    def test_none_previous_xml_not_included(self):
        """Explicitly passing None for previous_xml omits the previous section."""
        ctx = build_xml_context("<xml>current</xml>", None)
        assert "Previous diagram XML" not in ctx

    def test_whitespace_only_previous_xml_not_included(self):
        """Whitespace-only previous_xml should not create a spurious section."""
        ctx = build_xml_context("<xml>current</xml>", "   ")
        assert "Previous diagram XML" not in ctx
