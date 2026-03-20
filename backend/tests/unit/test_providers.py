"""
Unit tests for provider capability helpers in app/providers/factory.py.

Covers:
- supports_image_input     – vision/image capability heuristic
- supports_prompt_caching  – Anthropic-style prompt caching detection
- normalize_minimax_base_url – MiniMax URL normalisation
"""

import pytest
from app.providers.factory import supports_image_input, supports_prompt_caching
from app.providers.helpers import normalize_minimax_base_url


class TestSupportsImageInput:
    def test_claude_supports_vision(self):
        """Claude Sonnet models support image input."""
        assert supports_image_input("claude-sonnet-4-5-20250929") is True

    def test_gpt4o_supports_vision(self):
        """GPT-4o supports image input."""
        assert supports_image_input("gpt-4o") is True

    def test_deepseek_no_vision(self):
        """DeepSeek Chat text model does not support images."""
        assert supports_image_input("deepseek-chat") is False

    def test_deepseek_vl_has_vision(self):
        """DeepSeek VL variant supports image input."""
        assert supports_image_input("deepseek-vl") is True

    def test_qwen_no_vision(self):
        """Qwen Turbo (text-only) does not support images."""
        assert supports_image_input("qwen-turbo") is False

    def test_qwen_vl_has_vision(self):
        """Qwen VL Plus (vision-language) supports image input."""
        assert supports_image_input("qwen-vl-plus") is True

    def test_kimi_k2_no_vision(self):
        """Kimi K2 text model does not support images."""
        assert supports_image_input("kimi-k2") is False

    def test_kimi_k25_has_vision(self):
        """Kimi K2.5 vision variant supports image input."""
        assert supports_image_input("kimi-k2.5") is True

    def test_gemini_supports_vision(self):
        """Gemini models support image input."""
        assert supports_image_input("gemini-2.5-pro") is True

    def test_gpt4_supports_vision(self):
        """GPT-4 supports image input (not a restricted model)."""
        assert supports_image_input("gpt-4") is True

    def test_deepseek_r1_no_vision(self):
        """DeepSeek R1 reasoning model (no vision marker) does not support images."""
        assert supports_image_input("deepseek-r1") is False

    def test_deepseek_vision_variant(self):
        """Model name containing 'vision' is always treated as vision-capable."""
        assert supports_image_input("deepseek-vision-large") is True


class TestSupportsPromptCaching:
    def test_claude_caching(self):
        """Anthropic Claude models support prompt caching."""
        assert supports_prompt_caching("anthropic.claude-sonnet-4-5") is True

    def test_claude_direct_caching(self):
        """Direct 'claude-' prefix models support caching."""
        assert supports_prompt_caching("claude-opus-4-5-20250929") is True

    def test_bedrock_us_prefix_caching(self):
        """Bedrock cross-region 'us.anthropic.*' prefix supports caching."""
        assert supports_prompt_caching("us.anthropic.claude-sonnet-4-5-v1:0") is True

    def test_bedrock_eu_prefix_caching(self):
        """Bedrock cross-region 'eu.anthropic.*' prefix supports caching."""
        assert supports_prompt_caching("eu.anthropic.claude-haiku-4-5-v1:0") is True

    def test_gpt_no_caching(self):
        """GPT-4o does not support Anthropic-style prompt caching."""
        assert supports_prompt_caching("gpt-4o") is False

    def test_gemini_no_caching(self):
        """Gemini models do not support Anthropic-style prompt caching."""
        assert supports_prompt_caching("gemini-2.5-pro") is False

    def test_deepseek_no_caching(self):
        """DeepSeek models do not support Anthropic-style prompt caching."""
        assert supports_prompt_caching("deepseek-chat") is False

    def test_model_with_anthropic_substring(self):
        """Any model ID containing 'anthropic' is treated as caching-capable."""
        assert supports_prompt_caching("bedrock/anthropic.claude-3-5-sonnet") is True


class TestNormalizeMiniMaxBaseUrl:
    def test_anthropic_path_without_version(self):
        """URL with /anthropic path (no /v1) gets /v1 appended."""
        url, is_anthro = normalize_minimax_base_url("https://api.minimaxi.com/anthropic")
        assert url == "https://api.minimaxi.com/anthropic/v1"
        assert is_anthro is True

    def test_anthropic_path_already_versioned(self):
        """URL already ending with /anthropic/v1 is returned unchanged."""
        url, is_anthro = normalize_minimax_base_url("https://api.minimaxi.com/anthropic/v1")
        assert url == "https://api.minimaxi.com/anthropic/v1"
        assert is_anthro is True

    def test_openai_path_base(self):
        """Plain base URL (no /anthropic) gets /v1 appended."""
        url, is_anthro = normalize_minimax_base_url("https://api.minimaxi.com")
        assert url == "https://api.minimaxi.com/v1"
        assert is_anthro is False

    def test_openai_path_already_versioned(self):
        """URL already ending with /v1 (no /anthropic) is returned unchanged."""
        url, is_anthro = normalize_minimax_base_url("https://api.minimaxi.com/v1")
        assert url == "https://api.minimaxi.com/v1"
        assert is_anthro is False

    def test_trailing_slash_stripped(self):
        """Trailing slashes are stripped before the /v1 suffix is added."""
        url, _ = normalize_minimax_base_url("https://api.minimaxi.com/")
        assert url == "https://api.minimaxi.com/v1"

    def test_anthropic_path_trailing_slash(self):
        """Anthropic URL with trailing slash normalises correctly."""
        url, is_anthro = normalize_minimax_base_url("https://api.minimaxi.com/anthropic/")
        assert url == "https://api.minimaxi.com/anthropic/v1"
        assert is_anthro is True

    def test_is_anthropic_flag_false_for_plain_url(self):
        """is_anthropic flag is False when path does not contain /anthropic."""
        _, is_anthro = normalize_minimax_base_url("https://api.minimaxi.com")
        assert is_anthro is False
