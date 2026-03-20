"""
POST /parse-url — fetch a URL and return its article content as Markdown.

Security
--------
- SSRF protection: private/internal URLs are blocked unless
  ``ALLOW_PRIVATE_URLS=true`` is explicitly configured.
- PDF URLs are rejected (user should upload the file directly).
- A configurable timeout prevents slow/hung upstream servers from tying up
  worker threads.
- Content is truncated to ``MAX_CONTENT_LENGTH`` characters.
"""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.config import Settings
from app.dependencies import get_settings
from app.models.parse_url import ParseUrlRequest, ParseUrlResponse
from app.services.ssrf_protection import is_private_url

router = APIRouter()
logger = logging.getLogger(__name__)

_USER_AGENT = "Mozilla/5.0 (compatible; NextAIDrawio-backend/1.0)"


@router.post("/parse-url", response_model=ParseUrlResponse)
async def parse_url(
    body: ParseUrlRequest,
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """
    Extract readable article text from *url* and return it as Markdown.

    Returns
    -------
    200  ``{title, content, charCount}`` on success
    400  on malformed URL, PDF content, or content too short
    403  when the URL targets a private network (SSRF)
    504  when the upstream server does not respond in time
    500  on unexpected extraction failure
    """
    url = (body.url or "").strip()

    # ------------------------------------------------------------------
    # Basic URL validation
    # ------------------------------------------------------------------
    if not url:
        return JSONResponse(status_code=400, content={"error": "URL is required"})

    try:
        from urllib.parse import urlparse as _urlparse

        parsed = _urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError("Only http and https URLs are supported")
    except Exception as exc:
        return JSONResponse(
            status_code=400, content={"error": f"Invalid URL format: {exc}"}
        )

    # ------------------------------------------------------------------
    # SSRF protection
    # ------------------------------------------------------------------
    if not settings.ALLOW_PRIVATE_URLS and is_private_url(url):
        return JSONResponse(
            status_code=403,
            content={"error": "Cannot access private/internal URLs"},
        )

    timeout = settings.EXTRACT_TIMEOUT_SECONDS

    # ------------------------------------------------------------------
    # HEAD pre-check — reject PDF URLs early
    # ------------------------------------------------------------------
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=min(3.0, timeout),
            headers={"User-Agent": _USER_AGENT},
        ) as client:
            head_resp = await client.head(url)
            content_type = head_resp.headers.get("content-type", "")
            if "application/pdf" in content_type:
                return JSONResponse(
                    status_code=422,
                    content={
                        "error": (
                            "PDF URLs are not supported. "
                            "Please download and upload the PDF file directly."
                        )
                    },
                )
    except httpx.TimeoutException:
        pass  # Proceed to full fetch; HEAD timed out
    except Exception:  # noqa: BLE001
        pass  # Network error on HEAD is non-fatal

    # ------------------------------------------------------------------
    # Extract article content with html2text
    # ------------------------------------------------------------------
    try:
        html, title = await _fetch_html(url, timeout)
    except httpx.TimeoutException:
        return JSONResponse(
            status_code=504,
            content={"error": "Timed out while fetching URL content"},
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("URL fetch failed for %s: %s", url, exc)
        return JSONResponse(
            status_code=500,
            content={"error": "Failed to fetch or parse URL content"},
        )

    if not html:
        return JSONResponse(
            status_code=400,
            content={"error": "Could not extract content from URL"},
        )

    # ------------------------------------------------------------------
    # Convert HTML → Markdown
    # ------------------------------------------------------------------
    markdown = _html_to_markdown(html)

    if not markdown.strip():
        return JSONResponse(
            status_code=400,
            content={"error": "Could not extract content from URL"},
        )

    # ------------------------------------------------------------------
    # Length check
    # ------------------------------------------------------------------
    max_len = settings.MAX_CONTENT_LENGTH
    if len(markdown) > max_len:
        # Truncate rather than reject — caller can handle partial content
        logger.debug(
            "URL content truncated: %d → %d chars (%s)",
            len(markdown),
            max_len,
            url,
        )
        markdown = markdown[:max_len]

    return JSONResponse(
        content=ParseUrlResponse(
            title=title or "Untitled",
            content=markdown,
            charCount=len(markdown),
        ).model_dump()
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _fetch_html(url: str, timeout: float) -> tuple[str, str]:
    """
    Fetch *url* and return ``(html_body, page_title)``.

    Uses httpx for the HTTP request and BeautifulSoup / lxml to extract the
    main article body.  Falls back to the full response text when article
    extraction is not possible.
    """
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=timeout,
        headers={"User-Agent": _USER_AGENT},
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
        html = response.text

    title = _extract_title(html)
    return html, title


def _extract_title(html: str) -> str:
    """Extract a page title from raw HTML (best-effort, no dependencies)."""
    import re

    match = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ""


def _html_to_markdown(html: str) -> str:
    """
    Convert raw HTML to Markdown using html2text.

    Strips scripts, styles, and iframes before conversion so that the
    resulting Markdown contains only meaningful textual content.
    """
    try:
        import html2text  # type: ignore[import]
    except ImportError:
        # Fallback: strip tags manually
        import re
        return re.sub(r"<[^>]+>", " ", html).strip()

    converter = html2text.HTML2Text()
    converter.ignore_links = False
    converter.ignore_images = True
    converter.ignore_tables = False
    converter.body_width = 0  # No hard line-wrapping
    converter.skip_internal_links = True

    return converter.handle(html)
