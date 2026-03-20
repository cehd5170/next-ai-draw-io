"""
VLM-based diagram validation service.

Sends a rendered diagram screenshot (base64 PNG data URL) to the configured
vision-language model and returns a structured :class:`ValidationResult`.

Behaviour
---------
- If ``ENABLE_VLM_VALIDATION`` is False the service returns a default
  valid result without making any network call.
- If the VLM call fails for any reason (network error, timeout, parse
  failure) the service *also* returns a valid result ("fail-open"), but
  logs a warning so the issue is visible.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from app.config import Settings
from app.models.validate_diagram import ValidationIssue, ValidationResult
from app.prompts.validation import VALIDATION_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

# Safe default returned whenever validation cannot produce a result.
_DEFAULT_VALID = ValidationResult(valid=True, issues=[], suggestions=[])


class ValidationService:
    """Wraps the litellm call for diagram image validation."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def validate_diagram(
        self,
        image_data: str,
        session_id: Optional[str] = None,
    ) -> ValidationResult:
        """
        Validate *image_data* (a base64 PNG data URL) with the configured VLM.

        Parameters
        ----------
        image_data:
            A ``data:image/png;base64,...`` string produced by the frontend
            after rendering the diagram.
        session_id:
            Optional session identifier for observability / logging.

        Returns
        -------
        ValidationResult
            Structured result.  Always returns a *valid* result on error
            (fail-open).
        """
        if not self.settings.ENABLE_VLM_VALIDATION:
            logger.debug("VLM validation disabled; returning default valid result")
            return _DEFAULT_VALID

        if not image_data or not image_data.strip():
            logger.debug("Empty image_data; skipping VLM validation")
            return _DEFAULT_VALID

        try:
            return await self._call_vlm(image_data, session_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "VLM validation failed (fail-open) [session=%s]: %s",
                session_id,
                exc,
                exc_info=True,
            )
            return _DEFAULT_VALID

    def format_validation_feedback(self, result: ValidationResult) -> str:
        """
        Format a :class:`ValidationResult` as human-readable feedback text.

        Returns an empty string when the diagram is valid and has no issues,
        so the caller can cheaply check ``if feedback:`` before injecting it
        into the conversation.
        """
        if result.valid and not result.issues and not result.suggestions:
            return ""

        lines: list[str] = []

        critical = [i for i in result.issues if i.severity == "critical"]
        warnings = [i for i in result.issues if i.severity == "warning"]

        if critical:
            lines.append("**Critical issues detected in the diagram:**")
            for issue in critical:
                lines.append(f"- [{issue.type}] {issue.description}")

        if warnings:
            lines.append("**Warnings:**")
            for issue in warnings:
                lines.append(f"- [{issue.type}] {issue.description}")

        if result.suggestions:
            lines.append("**Suggestions to improve the diagram:**")
            for suggestion in result.suggestions:
                lines.append(f"- {suggestion}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_validation_model(self) -> str:
        """Return the model ID to use for validation calls."""
        return self.settings.VALIDATION_MODEL or self.settings.AI_MODEL

    async def _call_vlm(
        self,
        image_data: str,
        session_id: Optional[str],
    ) -> ValidationResult:
        """Make the actual litellm VLM call and parse the structured response."""
        import asyncio  # noqa: PLC0415

        try:
            import litellm  # type: ignore[import]  # noqa: PLC0415
        except ImportError as exc:
            raise RuntimeError(
                "litellm is required for VLM validation. "
                "Install it with: pip install litellm"
            ) from exc

        model_id = self._get_validation_model()

        messages = [
            {"role": "system", "content": VALIDATION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": image_data},
                    },
                    {
                        "type": "text",
                        "text": (
                            "Please analyse this rendered diagram for visual quality issues. "
                            "Return a JSON object with keys: "
                            "valid (bool), issues (list of {type, severity, description}), "
                            "suggestions (list of strings)."
                        ),
                    },
                ],
            },
        ]

        call_kwargs: dict = {
            "model": model_id,
            "messages": messages,
            "max_tokens": self.settings.VALIDATION_MAX_OUTPUT_TOKENS,
            "response_format": {"type": "json_object"},
        }

        # Propagate API credentials from settings when available.
        if self.settings.ANTHROPIC_API_KEY:
            call_kwargs["api_key"] = self.settings.ANTHROPIC_API_KEY
        elif self.settings.OPENAI_API_KEY:
            call_kwargs["api_key"] = self.settings.OPENAI_API_KEY

        response = await asyncio.wait_for(
            litellm.acompletion(**call_kwargs),  # type: ignore[attr-defined]
            timeout=self.settings.VALIDATION_TIMEOUT_SECONDS,
        )

        raw_content: str = (
            response.choices[0].message.content or "{}"  # type: ignore[index]
        )

        return self._parse_response(raw_content)

    @staticmethod
    def _parse_response(raw: str) -> ValidationResult:
        """
        Parse a raw JSON string from the VLM into a :class:`ValidationResult`.

        Falls back to a default valid result if JSON is malformed or has
        unexpected structure.
        """
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(
                "VLM returned non-JSON response (first 200 chars): %.200s", raw
            )
            return _DEFAULT_VALID

        valid = bool(data.get("valid", True))

        issues: list[ValidationIssue] = []
        for raw_issue in data.get("issues", []):
            if not isinstance(raw_issue, dict):
                continue
            try:
                issues.append(
                    ValidationIssue(
                        type=str(raw_issue.get("type", "rendering")),
                        severity=str(raw_issue.get("severity", "warning")),
                        description=str(raw_issue.get("description", "")),
                    )
                )
            except Exception:  # noqa: BLE001
                continue

        suggestions: list[str] = [
            str(s) for s in data.get("suggestions", []) if s
        ]

        return ValidationResult(valid=valid, issues=issues, suggestions=suggestions)
