---
name: xml-editing
description: Guide for using edit_diagram operations (update/add/delete). Load when user asks to modify, change, or update an existing diagram.
tags: [editing, edit_diagram, operations]
---

# edit_diagram Operations Guide

Use `edit_diagram` for small targeted changes to an existing diagram. It is more efficient than regenerating the whole diagram.

## Operations

- **update**: modify an existing cell — provide `cell_id` and complete `new_xml`
- **add**: insert a new cell — provide `cell_id` (new unique id) and `new_xml`
- **delete**: remove a cell — only `cell_id` needed (children and connected edges are auto-deleted)

Find cell IDs from the "Current Diagram XML" in the system context.

## Examples

Update:
```json
{"operations": [{"operation": "update", "cell_id": "3", "new_xml": "<mxCell id=\"3\" value=\"New Label\" style=\"rounded=1;\" vertex=\"1\" parent=\"1\">\n  <mxGeometry x=\"100\" y=\"100\" width=\"120\" height=\"60\" as=\"geometry\"/>\n</mxCell>"}]}
```

Delete:
```json
{"operations": [{"operation": "delete", "cell_id": "5"}]}
```

Add:
```json
{"operations": [{"operation": "add", "cell_id": "new1", "new_xml": "<mxCell id=\"new1\" value=\"New Box\" style=\"rounded=1;\" vertex=\"1\" parent=\"1\">\n  <mxGeometry x=\"400\" y=\"200\" width=\"120\" height=\"60\" as=\"geometry\"/>\n</mxCell>"}]}
```

⚠️ JSON ESCAPING: Every `"` inside `new_xml` MUST be escaped as `\"`.
