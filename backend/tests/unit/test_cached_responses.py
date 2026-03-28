from app.services.cached_responses import find_cached_response


class TestFindCachedResponse:
    def test_matches_exact_demo_prompt(self):
        """Known example prompts should still hit the cache."""
        xml = find_cached_response(
            "Give me a **animated connector** diagram of transformer's architecture",
            False,
        )
        assert xml is not None

    def test_normalizes_markdown_and_trailing_punctuation(self):
        """Minor formatting differences should still match the demo cache."""
        xml = find_cached_response(
            "  Give me a animated connector diagram of transformer's architecture.  ",
            False,
        )
        assert xml is not None

    def test_does_not_match_broad_substrings_anymore(self):
        """Generic topic mentions should not accidentally trigger demo XML."""
        xml = find_cached_response(
            "Explain transformer architecture tradeoffs for retrieval systems",
            False,
        )
        assert xml is None
