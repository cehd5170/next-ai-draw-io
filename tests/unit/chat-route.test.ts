import { afterEach, describe, expect, it, vi } from "vitest"
import {
    buildChatProxyUrl,
    buildForwardHeaders,
    buildProxyResponseHeaders,
    proxyChatRequest,
} from "@/app/api/chat/route"

const ORIGINAL_ENV = { ...process.env }

afterEach(() => {
    process.env.PYTHON_API_URL = ORIGINAL_ENV.PYTHON_API_URL
    vi.unstubAllGlobals()
})

describe("chat proxy route", () => {
    it("builds the backend URL from PYTHON_API_URL", () => {
        process.env.PYTHON_API_URL = "http://backend:8000/"

        expect(buildChatProxyUrl()).toBe("http://backend:8000/api/chat")
    })

    it("strips hop-by-hop headers from forwarded requests", () => {
        const headers = new Headers({
            "accept-encoding": "gzip, deflate, br",
            connection: "keep-alive",
            "content-length": "123",
            "x-custom": "value",
        })

        const forwarded = buildForwardHeaders(headers)

        expect(forwarded.has("accept-encoding")).toBe(false)
        expect(forwarded.has("connection")).toBe(false)
        expect(forwarded.has("content-length")).toBe(false)
        expect(forwarded.get("x-custom")).toBe("value")
    })

    it("enforces SSE buffering headers on upstream responses", () => {
        const headers = buildProxyResponseHeaders(
            new Headers({
                "content-type": "text/event-stream; charset=utf-8",
                "x-upstream": "1",
                connection: "close",
            }),
        )

        expect(headers.get("content-type")).toContain("text/event-stream")
        expect(headers.get("cache-control")).toBe(
            "no-cache, no-store, no-transform",
        )
        expect(headers.get("x-accel-buffering")).toBe("no")
        expect(headers.get("x-upstream")).toBe("1")
    })

    it("forwards the request body and returns the streamed body unchanged", async () => {
        process.env.PYTHON_API_URL = "http://backend:8000"

        const requestPayload = JSON.stringify({
            messages: [{ role: "user", content: "hello" }],
        })

        const upstreamStream = new ReadableStream<Uint8Array>({
            start(controller) {
                controller.enqueue(
                    new TextEncoder().encode(
                        'data: {"type":"start"}\n\n',
                    ),
                )
                controller.enqueue(
                    new TextEncoder().encode('data: [DONE]\n\n'),
                )
                controller.close()
            },
        })

        const fetchMock = vi.fn(async (_url: string, init: RequestInit) => {
            expect(_url).toBe("http://backend:8000/api/chat")
            expect(init.method).toBe("POST")
            expect(init.headers).toBeInstanceOf(Headers)
            expect((init as RequestInit & { duplex?: string }).duplex).toBe(
                "half",
            )

            const forwardedBody = await new Response(init.body as BodyInit).text()
            expect(forwardedBody).toBe(requestPayload)
            expect(
                (init.headers as Headers).has("content-length"),
            ).toBe(false)
            expect(
                (init.headers as Headers).has("accept-encoding"),
            ).toBe(false)

            return new Response(upstreamStream, {
                status: 200,
                headers: {
                    "content-type": "text/event-stream; charset=utf-8",
                    "x-upstream": "1",
                },
            })
        })

        vi.stubGlobal("fetch", fetchMock)

        const request = new Request("http://localhost/api/chat", {
            method: "POST",
            headers: {
                "content-type": "application/json",
                connection: "keep-alive",
                "content-length": String(requestPayload.length),
                "x-custom": "value",
            },
            body: requestPayload,
        })

        const response = await proxyChatRequest(request)

        expect(fetchMock).toHaveBeenCalledTimes(1)
        expect(response.status).toBe(200)
        expect(response.headers.get("x-upstream")).toBe("1")
        expect(response.headers.get("x-accel-buffering")).toBe("no")
        expect(response.headers.get("cache-control")).toBe(
            "no-cache, no-store, no-transform",
        )
        expect(response.body).not.toBeNull()
        const body = await response.text()
        expect(body).toContain('"type":"start"')
        expect(body).toContain("data: [DONE]")
    })

    it("returns a 500 when PYTHON_API_URL is missing", async () => {
        delete process.env.PYTHON_API_URL

        const response = await proxyChatRequest(
            new Request("http://localhost/api/chat", { method: "POST" }),
        )

        expect(response.status).toBe(500)
        await expect(response.json()).resolves.toMatchObject({
            error: expect.stringContaining("PYTHON_API_URL"),
        })
    })
})
