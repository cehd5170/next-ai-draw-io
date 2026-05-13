---
name: diagram-creation
description: Visual quality standards and detail level for creating draw.io diagrams. Load for new diagram creation requests.
tags: [creation, quality, layout, sizing]
---

# Diagram Creation Standards

## Detail Level

CRITICAL: Always generate DETAILED, COMPREHENSIVE diagrams:
- Include ALL relevant components and sub-components (not just top-level boxes)
- Include internal elements within containers (layers inside an encoder, steps inside a process)
- Add ALL connections/edges with descriptive labels
- Use proper grouping with parent-child relationships (swimlanes, containers)
- A typical architecture diagram should have 15–40+ elements — never just 2–4 boxes

## Visual Quality

- Prefer real library icons over plain rectangles for cloud/tech/infrastructure diagrams
- Use containers, swimlanes, zones, and labeled groups to create hierarchy
- Mix visual primitives: icons for services, containers for domains, rounded boxes for processes, diamonds for decisions, cylinders for databases
- Keep labels short on canvas — use layout and grouping to communicate structure
- Avoid "wall of same-size boxes" layouts unless user explicitly asks for a simple wireframe
- Treat layout as hierarchical composition: groups first, leaf nodes second, connectors last

## Node Sizing

- Short labels (1–3 words): width=120–160, height=40–60
- Medium labels (4–8 words): width=180–240, height=50–70
- Long labels (9+ words): width=260–360, height=60–80
- Containers/swimlanes: large enough to hold all children with 20px padding on each side
- Never cram long text into a small box — widen the box or shorten the label

## Edge Routing

- Always set `exitX`, `exitY`, `entryX`, `entryY` explicitly on every edge
- Default to `edgeStyle=orthogonalEdgeStyle` unless diagram clearly calls for curved/straight
- For overlapping edges, use different `exitY`/`entryY` values (e.g. 0.3 and 0.7) or add waypoints
