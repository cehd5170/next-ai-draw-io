import { describe, expect, it } from "vitest"
import { extractTitle, sanitizeMessage } from "@/lib/session-storage"

describe("session-storage", () => {
    it("removes inline attachment payloads when sanitizing messages", () => {
        const sanitized = sanitizeMessage({
            id: "user-1",
            role: "user",
            parts: [
                { type: "text", text: "hello" },
                {
                    type: "file",
                    url: "data:image/png;base64,AAAA",
                    mediaType: "image/png",
                    filename: "diagram.png",
                },
            ],
        })

        expect(sanitized).not.toBeNull()
        expect(sanitized?.parts).toEqual([
            { type: "text", text: "hello" },
            {
                type: "file",
                mediaType: "image/png",
                filename: "diagram.png",
            },
        ])
    })

    it("removes inline image payloads when sanitizing messages", () => {
        const sanitized = sanitizeMessage({
            id: "user-2",
            role: "user",
            parts: [
                {
                    type: "image",
                    url: "data:image/png;base64,BBBB",
                    mediaType: "image/png",
                },
            ],
        })

        expect(sanitized).not.toBeNull()
        expect(sanitized?.parts).toEqual([
            {
                type: "image",
                mediaType: "image/png",
            },
        ])
    })

    it("falls back to the first attachment filename when the text is empty", () => {
        expect(
            extractTitle([
                {
                    id: "user-1",
                    role: "user",
                    parts: [
                        { type: "text", text: "   " },
                        { type: "file", filename: "architecture.pdf" },
                    ],
                },
            ]),
        ).toBe("architecture.pdf")
    })
})
