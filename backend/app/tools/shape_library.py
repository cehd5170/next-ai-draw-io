"""
get_shape_library tool — return shape/icon library documentation.

The markdown files live in ``context.shape_library_dir``.  A path-traversal
check ensures that even a malicious library name cannot escape that directory.
"""
from __future__ import annotations

import re
from pathlib import Path

from app.tools.registry import Tool, ToolContext, ToolResult, register_tool
from app.prompts.constants import TOOL_SCHEMAS, SHAPE_LIBRARY_NAMES

# ── Sanitisation ──────────────────────────────────────────────────────────────

_SAFE_NAME_RE = re.compile(r"^[a-z0-9_-]+$")


def _sanitise_library_name(name: str) -> str:
    """Lowercase and strip *name* to the safe character set [a-z0-9_-]."""
    return name.lower().strip()


# ── Execution ─────────────────────────────────────────────────────────────────

async def execute_shape_library(params: dict, context: ToolContext) -> ToolResult:
    """
    Return the markdown documentation for a shape/icon library.
    """
    library: str = params.get("library", "")

    # 1. Non-empty check.
    if not library or not library.strip():
        return ToolResult(
            success=False,
            content=(
                "Parameter 'library' must be a non-empty string.  "
                f"Available libraries: {', '.join(AVAILABLE_LIBRARIES)}."
            ),
        )

    # 2. Sanitise: lowercase, only a-z0-9_-
    sanitised = _sanitise_library_name(library)
    if not _SAFE_NAME_RE.match(sanitised):
        return ToolResult(
            success=False,
            content=(
                f"Library name '{library}' contains invalid characters.  "
                "Only letters, digits, underscores, and hyphens are allowed.  "
                f"Available libraries: {', '.join(AVAILABLE_LIBRARIES)}."
            ),
        )

    # 3. Check against allow-list.
    if sanitised not in AVAILABLE_LIBRARIES:
        return ToolResult(
            success=False,
            content=(
                f"Unknown library '{sanitised}'.  "
                f"Available libraries: {', '.join(AVAILABLE_LIBRARIES)}."
            ),
        )

    # 4. Resolve path and perform traversal check.
    base_dir = Path(context.shape_library_dir).resolve()
    candidate = (base_dir / f"{sanitised}.md").resolve()

    if not str(candidate).startswith(str(base_dir)):
        return ToolResult(
            success=False,
            content=f"Invalid library path for '{sanitised}' (path traversal detected).",
        )

    # 5. Read the markdown file.
    if not candidate.exists():
        return ToolResult(
            success=False,
            content=(
                f"Documentation file for library '{sanitised}' was not found on the server.  "
                f"Available libraries: {', '.join(AVAILABLE_LIBRARIES)}."
            ),
        )

    try:
        content = candidate.read_text(encoding="utf-8")
    except OSError as exc:
        return ToolResult(
            success=False,
            content=f"Could not read documentation for library '{sanitised}': {exc}",
        )

    if not content.strip():
        return ToolResult(
            success=False,
            content=f"Documentation file for library '{sanitised}' is empty.",
        )

    return ToolResult(
        success=True,
        content=content,
    )


# ── Available libraries ───────────────────────────────────────────────────────
# Use the canonical list from prompts/constants.py as the single source of
# truth; the list below is kept as an explicit module-level constant for
# convenience (used in error messages above).

AVAILABLE_LIBRARIES: list[str] = list(SHAPE_LIBRARY_NAMES)

# Additional libraries not yet in the shared constant can be appended here:
_EXTRA: list[str] = [
    "alibaba_cloud", "openstack", "salesforce",
    "vvd",
    "lean_mapping",
    "arrows2", "infographic", "sitemap",
    "material_design",
    "citrix", "sap", "mscae", "atlassian",
    "fluidpower", "pid", "cabinets",
    "webicons",
]
for _lib in _EXTRA:
    if _lib not in AVAILABLE_LIBRARIES:
        AVAILABLE_LIBRARIES.append(_lib)


# ── Registration ──────────────────────────────────────────────────────────────

_schema = TOOL_SCHEMAS["get_shape_library"]

register_tool(
    Tool(
        name=_schema["name"],
        description=_schema["description"],
        parameters=_schema["parameters"],
        execute=execute_shape_library,
    )
)
