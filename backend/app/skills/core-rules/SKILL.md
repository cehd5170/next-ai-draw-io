---
name: core-rules
description: Core rules for diagram tool selection and XML generation. Load this for every diagram request.
tags: [always, tools, xml, rules]
---

# Core Diagram Rules

## Tool Selection

- `display_diagram`: Create a NEW diagram or major restructure. Use when current XML is empty or structural changes needed.
- `edit_diagram`: Small targeted changes — add/remove/rename elements, adjust colours, move items.
- `append_diagram`: ONLY when a previous `display_diagram` response says the XML was truncated. Never use otherwise.
- `get_shape_library`: Load icon documentation BEFORE creating diagrams with cloud/tech icons (AWS, Azure, GCP, K8s, etc.). Never guess icon syntax.

CRITICAL:
- Always use tool calls — never return raw XML in text responses.
- Never call `edit_diagram` right after `display_diagram` in the same response.
- Never include XML comments (`<!-- ... -->`) in generated XML.
- After tool calls, do not add commentary.
- Respond in the same language as the user's message.

## Draw.io XML Structure

Generate ONLY `mxCell` elements — NO wrapper tags (`<mxfile>`, `<mxGraphModel>`, `<root>`).
Do NOT include root cells (id="0" or id="1") — they are added automatically.
ALL mxCell elements must be siblings — NEVER nest mxCell inside another mxCell.
Use unique sequential IDs starting from "2".
Set `parent="1"` for top-level shapes, or `parent="<container-id>"` for grouped elements.

Shape example:
```xml
<mxCell id="2" value="Label" style="rounded=1;whiteSpace=wrap;html=1;" vertex="1" parent="1">
  <mxGeometry x="100" y="100" width="120" height="60" as="geometry"/>
</mxCell>
```

Edge example:
```xml
<mxCell id="3" style="edgeStyle=orthogonalEdgeStyle;exitX=1;exitY=0.5;entryX=0;entryY=0.5;endArrow=classic;html=1;" edge="1" parent="1" source="2" target="4">
  <mxGeometry relative="1" as="geometry"/>
</mxCell>
```

## Layout

Auto-layout is applied on the server — focus on correct parent-child relationships and edge source/target, not pixel-perfect coordinates.
