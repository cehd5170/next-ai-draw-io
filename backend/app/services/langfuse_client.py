"""
Langfuse observability wrapper.

Ported from lib/langfuse.ts.  Provides a thin facade over the Langfuse
Python SDK so that callers never need to guard against missing credentials
— every method is a no-op when Langfuse is not configured.
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from app.config import Settings

logger = logging.getLogger(__name__)


def _iso_now() -> str:
    from datetime import datetime, timezone  # noqa: PLC0415

    return datetime.now(timezone.utc).isoformat()


class LangfuseWrapper:
    """
    Facade over the Langfuse Python SDK.

    Instantiation is safe even when the ``langfuse`` package is not
    installed or credentials are absent — all methods become no-ops in
    that case.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.enabled: bool = bool(
            settings.LANGFUSE_PUBLIC_KEY and settings.LANGFUSE_SECRET_KEY
        )
        self.client: Optional[object] = None

        if self.enabled:
            try:
                from langfuse import Langfuse  # type: ignore[import]  # noqa: PLC0415

                self.client = Langfuse(
                    public_key=settings.LANGFUSE_PUBLIC_KEY,
                    secret_key=settings.LANGFUSE_SECRET_KEY,
                    host=settings.LANGFUSE_BASEURL or "https://cloud.langfuse.com",
                )
                logger.info("Langfuse client initialised (host=%s)", settings.LANGFUSE_BASEURL)
            except ImportError:
                logger.warning(
                    "langfuse package not installed — observability disabled"
                )
                self.enabled = False
            except Exception as exc:  # noqa: BLE001
                logger.warning("Langfuse initialisation failed: %s", exc)
                self.enabled = False

    # ------------------------------------------------------------------
    # Core tracing
    # ------------------------------------------------------------------

    def trace(
        self,
        name: str,
        session_id: Optional[str],
        user_id: Optional[str],
        input: Optional[str],   # noqa: A002
        output: Optional[str],
        metadata: Optional[dict] = None,
    ) -> Optional[str]:
        """
        Create a Langfuse trace.

        Returns the trace ID on success, or ``None`` when Langfuse is
        disabled or the call fails.
        """
        if not self.enabled or self.client is None:
            return None

        try:
            lf = self.client  # type: ignore[attr-defined]
            trace_id = str(uuid.uuid4())
            now = _iso_now()

            lf.api.ingestion.batch(
                batch=[
                    {
                        "type": "trace-create",
                        "id": str(uuid.uuid4()),
                        "timestamp": now,
                        "body": {
                            "id": trace_id,
                            "name": name,
                            "sessionId": session_id,
                            "userId": user_id,
                            "input": input,
                            "output": output,
                            "metadata": metadata or {},
                            "timestamp": now,
                        },
                    }
                ]
            )
            return trace_id
        except Exception as exc:  # noqa: BLE001
            logger.warning("Langfuse trace() failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def score(
        self,
        trace_id: str,
        name: str,
        value: float,
        comment: Optional[str] = None,
    ) -> None:
        """
        Add a numeric score to an existing trace.

        Parameters
        ----------
        trace_id:
            Langfuse trace ID (as returned by :meth:`trace`).
        name:
            Score name, e.g. ``"user-feedback"``.
        value:
            Numeric score value (e.g. 0 / 1 for binary feedback).
        comment:
            Optional human-readable explanation.
        """
        if not self.enabled or self.client is None:
            return

        try:
            lf = self.client  # type: ignore[attr-defined]
            now = _iso_now()
            lf.api.ingestion.batch(
                batch=[
                    {
                        "type": "score-create",
                        "id": str(uuid.uuid4()),
                        "timestamp": now,
                        "body": {
                            "id": str(uuid.uuid4()),
                            "traceId": trace_id,
                            "name": name,
                            "value": value,
                            "comment": comment,
                        },
                    }
                ]
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Langfuse score() failed: %s", exc)

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def log_save(
        self,
        session_id: Optional[str],
        filename: str,
        format: str,  # noqa: A002
    ) -> None:
        """
        Log a diagram-save event by attaching a score to the most recent
        trace for *session_id*.

        Parameters
        ----------
        session_id:
            Client session identifier.
        filename:
            Saved filename (without extension).
        format:
            File format string, e.g. ``"png"`` or ``"pptx"``.
        """
        if not self.enabled or self.client is None or not session_id:
            return

        try:
            lf = self.client  # type: ignore[attr-defined]
            traces_resp = lf.api.trace.list(sessionId=session_id, limit=1)
            traces = getattr(traces_resp, "data", []) or []
            trace = traces[0] if traces else None

            if not trace:
                return

            now = _iso_now()
            lf.api.ingestion.batch(
                batch=[
                    {
                        "type": "score-create",
                        "id": str(uuid.uuid4()),
                        "timestamp": now,
                        "body": {
                            "id": str(uuid.uuid4()),
                            "traceId": trace.id,
                            "name": "diagram-saved",
                            "value": 1,
                            "comment": f"User saved diagram as {filename}.{format}",
                        },
                    }
                ]
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Langfuse log_save() failed: %s", exc)

    def feedback_score(
        self,
        *,
        message_id: str,
        feedback: str,
        session_id: Optional[str],
        user_id: Optional[str] = None,
    ) -> None:
        """
        Record a user thumbs-up / thumbs-down feedback score.

        Attaches the score to the most recent trace for *session_id*.
        Creates a standalone trace if none is found.

        Parameters
        ----------
        message_id:
            Client message identifier.
        feedback:
            ``"good"`` or ``"bad"``.
        session_id:
            Client session identifier.
        user_id:
            Optional user identifier.
        """
        if not self.enabled or self.client is None:
            return

        try:
            lf = self.client  # type: ignore[attr-defined]
            score_value: float = 1.0 if feedback == "good" else 0.0
            now = _iso_now()

            if not session_id:
                return

            traces_resp = lf.api.trace.list(sessionId=session_id, limit=1)
            traces = getattr(traces_resp, "data", []) or []
            trace = traces[0] if traces else None

            if trace:
                lf.api.ingestion.batch(
                    batch=[
                        {
                            "type": "score-create",
                            "id": str(uuid.uuid4()),
                            "timestamp": now,
                            "body": {
                                "id": str(uuid.uuid4()),
                                "traceId": trace.id,
                                "name": "user-feedback",
                                "value": score_value,
                                "comment": f"User gave {feedback} feedback",
                            },
                        }
                    ]
                )
            else:
                # No existing trace — create a standalone one.
                trace_id = str(uuid.uuid4())
                lf.api.ingestion.batch(
                    batch=[
                        {
                            "type": "trace-create",
                            "id": str(uuid.uuid4()),
                            "timestamp": now,
                            "body": {
                                "id": trace_id,
                                "name": "user-feedback",
                                "sessionId": session_id,
                                "userId": user_id,
                                "input": {
                                    "messageId": message_id,
                                    "feedback": feedback,
                                },
                                "metadata": {
                                    "source": "feedback-button",
                                    "note": "standalone — no chat trace found",
                                },
                                "timestamp": now,
                            },
                        },
                        {
                            "type": "score-create",
                            "id": str(uuid.uuid4()),
                            "timestamp": now,
                            "body": {
                                "id": str(uuid.uuid4()),
                                "traceId": trace_id,
                                "name": "user-feedback",
                                "value": score_value,
                                "comment": f"User gave {feedback} feedback",
                            },
                        },
                    ]
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Langfuse feedback_score() failed: %s", exc)
