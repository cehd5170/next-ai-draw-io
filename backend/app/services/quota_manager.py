"""
DynamoDB-backed per-user quota manager.

Ported from lib/dynamo-quota-manager.ts.

Tracks three limits per user per day (composite PK=user, SK=date):
- ``reqCount``   – daily request count
- ``tokenCount`` – daily token count
- ``tpmCount``   – tokens-per-minute rate (reset when minute changes)

All quota tracking is opt-in — it is only active when
``settings.DYNAMODB_QUOTA_TABLE`` is set.  Every public method that
interacts with DynamoDB is wrapped to *fail open* so that DynamoDB errors
never block users.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from app.config import Settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Token usage dataclass
# ---------------------------------------------------------------------------


@dataclass
class TokenUsage:
    """Token counts from a completed LLM response."""

    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens


# ---------------------------------------------------------------------------
# QuotaManager
# ---------------------------------------------------------------------------


class QuotaManager:
    """Async-friendly DynamoDB quota manager."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.table_name: Optional[str] = settings.DYNAMODB_QUOTA_TABLE
        self._boto_client: Optional[object] = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def check_and_increment(
        self, user_id: str
    ) -> tuple[bool, Optional[str]]:
        """
        Atomically check all quotas and increment the request counter.

        Returns ``(True, None)`` when the request is allowed, or
        ``(False, "<reason>")`` when a limit is exceeded.

        On any DynamoDB error the method fails open (returns ``True``).
        """
        if not self.settings.quota_enabled:
            return (True, None)

        if not user_id or user_id == "anonymous":
            return (True, None)

        try:
            return await self._do_check_and_increment(user_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Quota check failed (fail-open) for user %s: %s",
                user_id[:8] + "...",
                exc,
            )
            return (True, None)

    async def record_token_usage(
        self, user_id: str, usage: TokenUsage
    ) -> None:
        """
        Record token usage after a successful LLM response.

        Uses a two-phase update:
        1.  Try to update assuming the current minute matches ``lastMinute``
            (or that the item is new).
        2.  On ``ConditionalCheckFailedException`` (different minute), reset
            ``tpmCount`` for the new minute.

        Errors are logged but never raised.
        """
        if not self.settings.quota_enabled:
            return
        if not user_id or user_id == "anonymous":
            return

        tokens = usage.total
        if not math.isfinite(tokens) or tokens <= 0:
            return

        try:
            await self._do_record_tokens(user_id, tokens)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Token usage recording failed for user %s: %s",
                user_id[:8] + "...",
                exc,
            )

    # ------------------------------------------------------------------
    # Internal DynamoDB helpers
    # ------------------------------------------------------------------

    def _get_client(self) -> object:
        """Lazily initialise and cache the boto3 DynamoDB *client*."""
        if self._boto_client is None:
            try:
                import boto3  # type: ignore[import]  # noqa: PLC0415
            except ImportError as exc:
                raise RuntimeError(
                    "boto3 is required for quota management. "
                    "Install it with: pip install boto3"
                ) from exc
            self._boto_client = boto3.client(
                "dynamodb",
                region_name=self.settings.DYNAMODB_REGION,
            )
        return self._boto_client

    def _get_today(self) -> str:
        """Return today's date as ``YYYY-MM-DD`` in the configured timezone."""
        try:
            from zoneinfo import ZoneInfo  # noqa: PLC0415 (Python 3.9+)
            tz = ZoneInfo(self.settings.QUOTA_TIMEZONE)
        except Exception:  # noqa: BLE001
            tz = timezone.utc
        return datetime.now(tz).strftime("%Y-%m-%d")

    @staticmethod
    def _current_minute() -> str:
        """Return the current Unix minute as a string (floor of epoch / 60)."""
        return str(math.floor(datetime.now(timezone.utc).timestamp() / 60))

    async def _do_check_and_increment(
        self, user_id: str
    ) -> tuple[bool, Optional[str]]:
        """
        Perform the atomic DynamoDB check-and-increment.

        Uses a single ``UpdateItem`` with a ``ConditionExpression`` that
        enforces all three limits simultaneously.  On
        ``ConditionalCheckFailedException`` a ``GetItem`` is issued to
        determine which specific limit was hit.
        """
        import asyncio  # noqa: PLC0415

        client = self._get_client()  # type: ignore[attr-defined]
        table = self.table_name

        pk = user_id
        sk = self._get_today()
        current_minute = self._current_minute()

        req_limit = self.settings.DAILY_REQUEST_LIMIT
        token_limit = self.settings.DAILY_TOKEN_LIMIT
        tpm_limit = self.settings.TPM_LIMIT

        try:
            await asyncio.get_event_loop().run_in_executor(  # type: ignore[attr-defined]
                None,
                lambda: client.update_item(  # type: ignore[attr-defined]
                    TableName=table,
                    Key={
                        "PK": {"S": pk},
                        "SK": {"S": sk},
                    },
                    UpdateExpression="ADD reqCount :one",
                    ConditionExpression=(
                        "(attribute_not_exists(reqCount) OR reqCount < :reqLimit) AND "
                        "(attribute_not_exists(tokenCount) OR tokenCount < :tokenLimit) AND "
                        "(attribute_not_exists(lastMinute) OR lastMinute <> :minute OR "
                        " attribute_not_exists(tpmCount) OR tpmCount < :tpmLimit)"
                    ),
                    ExpressionAttributeValues={
                        ":one":        {"N": "1"},
                        ":minute":     {"S": current_minute},
                        ":reqLimit":   {"N": str(req_limit or 999_999)},
                        ":tokenLimit": {"N": str(token_limit or 999_999)},
                        ":tpmLimit":   {"N": str(tpm_limit or 999_999)},
                    },
                ),
            )
            return (True, None)

        except Exception as exc:  # noqa: BLE001
            exc_name = type(exc).__name__
            if "ConditionalCheckFailed" not in exc_name:
                # Unexpected error — fail open.
                logger.warning(
                    "DynamoDB error during quota check (fail-open): %s", exc
                )
                return (True, None)

        # Condition failed — inspect current counts to return a useful message.
        try:
            get_resp = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: client.get_item(  # type: ignore[attr-defined]
                    TableName=table,
                    Key={
                        "PK": {"S": pk},
                        "SK": {"S": sk},
                    },
                ),
            )
            item = get_resp.get("Item", {})
            stored_minute = item.get("lastMinute", {}).get("S", "")
            req_count   = int(item.get("reqCount",   {}).get("N", 0))
            token_count = int(item.get("tokenCount", {}).get("N", 0))
            tpm_count   = int(item.get("tpmCount",   {}).get("N", 0)) \
                if stored_minute == current_minute else 0

            if req_limit > 0 and req_count >= req_limit:
                return (False, "Daily request limit exceeded")
            if token_limit > 0 and token_count >= token_limit:
                return (False, "Daily token limit exceeded")
            if tpm_limit > 0 and tpm_count >= tpm_limit:
                return (False, "Rate limit exceeded (tokens per minute)")

            # Edge case: condition failed but no limit clearly exceeded (race).
            logger.warning(
                "Quota condition failed but no limit exceeded for user %s",
                user_id[:8] + "...",
            )
            return (True, None)

        except Exception as exc2:  # noqa: BLE001
            logger.error(
                "Failed to retrieve quota details after condition failure: %s", exc2
            )
            return (True, None)

    async def _do_record_tokens(self, user_id: str, tokens: int) -> None:
        """
        Two-phase DynamoDB token usage update.

        Phase 1:  ADD tokens to ``tokenCount`` and ``tpmCount`` under the
                  condition that ``lastMinute`` is absent or equals the
                  current minute.
        Phase 2:  On ``ConditionalCheckFailed`` (different minute), SET
                  ``lastMinute`` and reset ``tpmCount`` to *tokens* while
                  still adding to the cumulative ``tokenCount``.
        """
        import asyncio  # noqa: PLC0415

        client = self._get_client()  # type: ignore[attr-defined]
        table = self.table_name

        pk = user_id
        sk = self._get_today()
        current_minute = self._current_minute()

        # Phase 1: same-minute update.
        try:
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: client.update_item(  # type: ignore[attr-defined]
                    TableName=table,
                    Key={
                        "PK": {"S": pk},
                        "SK": {"S": sk},
                    },
                    UpdateExpression=(
                        "SET lastMinute = if_not_exists(lastMinute, :minute) "
                        "ADD tokenCount :tokens, tpmCount :tokens"
                    ),
                    ConditionExpression=(
                        "attribute_not_exists(lastMinute) OR lastMinute = :minute"
                    ),
                    ExpressionAttributeValues={
                        ":minute": {"S": current_minute},
                        ":tokens": {"N": str(tokens)},
                    },
                ),
            )
            return
        except Exception as exc:  # noqa: BLE001
            if "ConditionalCheckFailed" not in type(exc).__name__:
                logger.warning("Token recording phase-1 error: %s", exc)
                return

        # Phase 2: minute has rolled over — reset tpmCount.
        try:
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: client.update_item(  # type: ignore[attr-defined]
                    TableName=table,
                    Key={
                        "PK": {"S": pk},
                        "SK": {"S": sk},
                    },
                    UpdateExpression=(
                        "SET lastMinute = :minute, tpmCount = :tokens "
                        "ADD tokenCount :tokens"
                    ),
                    ExpressionAttributeValues={
                        ":minute": {"S": current_minute},
                        ":tokens": {"N": str(tokens)},
                    },
                ),
            )
        except Exception as exc2:  # noqa: BLE001
            logger.warning("Token recording phase-2 error: %s", exc2)
