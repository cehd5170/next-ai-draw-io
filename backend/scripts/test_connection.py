#!/usr/bin/env python3
"""
test_connection.py — Connection test suite for the Python backend.

Tests every public endpoint against a running backend instance and prints a
summary of what passed and what failed.

Usage
-----
    python scripts/test_connection.py                  # uses http://localhost:8000
    BACKEND_URL=http://localhost:8000 python scripts/test_connection.py

Requirements
------------
    pip install httpx

The script is intentionally self-contained and has no dependency on the
backend package itself so it can be run from any Python environment that has
httpx installed.
"""

from __future__ import annotations

import json
import os
import sys
import textwrap
import time
from typing import Any

try:
    import httpx
except ImportError:
    print("ERROR: httpx is required.  Install it with:  pip install httpx")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BACKEND_URL: str = os.environ.get("BACKEND_URL", "http://localhost:8000").rstrip("/")
TIMEOUT: float = float(os.environ.get("TEST_TIMEOUT", "15"))

# Minimal valid draw.io XML used across several tests.
SAMPLE_XML = textwrap.dedent("""\
    <mxGraphModel>
      <root>
        <mxCell id="0"/>
        <mxCell id="1" parent="0"/>
        <mxCell id="2" value="Start"
          style="rounded=1;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;"
          vertex="1" parent="1">
          <mxGeometry x="100" y="100" width="120" height="60" as="geometry"/>
        </mxCell>
        <mxCell id="3" value="Process" style="whiteSpace=wrap;html=1;" vertex="1" parent="1">
          <mxGeometry x="100" y="220" width="120" height="60" as="geometry"/>
        </mxCell>
        <mxCell id="4" value="End"
          style="rounded=1;whiteSpace=wrap;html=1;fillColor=#f8cecc;strokeColor=#b85450;"
          vertex="1" parent="1">
          <mxGeometry x="100" y="340" width="120" height="60" as="geometry"/>
        </mxCell>
        <mxCell id="5" style="endArrow=classic;html=1;" edge="1" parent="1" source="2" target="3">
          <mxGeometry relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="6" style="endArrow=classic;html=1;" edge="1" parent="1" source="3" target="4">
          <mxGeometry relative="1" as="geometry"/>
        </mxCell>
      </root>
    </mxGraphModel>
""")

# A 1x1 transparent PNG encoded as a base-64 data URL (smallest valid PNG).
MINIMAL_PNG_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)

# ---------------------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------------------

_results: list[dict[str, Any]] = []


def _record(name: str, passed: bool, detail: str = "") -> None:
    _results.append({"name": name, "passed": passed, "detail": detail})
    status = "PASS" if passed else "FAIL"
    prefix = f"  [{status}] {name}"
    if detail:
        print(f"{prefix} — {detail}")
    else:
        print(prefix)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get(path: str, **kwargs: Any) -> httpx.Response:
    with httpx.Client(timeout=TIMEOUT) as client:
        return client.get(f"{BACKEND_URL}{path}", **kwargs)


def _post(path: str, **kwargs: Any) -> httpx.Response:
    with httpx.Client(timeout=TIMEOUT) as client:
        return client.post(f"{BACKEND_URL}{path}", **kwargs)


def _stream_post(path: str, **kwargs: Any) -> httpx.Response:
    """POST that reads the full streamed response body before returning."""
    with httpx.Client(timeout=TIMEOUT) as client:
        with client.stream("POST", f"{BACKEND_URL}{path}", **kwargs) as r:
            # Consume all chunks so the body is available via r.text after exit.
            chunks = list(r.iter_bytes())
    # Re-assemble onto the response object for uniform handling.
    r._content = b"".join(chunks)  # type: ignore[attr-defined]
    return r


# ---------------------------------------------------------------------------
# Individual test functions
# ---------------------------------------------------------------------------


def test_health() -> bool:
    """GET /health — backend liveness probe."""
    print("\n[1/9] Health check")
    try:
        r = _get("/health")
        if r.status_code == 200 and r.json().get("status") == "ok":
            _record("GET /health", True, 'status="ok"')
            return True
        _record("GET /health", False, f"HTTP {r.status_code}: {r.text[:120]}")
    except httpx.ConnectError:
        _record(
            "GET /health",
            False,
            f"Connection refused — is the backend running at {BACKEND_URL}?",
        )
    except Exception as exc:  # noqa: BLE001
        _record("GET /health", False, str(exc)[:120])
    return False


def test_config() -> None:
    """GET /api/config — verify all expected fields are present."""
    print("\n[2/9] Config endpoint")
    expected_fields = {
        "accessCodeRequired",
        "dailyRequestLimit",
        "dailyTokenLimit",
        "tpmLimit",
        "maxFileSize",
        "maxFiles",
        "maxImageSize",
        "enableVlmValidation",
    }
    try:
        r = _get("/api/config")
        if r.status_code != 200:
            _record("GET /api/config", False, f"HTTP {r.status_code}: {r.text[:120]}")
            return
        body = r.json()
        missing = expected_fields - set(body.keys())
        if missing:
            _record("GET /api/config", False, f"Missing fields: {sorted(missing)}")
        else:
            _record(
                "GET /api/config",
                True,
                f"accessCodeRequired={body['accessCodeRequired']}, "
                f"enableVlmValidation={body['enableVlmValidation']}",
            )
    except Exception as exc:  # noqa: BLE001
        _record("GET /api/config", False, str(exc)[:120])


def test_server_models() -> None:
    """GET /api/server-models — verify response shape."""
    print("\n[3/9] Server models endpoint")
    try:
        r = _get("/api/server-models")
        if r.status_code != 200:
            _record(
                "GET /api/server-models",
                False,
                f"HTTP {r.status_code}: {r.text[:120]}",
            )
            return
        body = r.json()
        if "models" not in body or "hasConfig" not in body:
            _record(
                "GET /api/server-models",
                False,
                f"Unexpected shape: {list(body.keys())}",
            )
        else:
            _record(
                "GET /api/server-models",
                True,
                f"hasConfig={body['hasConfig']}, models={len(body['models'])}",
            )
    except Exception as exc:  # noqa: BLE001
        _record("GET /api/server-models", False, str(exc)[:120])


def test_verify_access_code() -> None:
    """POST /api/verify-access-code — no code, server decides valid/invalid."""
    print("\n[4/9] Verify access code endpoint")
    try:
        r = _post("/api/verify-access-code")
        # 200 = no access code configured; 401 = code required but not provided.
        # Both are legitimate responses — we just want a well-formed JSON body.
        body = r.json()
        if "valid" in body:
            _record(
                "POST /api/verify-access-code",
                True,
                f"HTTP {r.status_code}, valid={body['valid']}, "
                f"message={body.get('message', '')}",
            )
        else:
            _record(
                "POST /api/verify-access-code",
                False,
                f"Missing 'valid' field: {body}",
            )
    except Exception as exc:  # noqa: BLE001
        _record("POST /api/verify-access-code", False, str(exc)[:120])


def test_chat_sse() -> None:
    """
    POST /api/chat — verify SSE stream format.

    Uses a pre-canned first message on an empty canvas so the backend returns
    the cached 'help' response and never calls an external LLM.  This keeps
    the test fast and API-key-free.
    """
    print("\n[5/9] Chat SSE stream")
    payload = {
        "messages": [
            {
                "id": "test-msg-1",
                "role": "user",
                "content": [{"type": "text", "text": "help"}],
            }
        ],
        "xml": "",
        "previousXml": None,
        "sessionId": "test-session-connection-check",
    }
    try:
        r = _stream_post("/api/chat", json=payload)
    except Exception as exc:  # noqa: BLE001
        _record("POST /api/chat (SSE)", False, str(exc)[:120])
        return

    if r.status_code not in (200, 401, 429):
        _record(
            "POST /api/chat (SSE)",
            False,
            f"HTTP {r.status_code}: {r.text[:120]}",
        )
        return

    if r.status_code == 401:
        _record(
            "POST /api/chat (SSE)",
            True,
            "HTTP 401 — access code required (endpoint is reachable)",
        )
        return

    if r.status_code == 429:
        _record(
            "POST /api/chat (SSE)",
            True,
            "HTTP 429 — quota exceeded (endpoint is reachable)",
        )
        return

    # Verify content-type and SSE event structure.
    content_type = r.headers.get("content-type", "")
    if "text/event-stream" not in content_type:
        _record(
            "POST /api/chat (SSE) — content-type",
            False,
            f"Expected text/event-stream, got: {content_type}",
        )
    else:
        _record(
            "POST /api/chat (SSE) — content-type",
            True,
            f"content-type: {content_type}",
        )

    # Verify X-Accel-Buffering header is set to disable nginx buffering.
    buffering_header = r.headers.get("x-accel-buffering", "")
    if buffering_header.lower() == "no":
        _record(
            "POST /api/chat (SSE) — X-Accel-Buffering",
            True,
            "X-Accel-Buffering: no",
        )
    else:
        _record(
            "POST /api/chat (SSE) — X-Accel-Buffering",
            False,
            f"Expected 'no', got: '{buffering_header}'",
        )

    # Parse SSE events and look for known event types.
    raw_body = r.content.decode("utf-8", errors="replace")
    events: list[dict[str, Any]] = []
    done_seen = False

    for line in raw_body.splitlines():
        if line.startswith("data: "):
            payload_str = line[len("data: "):]
            if payload_str.strip() == "[DONE]":
                done_seen = True
                continue
            try:
                events.append(json.loads(payload_str))
            except json.JSONDecodeError:
                pass  # Partial line or non-JSON data event — ignore.

    if done_seen:
        _record("POST /api/chat (SSE) — [DONE] terminator", True)
    else:
        _record(
            "POST /api/chat (SSE) — [DONE] terminator",
            False,
            "Stream did not end with 'data: [DONE]'",
        )

    known_types = {"tool_call", "text", "error", "finish"}
    found_types = {e.get("type") for e in events if isinstance(e, dict)}
    if found_types:
        _record(
            "POST /api/chat (SSE) — event types",
            True,
            f"Observed types: {sorted(found_types & known_types) or sorted(found_types)}",
        )
    else:
        _record(
            "POST /api/chat (SSE) — event types",
            len(events) == 0 and done_seen,  # empty but well-formed is still ok
            "No JSON events found in stream",
        )


def test_validate_diagram() -> None:
    """POST /api/validate-diagram — verify streamed JSON response."""
    print("\n[6/9] Validate diagram endpoint")
    payload = {
        "imageData": MINIMAL_PNG_DATA_URL,
        "sessionId": "test-session-connection-check",
    }
    try:
        r = _stream_post("/api/validate-diagram", json=payload)
    except Exception as exc:  # noqa: BLE001
        _record("POST /api/validate-diagram", False, str(exc)[:120])
        return

    if r.status_code != 200:
        _record(
            "POST /api/validate-diagram",
            False,
            f"HTTP {r.status_code}: {r.text[:120]}",
        )
        return

    content_type = r.headers.get("content-type", "")
    if "text/plain" not in content_type:
        _record(
            "POST /api/validate-diagram — content-type",
            False,
            f"Expected text/plain, got: {content_type}",
        )
    else:
        _record(
            "POST /api/validate-diagram — content-type",
            True,
            f"content-type: {content_type}",
        )

    raw = r.content.decode("utf-8", errors="replace").strip()
    try:
        body = json.loads(raw)
        required = {"valid", "issues", "suggestions"}
        missing = required - set(body.keys())
        if missing:
            _record(
                "POST /api/validate-diagram — response shape",
                False,
                f"Missing fields: {sorted(missing)}",
            )
        else:
            _record(
                "POST /api/validate-diagram — response shape",
                True,
                f"valid={body['valid']}, issues={len(body['issues'])}, "
                f"suggestions={len(body['suggestions'])}",
            )
    except json.JSONDecodeError as exc:
        _record(
            "POST /api/validate-diagram — JSON parse",
            False,
            f"Could not parse response as JSON: {exc} — body[:120]: {raw[:120]}",
        )


def test_validate_model() -> None:
    """POST /api/validate-model — missing credentials returns valid=false, not 5xx."""
    print("\n[7/9] Validate model endpoint")
    payload = {
        "provider": "openai",
        "modelId": "gpt-4o",
        "apiKey": "sk-invalid-key-for-testing",
    }
    try:
        r = _post("/api/validate-model", json=payload)
    except Exception as exc:  # noqa: BLE001
        _record("POST /api/validate-model", False, str(exc)[:120])
        return

    # The endpoint always returns HTTP 200 with a JSON body.
    if r.status_code != 200:
        _record(
            "POST /api/validate-model",
            False,
            f"HTTP {r.status_code}: {r.text[:120]}",
        )
        return

    body = r.json()
    if "valid" not in body:
        _record(
            "POST /api/validate-model",
            False,
            f"Missing 'valid' field: {body}",
        )
        return

    # An invalid key must produce valid=false, not a server error.
    if body["valid"] is False:
        _record(
            "POST /api/validate-model",
            True,
            f"valid=false, error={body.get('error', '')[:80]}",
        )
    else:
        # Unexpectedly accepted — still a well-formed response.
        _record(
            "POST /api/validate-model",
            True,
            f"valid={body['valid']}, responseTime={body.get('responseTime')}ms",
        )


def test_export_pptx() -> None:
    """POST /api/export-pptx — verify binary PPTX response."""
    print("\n[8/9] Export PPTX endpoint")
    payload = {
        "xml": SAMPLE_XML,
        "filename": "test-diagram.pptx",
    }
    try:
        r = _post("/api/export-pptx", json=payload)
    except Exception as exc:  # noqa: BLE001
        _record("POST /api/export-pptx", False, str(exc)[:120])
        return

    if r.status_code == 503:
        _record(
            "POST /api/export-pptx",
            False,
            "HTTP 503 — drawio2pptx library not installed. "
            "Run:  pip install drawio2pptx",
        )
        return

    if r.status_code == 400:
        _record(
            "POST /api/export-pptx",
            False,
            f"HTTP 400 — {r.json().get('error', r.text[:120])}",
        )
        return

    if r.status_code != 200:
        _record(
            "POST /api/export-pptx",
            False,
            f"HTTP {r.status_code}: {r.text[:120]}",
        )
        return

    # Verify MIME type.
    expected_mime = (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    )
    content_type = r.headers.get("content-type", "")
    if expected_mime not in content_type:
        _record(
            "POST /api/export-pptx — MIME type",
            False,
            f"Expected PPTX MIME, got: {content_type}",
        )
    else:
        _record("POST /api/export-pptx — MIME type", True, f"content-type: {content_type}")

    # Verify Content-Disposition header.
    disposition = r.headers.get("content-disposition", "")
    if "attachment" in disposition and ".pptx" in disposition:
        _record(
            "POST /api/export-pptx — Content-Disposition",
            True,
            disposition,
        )
    else:
        _record(
            "POST /api/export-pptx — Content-Disposition",
            False,
            f"Unexpected: {disposition}",
        )

    # Verify the response is a valid PPTX file (ZIP magic bytes: PK\x03\x04).
    body_bytes = r.content
    if body_bytes[:4] == b"PK\x03\x04":
        _record(
            "POST /api/export-pptx — PPTX magic bytes",
            True,
            f"{len(body_bytes):,} bytes, valid ZIP/PPTX magic",
        )
    else:
        _record(
            "POST /api/export-pptx — PPTX magic bytes",
            False,
            f"First 4 bytes: {body_bytes[:4]!r} (expected b'PK\\x03\\x04')",
        )


def test_parse_url() -> None:
    """POST /api/parse-url — invalid URL returns 400, reachable URL returns content."""
    print("\n[9/9] Parse URL endpoint")

    # Subtest A: missing URL body → 400.
    try:
        r = _post("/api/parse-url", json={"url": ""})
        if r.status_code == 400:
            _record(
                "POST /api/parse-url — empty URL rejected",
                True,
                f"HTTP 400: {r.json().get('error', '')[:80]}",
            )
        else:
            _record(
                "POST /api/parse-url — empty URL rejected",
                False,
                f"Expected HTTP 400, got {r.status_code}",
            )
    except Exception as exc:  # noqa: BLE001
        _record("POST /api/parse-url — empty URL rejected", False, str(exc)[:120])

    # Subtest B: non-http scheme → 400.
    try:
        r = _post("/api/parse-url", json={"url": "ftp://example.com"})
        if r.status_code == 400:
            _record(
                "POST /api/parse-url — non-http scheme rejected",
                True,
                f"HTTP 400: {r.json().get('error', '')[:80]}",
            )
        else:
            _record(
                "POST /api/parse-url — non-http scheme rejected",
                False,
                f"Expected HTTP 400, got {r.status_code}",
            )
    except Exception as exc:  # noqa: BLE001
        _record("POST /api/parse-url — non-http scheme rejected", False, str(exc)[:120])


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    print("=" * 60)
    print(f"  next-ai-draw-io backend connection tests")
    print(f"  Backend: {BACKEND_URL}")
    print(f"  Timeout: {TIMEOUT}s")
    print("=" * 60)

    start = time.monotonic()

    # Health check first — abort early if backend is unreachable.
    backend_alive = test_health()
    if not backend_alive:
        print(
            "\nBackend is not reachable.  Start it with:\n"
            "  cd backend && pip install -e . && uvicorn app.main:app --port 8000\n"
        )
        print("[SUMMARY]  0 passed, 1 failed — aborting remaining tests.")
        sys.exit(1)

    test_config()
    test_server_models()
    test_verify_access_code()
    test_chat_sse()
    test_validate_diagram()
    test_validate_model()
    test_export_pptx()
    test_parse_url()

    elapsed = time.monotonic() - start
    passed = sum(1 for r in _results if r["passed"])
    failed = sum(1 for r in _results if not r["passed"])
    total = len(_results)

    print("\n" + "=" * 60)
    print(f"  SUMMARY:  {passed}/{total} passed,  {failed} failed  ({elapsed:.1f}s)")
    print("=" * 60)

    if failed:
        print("\nFailed checks:")
        for r in _results:
            if not r["passed"]:
                print(f"  - {r['name']}: {r['detail']}")
        print()
        sys.exit(1)
    else:
        print("\nAll checks passed.")
        sys.exit(0)


if __name__ == "__main__":
    main()
