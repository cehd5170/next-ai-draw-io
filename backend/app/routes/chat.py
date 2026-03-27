"""
POST /chat — main streaming diagram-assistant endpoint.

Flow
----
1.  Verify access code (if ACCESS_CODE_LIST is configured).
2.  Validate file parts (size, count).
3.  Check per-user quota (if DynamoDB is configured).
4.  Return cached response for trivial first-message / empty-canvas prompts.
5.  Build system prompt (respecting x-minimal-style header).
6.  Build XML context (current + previous diagram).
7.  Optionally replace historical tool-call XML with placeholders.
8.  Resolve AI model config from settings + client-override headers.
9.  Stream the response via ChatService.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.config import Settings
from app.dependencies import get_client_overrides, get_settings, get_user_id
from app.models.chat import ChatRequest, ClientOverrides
from app.prompts import build_xml_context, get_system_prompt
from app.providers.factory import get_ai_model, supports_image_input
from app.services.cached_responses import find_cached_response
from app.services.chat_service import ChatService, _nanoid, _sse, _SSE_DONE
from app.services.file_processing import (
    is_minimal_diagram,
    replace_historical_tool_inputs,
    validate_file_parts,
)
from app.services.message_converter import (
    convert_ui_messages_to_litellm,
    extract_user_text_from_parts,
    has_file_in_parts,
)
from app.services.quota_manager import QuotaManager

router = APIRouter()
logger = logging.getLogger(__name__)
_SHAPE_LIBRARY_DIR = str(
    Path(__file__).resolve().parents[2] / "docs" / "shape-libraries"
)

# Singleton services — created once at module load, reused across requests.
_quota_manager: QuotaManager | None = None
_chat_service: ChatService | None = None


def _get_quota_manager(settings: Settings) -> QuotaManager:
    global _quota_manager
    if _quota_manager is None:
        _quota_manager = QuotaManager(settings)
    return _quota_manager


def _get_chat_service(settings: Settings) -> ChatService:
    global _chat_service
    if _chat_service is None:
        _chat_service = ChatService(settings)
    return _chat_service


def _extract_recent_user_text(messages: list[dict]) -> str:
    for message in reversed(messages):
        if not isinstance(message, dict) or message.get("role") != "user":
            continue

        raw_parts = message.get("parts") or message.get("content") or []
        if isinstance(raw_parts, str) and raw_parts.strip():
            return raw_parts

        if not isinstance(raw_parts, list):
            continue

        text_parts = [
            str(part.get("text", "")).strip()
            for part in raw_parts
            if isinstance(part, dict) and part.get("type") == "text"
        ]
        if text_parts:
            return "\n".join(part for part in text_parts if part)

    return ""


def _build_shape_library_hint(messages: list[dict]) -> str:
    user_text = f" {_extract_recent_user_text(messages).lower()} "
    if not user_text.strip():
        return ""

    library_patterns = [
        ("aws4", (" aws ", "amazon web services", "aws icon")),
        ("azure2", (" azure ", "azure icon")),
        ("gcp2", (" gcp ", "google cloud", "google cloud platform")),
        ("kubernetes", (" kubernetes ", " k8s ")),
        ("cisco19", (" cisco ",)),
        ("bpmn", (" bpmn ",)),
        ("flowchart", (" flowchart ",)),
        ("material_design", ("material icon", "material design")),
    ]

    for library, patterns in library_patterns:
        if any(pattern in user_text for pattern in patterns):
            return (
                "## Required Shape Library Guidance\n"
                f"This request explicitly matches the `{library}` library. "
                f"Before creating the diagram, call `get_shape_library` with "
                f'`{{"library":"{library}"}}` and use those documented shapes/icons '
                "instead of falling back to generic rounded text boxes."
            )

    return ""


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.post("/chat")
async def chat(
    request: ChatRequest,
    raw_request: Request,
    settings: Settings = Depends(get_settings),
    overrides: ClientOverrides = Depends(get_client_overrides),
    user_id: str = Depends(get_user_id),
) -> StreamingResponse:
    """
    Main streaming chat endpoint.

    Returns an SSE stream of JSON events consumed by the frontend.
    """

    # ------------------------------------------------------------------
    # 1. Access-code check (uses verify_access_code dependency if needed,
    #    but chat returns JSON instead of raising — so inline check is kept
    #    intentionally to return JSONResponse instead of HTTPException).
    # ------------------------------------------------------------------
    if settings.access_codes:
        provided = raw_request.headers.get("x-access-code", "")
        if not provided or provided not in settings.access_codes:
            return JSONResponse(
                status_code=401,
                content={
                    "error": (
                        "Invalid or missing access code. "
                        "Please configure it in Settings."
                    )
                },
            )

    # ------------------------------------------------------------------
    # 2. File / attachment validation
    # ------------------------------------------------------------------
    try:
        validate_file_parts(
            request.messages,
            settings.MAX_FILE_SIZE_BYTES,
            settings.MAX_FILES_PER_MESSAGE,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})

    # ------------------------------------------------------------------
    # 3. Quota check (DynamoDB — opt-in)
    # ------------------------------------------------------------------
    if settings.DYNAMODB_QUOTA_TABLE and not overrides.api_key:
        allowed, reason = await _get_quota_manager(settings).check_and_increment(user_id)
        if not allowed:
            return JSONResponse(status_code=429, content={"error": reason})

    # ------------------------------------------------------------------
    # 4. Cached-response shortcut
    #    Only for single-turn conversations on an empty / minimal canvas.
    # ------------------------------------------------------------------
    logger.info(
        "Chat request: %d messages, has_xml=%s, minimal_diagram=%s",
        len(request.messages),
        bool(request.xml),
        is_minimal_diagram(request.xml or "") if len(request.messages) == 1 else "N/A",
    )
    if len(request.messages) == 1 and is_minimal_diagram(request.xml or ""):
        first_msg = request.messages[0]
        user_text = ""
        has_image = False

        # Support both UIMessage format (parts) and litellm format (content)
        parts = first_msg.get("parts") or first_msg.get("content") or []

        if isinstance(parts, list):
            user_text = extract_user_text_from_parts(parts)
            has_image = has_file_in_parts(parts)
        elif isinstance(parts, str):
            user_text = parts

        cached_xml = find_cached_response(user_text, has_image)
        if cached_xml:
            logger.info(
                "Cache hit: user_text=%r, has_image=%s",
                user_text[:80],
                has_image,
            )

            async def _cached_stream():
                msg_id = _nanoid("msg_")
                text_id = _nanoid("text_")
                call_id = _nanoid("call_")
                args = {"xml": cached_xml}
                args_json = json.dumps(args, ensure_ascii=False)

                yield _sse({"type": "start", "messageId": msg_id})
                yield _sse({"type": "text-start", "id": text_id})
                yield _sse({"type": "text-delta", "id": text_id, "delta": "I'll display the diagram."})
                yield _sse({"type": "text-end", "id": text_id})
                yield _sse({"type": "tool-input-start", "toolCallId": call_id, "toolName": "display_diagram"})
                yield _sse({"type": "tool-input-delta", "toolCallId": call_id, "inputTextDelta": args_json})
                yield _sse({"type": "tool-input-available", "toolCallId": call_id, "toolName": "display_diagram", "input": args})
                yield _sse({"type": "finish"})
                yield _SSE_DONE

            return StreamingResponse(
                _cached_stream(),
                media_type="text/event-stream",
                headers={
                    "X-Accel-Buffering": "no",
                    "Cache-Control": "no-cache, no-store, no-transform",
                    "Connection": "keep-alive",
                },
            )

    # ------------------------------------------------------------------
    # 5. Build system prompt
    # ------------------------------------------------------------------
    minimal_style: bool = overrides.minimal_style
    model_id: str = overrides.model_id or settings.AI_MODEL or ""
    system_prompt = get_system_prompt(model_id, minimal_style)
    shape_library_hint = _build_shape_library_hint(request.messages)
    if shape_library_hint:
        system_prompt = f"{system_prompt}\n\n{shape_library_hint}"

    if request.customSystemMessage:
        system_prompt = (
            f"{system_prompt}\n\n## Custom Instructions\n"
            f"{request.customSystemMessage}"
        )

    # ------------------------------------------------------------------
    # 6. Build XML context
    # ------------------------------------------------------------------
    xml_context = build_xml_context(request.xml or "", request.previousXml)

    # ------------------------------------------------------------------
    # 7. Convert UIMessages to litellm format + optional history replacement
    # ------------------------------------------------------------------
    # The AI SDK DefaultChatTransport sends messages in UIMessage format
    # (with "parts" arrays).  litellm expects a different format (with
    # "content" / "tool_calls").  Convert before passing to ChatService.
    messages = convert_ui_messages_to_litellm(request.messages)

    if settings.ENABLE_HISTORY_XML_REPLACE:
        messages = replace_historical_tool_inputs(messages)

    # ------------------------------------------------------------------
    # 8. Resolve AI model config
    # ------------------------------------------------------------------
    try:
        model_config = get_ai_model(
            provider=overrides.provider or settings.AI_PROVIDER,
            model_id=model_id,
            api_key=overrides.api_key,
            base_url=overrides.base_url,
            settings=settings,
        )
    except ValueError as exc:
        logger.error("Model configuration error: %s", exc)
        return JSONResponse(status_code=400, content={"error": str(exc)})

    has_image_input = any(
        isinstance(msg, dict)
        and msg.get("role") == "user"
        and isinstance(msg.get("content"), list)
        and any(
            isinstance(part, dict) and part.get("type") == "image_url"
            for part in msg["content"]
        )
        for msg in messages
    )
    if has_image_input and not supports_image_input(model_config.model_id):
        return JSONResponse(
            status_code=400,
            content={
                "error": (
                    "The selected model does not support image input. "
                    "Choose a vision-capable model or remove the image attachment."
                )
            },
        )

    # ------------------------------------------------------------------
    # 9. Stream response
    # ------------------------------------------------------------------
    service = _get_chat_service(settings)
    try:
        stream = service.stream_chat(
            messages=messages,
            model_config=model_config,
            system_prompt=system_prompt,
            xml_context=xml_context,
            current_xml=request.xml or "",
            shape_library_dir=_SHAPE_LIBRARY_DIR,
        )
    except NotImplementedError:
        return JSONResponse(
            status_code=501,
            content={"error": "ChatService.stream_chat is not yet implemented."},
        )

    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache, no-store, no-transform",
            "Connection": "keep-alive",
        },
    )
