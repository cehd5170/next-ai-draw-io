---
name: shape-libraries
description: How to use the get_shape_library tool to load draw.io icon/shape library documentation. Load when user wants icons, logos, or library shapes.
tags: [shapes, icons, libraries, get_shape_library]
---

# Shape Library Usage

Use `get_shape_library` to load documentation for draw.io icon libraries before creating diagrams with special shapes.

## Available Libraries

| Library key | Contents |
|---|---|
| `aws4` | AWS service icons (EC2, S3, Lambda, RDS, etc.) |
| `azure2` | Azure service icons |
| `gcp2` | Google Cloud Platform icons |
| `kubernetes` | Kubernetes resource icons |
| `cisco19` | Cisco network device icons |
| `flowchart` | Standard flowchart symbols |
| `bpmn` | BPMN process diagram shapes |
| `material_design` | Material Design icons |

## Workflow

1. Call `get_shape_library` with the appropriate library key
2. Read the returned documentation to understand correct style syntax
3. Use those exact styles in your `display_diagram` or `edit_diagram` call

NEVER guess or invent icon style strings — always consult the library documentation first.
