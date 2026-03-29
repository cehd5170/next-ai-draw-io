"""
Request/response schemas for the /chat endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Message parts
# ---------------------------------------------------------------------------


class TextPart(BaseModel):
    """A plain-text message part."""

    type: Literal["text"] = "text"
    text: str


class ImagePart(BaseModel):
    """An inline image message part (base-64 data URL or remote URL).

    Accepts both AI SDK field names (``url``, ``mediaType``) and legacy
    field names (``data``, ``mimeType``).
    """

    type: Literal["image"] = "image"
    data: str = Field(default="", description="Base-64 encoded image bytes or a remote URL")
    url: str = Field(default="", description="Alias for data (AI SDK format)")
    mime_type: str = Field(
        default="image/png",
        alias="mimeType",
        description="MIME type of the image (e.g. image/png, image/jpeg)",
    )
    media_type: str = Field(
        default="",
        alias="mediaType",
        description="Alias for mimeType (AI SDK format)",
    )

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def _normalise_aliases(self) -> "ImagePart":
        """Ensure ``data`` and ``mime_type`` are populated from their aliases."""
        if not self.data and self.url:
            self.data = self.url
        if self.media_type and self.mime_type == "image/png":
            self.mime_type = self.media_type
        return self


class FilePart(BaseModel):
    """A file attachment message part.

    Accepts both AI SDK field names (``url``, ``mediaType``) and legacy
    field names (``data``, ``mimeType``).
    """

    type: Literal["file"] = "file"
    data: str = Field(default="", description="Base-64 encoded file bytes")
    url: str = Field(default="", description="Alias for data (AI SDK format)")
    mime_type: str = Field(
        default="",
        alias="mimeType",
        description="MIME type of the file (e.g. application/pdf)",
    )
    media_type: str = Field(
        default="",
        alias="mediaType",
        description="Alias for mimeType (AI SDK format)",
    )
    name: Optional[str] = Field(default=None, description="Original filename")

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def _normalise_aliases(self) -> "FilePart":
        """Ensure ``data`` and ``mime_type`` are populated from their aliases."""
        if not self.data and self.url:
            self.data = self.url
        if not self.mime_type and self.media_type:
            self.mime_type = self.media_type
        return self


# Union alias used in ChatRequest
MessagePart = TextPart | ImagePart | FilePart


# ---------------------------------------------------------------------------
# Chat request
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    """
    Request body for POST /api/chat.

    ``messages`` mirrors the AI SDK UIMessage format – each message is a
    dict so that we stay compatible with the existing frontend payload.
    ``xml`` is the *current* draw.io XML (authoritative source of truth).
    """

    messages: list[dict[str, Any]] = Field(
        ...,
        description="Conversation history in AI SDK UIMessage format",
    )
    xml: str = Field(
        default="",
        description="Current draw.io diagram XML (authoritative)",
    )
    previousXml: Optional[str] = Field(
        default=None,
        description="Diagram XML before the user's last change (for diff context)",
    )
    sessionId: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Session identifier for Langfuse tracing",
    )
    customSystemMessage: Optional[str] = Field(
        default=None,
        max_length=5000,
        description="User-supplied instructions appended to the system prompt",
    )
    pdfMode: Optional[Literal["text", "base64"]] = Field(
        default=None,
        description="How PDF attachments should be sent to the model (None = use server default PDF_INPUT_MODE)",
    )

    @field_validator("customSystemMessage", mode="before")
    @classmethod
    def _truncate_custom_system_message(cls, v: object) -> Optional[str]:
        if v is None:
            return None
        if not isinstance(v, str):
            return None
        # Hard truncation at 5000 chars; Pydantic max_length enforces it too,
        # but we silently truncate rather than reject to match JS behaviour.
        return v[:5000]


# ---------------------------------------------------------------------------
# Tool call inputs
# ---------------------------------------------------------------------------


class DisplayDiagramInput(BaseModel):
    """Input schema for the display_diagram tool."""

    xml: str = Field(..., description="mxCell XML elements to display on the canvas")
    layout: Optional[
        Literal[
            "none",
            "mxHierarchicalLayout",
            "mxFastOrganicLayout",
            "mxCircleLayout",
            "mxCompactTreeLayout",
            "mxRadialTreeLayout",
        ]
    ] = Field(
        default=None,
        description="Optional auto-layout algorithm to apply after rendering",
    )


class EditOperation(BaseModel):
    """A single cell-level edit operation."""

    operation: Literal["update", "add", "delete"]
    cell_id: str = Field(..., description="ID of the mxCell to act on")
    new_xml: Optional[str] = Field(
        default=None,
        description="Complete mxCell XML (required for update / add)",
    )


class EditDiagramInput(BaseModel):
    """Input schema for the edit_diagram tool."""

    operations: list[EditOperation] = Field(
        ...,
        description="Ordered list of cell operations to apply",
    )


class AppendDiagramInput(BaseModel):
    """Input schema for the append_diagram tool (handles truncated output)."""

    xml: str = Field(
        ...,
        description="Continuation XML fragment (no wrapper tags)",
    )


class GetShapeLibraryInput(BaseModel):
    """Input schema for the get_shape_library tool."""

    library: str = Field(
        ...,
        description="Shape library name (e.g. 'aws4', 'kubernetes', 'flowchart')",
    )


# Union of all tool call inputs
ToolCallInput = DisplayDiagramInput | EditDiagramInput | AppendDiagramInput | GetShapeLibraryInput


# ---------------------------------------------------------------------------
# Client overrides dataclass
# ---------------------------------------------------------------------------


@dataclass
class ClientOverrides:
    """
    Per-request AI provider overrides extracted from HTTP request headers.

    All fields are ``None`` when the corresponding header is absent, which
    means the server-configured default should be used.
    """

    # Provider / routing
    provider: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model_id: Optional[str] = None
    selected_model_id: Optional[str] = None

    # AWS Bedrock credentials
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[str] = None
    aws_region: Optional[str] = None
    aws_session_token: Optional[str] = None

    # Google Vertex AI (Express Mode)
    vertex_api_key: Optional[str] = None

    # UI preferences
    minimal_style: bool = False

    @property
    def has_own_api_key(self) -> bool:
        """Return True when the client has supplied its own credentials."""
        return bool(
            self.provider
            and (self.api_key or self.aws_access_key_id or self.vertex_api_key)
        )
