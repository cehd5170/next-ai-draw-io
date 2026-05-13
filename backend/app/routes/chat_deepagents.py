"""
POST /chat-deepagents — deepagents + SKILL.md based diagram agent endpoint.

Mirrors /chat-agents preprocessing but uses DeepAgentsService for orchestration.
Skills are loaded from backend/app/skills/ as SKILL.md files via progressive
disclosure, reducing per-request context overhead.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.config import Settings
from app.dependencies import get_client_overrides, get_settings, get_user_id
from app.models.chat import ChatRequest, ClientOverrides
from app.prompts import build_xml_context, get_system_prompt
from app.providers.factory import get_ai_model, supports_image_input
from app.routes.chat import (
    _SHAPE_LIBRARY_DIR,
    _build_shape_library_hint,
    _detect_requested_shape_library,
    _get_quota_manager,
    _should_force_diagram_tool,
)
from app.routes.server_models import (
    find_server_model_by_id,
    resolve_server_model_credentials,
)
from app.services.deepagents_service import DeepAgentsService
from app.services.cached_responses import find_cached_response
from app.services.chat_service import _SSE_DONE, _nanoid, _sse
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

router = APIRouter()
logger = logging.getLogger(__name__)

_deepagents_service: DeepAgentsService | None = None


def _get_deepagents_service(settings: Settings) -> DeepAgentsService:
    global _deepagents_service
    if _deepagents_service is None:
        _deepagents_service = DeepAgentsService(settings)
    return _deepagents_service


@router.post("/chat-deepagents")
async def chat_deepagents(
    request: ChatRequest,
    raw_request: Request,
    settings: Settings = Depends(get_settings),
    overrides: ClientOverrides = Depends(get_client_overrides),
    user_id: str = Depends(get_user_id),
) -> StreamingResponse:
    if settings.access_codes:
        provided = raw_request.headers.get("x-access-code", "")
        if not provided or provided not in settings.access_codes:
            return JSONResponse(
                status_code=401,
                content={"error": "Invalid or missing access code. Please configure it in Settings."},
            )

    try:
        validate_file_parts(
            request.messages,
            settings.MAX_FILE_SIZE_BYTES,
            settings.MAX_FILES_PER_MESSAGE,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})

    if settings.DYNAMODB_QUOTA_TABLE and not overrides.api_key:
        allowed, reason = await _get_quota_manager(settings).check_and_increment(user_id)
        if not allowed:
            return JSONResponse(status_code=429, content={"error": reason})

    if len(request.messages) == 1 and is_minimal_diagram(request.xml or ""):
        first_msg = request.messages[0]
        user_text = ""
        has_image = False
        parts = first_msg.get("parts") or first_msg.get("content") or []
        if isinstance(parts, list):
            user_text = extract_user_text_from_parts(parts)
            has_image = has_file_in_parts(parts)
        elif isinstance(parts, str):
            user_text = parts

        cached_xml = find_cached_response(user_text, has_image)
        if cached_xml:
            async def _cached_stream():
                msg_id = _nanoid("msg_")
                text_id = _nanoid("text_")
                call_id = _nanoid("call_")
                args = {"xml": cached_xml}
                args_json = json.dumps(args, ensure_ascii=False)
                yield _sse({"type": "start", "messageId": msg_id})
                yield _sse({"type": "tool-input-start", "toolCallId": call_id, "toolName": "display_diagram"})
                yield _sse({"type": "tool-input-delta", "toolCallId": call_id, "inputTextDelta": args_json})
                yield _sse({"type": "tool-input-available", "toolCallId": call_id, "toolName": "display_diagram", "input": args})
                yield _sse({"type": "tool-output-available", "toolCallId": call_id, "output": {"message": "Diagram created successfully.", "xml": cached_xml, "success": True, "isTruncated": False}})
                yield _sse({"type": "text-start", "id": text_id})
                yield _sse({"type": "text-delta", "id": text_id, "delta": "I'll display the diagram."})
                yield _sse({"type": "text-end", "id": text_id})
                yield _sse({"type": "finish"})
                yield _SSE_DONE

            return StreamingResponse(
                _cached_stream(),
                media_type="text/event-stream",
                headers={
                    "X-Accel-Buffering": "no",
                    "Cache-Control": "no-cache, no-store, no-transform",
                    "x-vercel-ai-ui-message-stream": "v1",
                    "Connection": "keep-alive",
                },
            )

    minimal_style: bool = overrides.minimal_style
    model_id: str = overrides.model_id or settings.AI_MODEL or ""
    system_prompt = get_system_prompt(model_id, minimal_style)
    shape_library_hint = _build_shape_library_hint(request.messages)
    preferred_shape_library = _detect_requested_shape_library(request.messages)
    force_diagram_tool = _should_force_diagram_tool(request.messages, request.xml or "")
    if shape_library_hint:
        system_prompt = f"{system_prompt}\n\n{shape_library_hint}"

    if request.customSystemMessage:
        system_prompt = f"{system_prompt}\n\n## Custom Instructions\n{request.customSystemMessage}"

    xml_context = build_xml_context(request.xml or "", request.previousXml)
    messages = convert_ui_messages_to_litellm(request.messages)

    if settings.ENABLE_HISTORY_XML_REPLACE:
        messages = replace_historical_tool_inputs(messages)

    try:
        resolved_provider = overrides.provider or settings.AI_PROVIDER
        resolved_model_id = model_id
        resolved_api_key = overrides.api_key
        resolved_base_url = overrides.base_url

        if overrides.selected_model_id and overrides.selected_model_id.startswith("server:"):
            server_model = await find_server_model_by_id(overrides.selected_model_id, settings)
            if server_model is None:
                return JSONResponse(
                    status_code=400,
                    content={"error": f"Selected server model '{overrides.selected_model_id}' was not found."},
                )
            resolved_provider = server_model.provider
            resolved_model_id = server_model.modelId
            server_api_key, server_base_url = resolve_server_model_credentials(server_model)
            resolved_api_key = resolved_api_key or server_api_key
            resolved_base_url = resolved_base_url or server_base_url

        model_config = get_ai_model(
            provider=resolved_provider,
            model_id=resolved_model_id,
            api_key=resolved_api_key,
            base_url=resolved_base_url,
            settings=settings,
        )
    except ValueError as exc:
        logger.error("Model configuration error: %s", exc)
        return JSONResponse(status_code=400, content={"error": str(exc)})

    has_image_input = any(
        isinstance(msg, dict)
        and msg.get("role") == "user"
        and isinstance(msg.get("content"), list)
        and any(isinstance(part, dict) and part.get("type") == "image_url" for part in msg["content"])
        for msg in messages
    )
    if has_image_input and not supports_image_input(model_config.model_id):
        return JSONResponse(
            status_code=400,
            content={"error": "The selected model does not support image input. Choose a vision-capable model or remove the image attachment."},
        )

    service = _get_deepagents_service(settings)
    try:
        stream = service.stream_chat(
            messages=messages,
            model_config=model_config,
            system_prompt=system_prompt,
            xml_context=xml_context,
            current_xml=request.xml or "",
            shape_library_dir=_SHAPE_LIBRARY_DIR,
            preferred_shape_library=preferred_shape_library,
            force_diagram_tool=force_diagram_tool,
        )
    except (NotImplementedError, RuntimeError) as exc:
        return JSONResponse(status_code=501, content={"error": str(exc)})

    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache, no-store, no-transform",
            "x-vercel-ai-ui-message-stream": "v1",
            "Connection": "keep-alive",
        },
    )
