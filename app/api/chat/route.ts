export const runtime = "nodejs"
export const dynamic = "force-dynamic"
export const maxDuration = 300

const HOP_BY_HOP_HEADERS = [
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "content-length",
]

const STREAMING_RESPONSE_HEADERS = {
    "Cache-Control": "no-cache, no-store, no-transform",
    "X-Accel-Buffering": "no",
    "x-vercel-ai-ui-message-stream": "v1",
    Connection: "keep-alive",
}

function getPythonApiUrl(): string | null {
    return process.env.PYTHON_API_URL?.replace(/\/$/, "") ?? null
}

export function buildChatProxyUrl(): string | null {
    const baseUrl = getPythonApiUrl()
    if (!baseUrl) return null
    return `${baseUrl}/api/chat`
}

export function buildForwardHeaders(headers: Headers): Headers {
    const forwarded = new Headers(headers)
    for (const name of HOP_BY_HOP_HEADERS) {
        forwarded.delete(name)
    }
    forwarded.delete("accept-encoding")
    return forwarded
}

export function buildProxyResponseHeaders(upstreamHeaders: Headers): Headers {
    const responseHeaders = new Headers(upstreamHeaders)
    for (const name of HOP_BY_HOP_HEADERS) {
        responseHeaders.delete(name)
    }
    for (const [name, value] of Object.entries(STREAMING_RESPONSE_HEADERS)) {
        responseHeaders.set(name, value)
    }
    if (!responseHeaders.has("Content-Type")) {
        responseHeaders.set("Content-Type", "text/event-stream; charset=utf-8")
    }
    return responseHeaders
}

export async function proxyChatRequest(request: Request): Promise<Response> {
    const upstreamUrl = buildChatProxyUrl()
    if (!upstreamUrl) {
        return Response.json(
            {
                error: "PYTHON_API_URL environment variable is required for /api/chat.",
            },
            { status: 500 },
        )
    }

    const requestId = request.headers.get("x-request-id") ?? crypto.randomUUID()
    const body = request.body
    const headers = buildForwardHeaders(request.headers)
    headers.set("x-request-id", requestId)
    const init: RequestInit & { duplex?: "half" } = {
        method: request.method,
        headers,
        body: body ?? undefined,
        signal: request.signal,
        cache: "no-store",
    }
    if (body) {
        init.duplex = "half"
    }

    try {
        const upstreamResponse = await fetch(upstreamUrl, init)
        const responseHeaders = buildProxyResponseHeaders(
            upstreamResponse.headers,
        )
        responseHeaders.set("x-request-id", requestId)

        return new Response(upstreamResponse.body, {
            status: upstreamResponse.status,
            statusText: upstreamResponse.statusText,
            headers: responseHeaders,
        })
    } catch {
        return Response.json(
            {
                error: "Upstream chat request failed before the stream started.",
                requestId,
            },
            { status: 502 },
        )
    }
}

export async function POST(request: Request): Promise<Response> {
    return proxyChatRequest(request)
}
