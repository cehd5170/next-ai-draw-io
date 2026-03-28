import type { NextRequest } from "next/server"
import { NextResponse } from "next/server"

const HOP_BY_HOP_HEADERS = new Set([
    "connection",
    "content-length",
    "content-encoding",
    "host",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
])

export const dynamic = "force-dynamic"

function buildTargetUrl(path: string[], search: string): URL {
    const proxyBaseUrl = process.env.DRAWIO_PROXY_URL
    if (!proxyBaseUrl) {
        throw new Error(
            "DRAWIO_PROXY_URL is required to proxy /drawio/* requests.",
        )
    }

    const normalizedBaseUrl = proxyBaseUrl.endsWith("/")
        ? proxyBaseUrl
        : `${proxyBaseUrl}/`
    const targetUrl = new URL(path.join("/"), normalizedBaseUrl)
    targetUrl.search = search
    return targetUrl
}

async function proxyRequest(
    request: NextRequest,
    context: { params: Promise<{ path: string[] }> },
): Promise<NextResponse> {
    const { path } = await context.params

    let targetUrl: URL
    try {
        targetUrl = buildTargetUrl(path, request.nextUrl.search)
    } catch (error) {
        return NextResponse.json(
            {
                error:
                    error instanceof Error
                        ? error.message
                        : "DRAWIO_PROXY_URL is not configured.",
            },
            { status: 503 },
        )
    }

    const headers = new Headers(request.headers)
    for (const header of HOP_BY_HOP_HEADERS) {
        headers.delete(header)
    }
    headers.delete("accept-encoding")

    const upstreamResponse = await fetch(targetUrl, {
        method: request.method,
        headers,
        body:
            request.method === "GET" || request.method === "HEAD"
                ? undefined
                : await request.arrayBuffer(),
        cache: "no-store",
        redirect: "manual",
    })

    const responseHeaders = new Headers(upstreamResponse.headers)
    for (const header of HOP_BY_HOP_HEADERS) {
        responseHeaders.delete(header)
    }

    return new NextResponse(upstreamResponse.body, {
        status: upstreamResponse.status,
        statusText: upstreamResponse.statusText,
        headers: responseHeaders,
    })
}

export async function GET(
    request: NextRequest,
    context: { params: Promise<{ path: string[] }> },
) {
    return proxyRequest(request, context)
}

export async function HEAD(
    request: NextRequest,
    context: { params: Promise<{ path: string[] }> },
) {
    return proxyRequest(request, context)
}

export async function POST(
    request: NextRequest,
    context: { params: Promise<{ path: string[] }> },
) {
    return proxyRequest(request, context)
}

export async function PUT(
    request: NextRequest,
    context: { params: Promise<{ path: string[] }> },
) {
    return proxyRequest(request, context)
}

export async function PATCH(
    request: NextRequest,
    context: { params: Promise<{ path: string[] }> },
) {
    return proxyRequest(request, context)
}

export async function DELETE(
    request: NextRequest,
    context: { params: Promise<{ path: string[] }> },
) {
    return proxyRequest(request, context)
}

export async function OPTIONS(
    request: NextRequest,
    context: { params: Promise<{ path: string[] }> },
) {
    return proxyRequest(request, context)
}
