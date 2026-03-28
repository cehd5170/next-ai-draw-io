import { describe, expect, it } from "vitest"
import { resolveDrawioBaseUrl, resolveRuntimeUrl } from "@/lib/runtime-config"

describe("runtime-config", () => {
    it("resolves relative draw.io urls against the current origin", () => {
        expect(
            resolveRuntimeUrl("/drawio/index.html", "http://localhost:3000"),
        ).toBe("http://localhost:3000/drawio/index.html")
        expect(
            resolveRuntimeUrl("drawio/index.html", "http://localhost:3000"),
        ).toBe("http://localhost:3000/drawio/index.html")
    })

    it("keeps absolute draw.io urls untouched and falls back when missing", () => {
        expect(
            resolveDrawioBaseUrl(
                { drawioBaseUrl: "https://example.com/drawio/index.html" },
                "https://embed.diagrams.net",
                "http://localhost:3000",
            ),
        ).toBe("https://example.com/drawio/index.html")
        expect(
            resolveDrawioBaseUrl(
                { drawioBaseUrl: "" },
                "https://embed.diagrams.net",
                "http://localhost:3000",
            ),
        ).toBe("https://embed.diagrams.net")
    })
})
