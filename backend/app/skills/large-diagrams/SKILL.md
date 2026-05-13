---
name: large-diagrams
description: Strategy for generating large or complex diagrams that may exceed output limits. Load when user requests diagrams from papers, complex systems, or very detailed topics.
tags: [large, truncation, append_diagram, complex]
---

# Large Diagram Strategy

## Generation Rules

- Generate ALL components in a single `display_diagram` call — do NOT simplify or omit elements
- Prefer MORE detail over less — users can always ask to simplify
- For papers/technical topics: include every major concept, layer, data flow, and relationship
- When a diagram has 20+ nodes, spread them across a larger canvas rather than packing tightly

## Handling Truncation

If your output is truncated mid-generation:
1. The server will inform you that the XML was truncated
2. Call `append_diagram` to continue from where you stopped
3. `append_diagram` takes continuation fragments — NO wrapper tags like `<mxGraphModel>` or `<root>`
4. Continue adding `mxCell` elements until the diagram is complete

NEVER call `append_diagram` proactively — only use it when explicitly instructed after a truncation.
