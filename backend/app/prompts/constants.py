"""
Constants for the prompts module: shape library names and tool JSON schemas.
These schemas are used by both the prompt builder and litellm function calling.
"""

# All available shape/icon library names
SHAPE_LIBRARY_NAMES: list[str] = [
    "aws4",
    "azure2",
    "gcp2",
    "kubernetes",
    "cisco19",
    "flowchart",
    "bpmn",
    "material_design",
    "webicons",
    "network",
    "ios7",
    "android",
    "bootstrap",
    "electrical",
    "floorplan",
    "lean_mapping",
    "mockup",
    "infographic",
    "uml",
    "er",
    "archimate3",
    "c4",
    "veeam",
    "rack",
    "office",
]

# JSON Schema definitions for all four diagram tools.
# The "parameters" value is the JSON Schema object passed to the LLM.
TOOL_SCHEMAS: dict[str, dict] = {
    "display_diagram": {
        "name": "display_diagram",
        "description": (
            "Display a NEW diagram on draw.io. Use this when creating a diagram from scratch "
            "or when major structural changes are needed."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "xml": {
                    "type": "string",
                    "description": (
                        "draw.io XML containing ONLY mxCell elements (no wrapper tags). "
                        "IDs must start from '2'. Root cells (id='0', id='1') are added automatically."
                    ),
                }
            },
            "required": ["xml"],
            "additionalProperties": False,
        },
    },
    "edit_diagram": {
        "name": "edit_diagram",
        "description": (
            "Edit specific parts of the EXISTING diagram. Use this when making small targeted "
            "changes like adding/removing elements, changing labels, or adjusting properties. "
            "More efficient than regenerating the entire diagram."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "operations": {
                    "type": "array",
                    "description": "List of cell-level operations to apply in order.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "operation": {
                                "type": "string",
                                "enum": ["update", "add", "delete"],
                                "description": (
                                    "update: replace an existing cell; "
                                    "add: insert a new cell; "
                                    "delete: remove a cell (children and edges auto-deleted)."
                                ),
                            },
                            "cell_id": {
                                "type": "string",
                                "description": (
                                    "The id attribute of the target mxCell. "
                                    "For 'add', supply the new unique id you want to assign."
                                ),
                            },
                            "new_xml": {
                                "type": ["string", "null"],
                                "description": (
                                    "Complete mxCell element string for update/add operations. "
                                    "Must be null (or omitted) for delete operations. "
                                    "Every \" inside the XML must be escaped as \\\"."
                                ),
                            },
                        },
                        "required": ["operation", "cell_id"],
                        "additionalProperties": False,
                    },
                    "minItems": 1,
                }
            },
            "required": ["operations"],
            "additionalProperties": False,
        },
    },
    "append_diagram": {
        "name": "append_diagram",
        "description": (
            "Continue generating diagram XML when display_diagram was truncated due to output "
            "length limits. Only use this after a display_diagram truncation."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "xml": {
                    "type": "string",
                    "description": (
                        "Continuation fragment containing ONLY mxCell elements — "
                        "NO wrapper tags like <mxGraphModel> or <root>. "
                        "Continue from exactly where the previous output was cut off."
                    ),
                }
            },
            "required": ["xml"],
            "additionalProperties": False,
        },
    },
    "get_shape_library": {
        "name": "get_shape_library",
        "description": (
            "Get shape/icon library documentation. Use this to discover available icon shapes "
            "(AWS, Azure, GCP, Kubernetes, Material Design, etc.) before creating diagrams with "
            "special icons. ALWAYS call this before using any icon library — never guess the syntax."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "library": {
                    "type": "string",
                    "description": (
                        "Library name. Available libraries: "
                        + ", ".join(SHAPE_LIBRARY_NAMES)
                    ),
                    "enum": SHAPE_LIBRARY_NAMES,
                }
            },
            "required": ["library"],
            "additionalProperties": False,
        },
    },
}
