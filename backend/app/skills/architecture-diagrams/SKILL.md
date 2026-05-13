---
name: architecture-diagrams
description: Workflow for creating architecture, cloud, infrastructure, platform, or system design diagrams with icon libraries. Load when request involves AWS, Azure, GCP, Kubernetes, or system architecture.
tags: [architecture, cloud, aws, azure, gcp, kubernetes, infrastructure, icons]
---

# Architecture Diagram Workflow

For architecture, platform, infrastructure, cloud, API, or system design requests:

1. Identify the main layers, domains, or zones first
2. If the request matches a known icon library, call `get_shape_library` before placing service nodes
3. Create containers, swimlanes, and grouped regions before placing leaf nodes
4. Place icon/service/database/queue nodes inside those groups with short labels
5. Add orthogonal edges after the main layout is stable

Do not start rich architecture diagrams by scattering many independent rounded rectangles.

## Icon Library Triggers

Call `get_shape_library` when the request mentions:
- AWS, Azure, GCP, Google Cloud → libraries: `aws4`, `azure2`, `gcp2`
- Kubernetes, containers, Docker → library: `kubernetes`
- Network, Cisco → library: `cisco19`
- BPMN processes → library: `bpmn`
- Material Design, Android → library: `material_design`
- Flowcharts → library: `flowchart`

NEVER guess icon style syntax — always call `get_shape_library` first.
