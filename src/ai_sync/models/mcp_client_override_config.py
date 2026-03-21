"""MCP client override config model."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictFloat, StrictInt

from ai_sync.models.oauth_override_config import OAuthOverrideConfig


class McpClientOverrideConfig(BaseModel):
    """Per-client MCP server field overrides from a source artifact."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    method: Literal["stdio", "http", "sse"] | None = None
    command: str | None = None
    args: list[str] | None = None
    url: str | None = None
    auth: dict[str, str] | None = None
    oauth: OAuthOverrideConfig | None = None
    headers: dict[str, str] | None = None
    auth_provider_type: str | None = None
    description: str | None = None
    trust: bool | None = None
    timeout_seconds: StrictInt | StrictFloat | None = None
