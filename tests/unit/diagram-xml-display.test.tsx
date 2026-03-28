// @vitest-environment jsdom

import { describe, expect, it } from "vitest"
import { prepareDiagramXmlForDisplay } from "@/lib/utils"

describe("prepareDiagramXmlForDisplay", () => {
    it("normalizes fixable mxCell XML the same way preview rendering does", () => {
        const rawXml =
            '<mxCell id="2" value="A & B" style="rounded=1;" vertex="1" parent="1"/>'

        const result = prepareDiagramXmlForDisplay(rawXml)

        expect(result.valid).toBe(true)
        expect(result.error).toBeNull()
        expect(result.xml).toContain("<mxfile>")
        expect(result.xml).toContain('<mxCell id="0"/>')
        expect(result.xml).toContain('value="A &amp; B"')
    })

    it("repairs malformed closing tags that commonly appear in model output", () => {
        const rawXml = `
<mxCell id="2" value="Box" vertex="1" parent="1">
  <mxGeometry x="20" y="20" width="120" height="60" as="geometry"/></mxGeometry>
</mxCell>
<mxCell id="3" value="Label" style="text;html=1;" vertex="1" parent="1">
  <mxGeometry x="30" y="100" width="160" height="24" as="geometry"/>
</Cell>
        `.trim()

        const result = prepareDiagramXmlForDisplay(rawXml)

        expect(result.valid).toBe(true)
        expect(result.error).toBeNull()
        expect(result.xml).not.toContain("</mxGeometry></mxCell>")
        expect(result.xml).not.toContain("</Cell>")
        expect(result.xml).toContain('id="2"')
        expect(result.xml).toContain('id="3"')
    })
})
