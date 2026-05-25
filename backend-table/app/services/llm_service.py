from __future__ import annotations

import asyncio
import json
import logging

from openai import AsyncOpenAI

from app.config import Settings
from app.tools.table_pptx import TOOL_SCHEMA, build_pptx, evict_expired, store_pptx

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a data extraction and presentation assistant.
When the user provides any text content, analyze it thoroughly and call create_table_pptx. Follow these rules:

Table content:
- Extract ALL meaningful data points — do not omit rows or columns to save space.
- Choose column headers that best capture the dimensions of the data (e.g. name, value, category, status, notes).
- Each row should be fully populated; use "-" only when a value is genuinely absent in the source.
- If the content allows multiple perspectives (e.g. pros/cons, before/after, by category), add those as extra columns.
- The title should be specific to the topic, not a generic label like "Table".

Text and layout:
- If the content has a useful summary, key insight, or context that doesn't fit neatly into the table, include it in the `text` field.
- Choose `layout`: use "text_above" for a short summary (1-3 sentences); "text_left" when the explanation is longer or equally important; "table_only" when no extra text is needed.

Only reply with plain text if the input is a simple greeting or question with no content to tabulate."""


async def chat(message: str, settings: Settings) -> dict:
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    response = await client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": message},
        ],
        tools=[TOOL_SCHEMA],
        tool_choice="auto",
        max_tokens=settings.MAX_TOKENS,
        temperature=settings.TEMPERATURE,
    )

    choice = response.choices[0]

    # Text-only response
    if not choice.message.tool_calls:
        return {"type": "text", "message": choice.message.content or ""}

    # Tool call
    tc = choice.message.tool_calls[0]
    try:
        args = json.loads(tc.function.arguments)
    except json.JSONDecodeError as exc:
        return {"type": "error", "message": f"Tool args parse error: {exc}"}

    try:
        pptx_bytes = await asyncio.to_thread(
            build_pptx,
            args["title"],
            args["headers"],
            args["rows"],
            args.get("text", ""),
            args.get("layout", "table_only"),
        )
    except Exception as exc:
        logger.error("build_pptx failed: %s", exc, exc_info=True)
        return {"type": "error", "message": f"PPTX generation failed: {exc}"}

    evict_expired()
    token = store_pptx(pptx_bytes, settings.DOWNLOAD_TTL_SECONDS)
    filename = f"{args.get('title', 'table')}.pptx"

    return {
        "type": "download",
        "url": f"/download/{token}",
        "filename": filename,
        "table": {"title": args["title"], "headers": args["headers"], "rows": args["rows"]},
    }
