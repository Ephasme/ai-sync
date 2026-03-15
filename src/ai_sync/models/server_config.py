"""MCP server configuration model."""

from typing import Literal

from pydantic import BaseModel, Field, StrictFloat, StrictInt, field_validator, model_validator

from ai_sync.models.client_override_config import ClientOverrideConfig
from ai_sync.models.oauth_config import OAuthConfig


class ServerConfig(BaseModel):
    name: str
    method: Literal["stdio", "http", "sse"] = "stdio"
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    url: str | None = None
    description: str
    trust: bool | None = None
    timeout_seconds: StrictInt | StrictFloat | None = None
    env: dict[str, str] = Field(default_factory=dict)
    auth: dict[str, str] = Field(default_factory=dict)
    oauth: OAuthConfig = Field(default_factory=OAuthConfig)
    headers: dict[str, str] = Field(default_factory=dict)
    auth_provider_type: str | None = None
    client_overrides: dict[str, ClientOverrideConfig] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def reject_legacy_timeout(cls, data):
        if isinstance(data, dict) and "timeout" in data:
            raise ValueError("timeout is no longer supported; use timeout_seconds")
        return data

    @field_validator("command")
    @classmethod
    def validate_command_for_stdio(cls, value: str | None, info):
        method = info.data.get("method", "stdio")
        if method == "stdio" and (value is None or not str(value).strip()):
            raise ValueError("stdio servers must define command")
        return value

    @field_validator("name", "description")
    @classmethod
    def validate_required_text(cls, value: str, info):
        if not value.strip():
            raise ValueError(f"{info.field_name} must not be blank")
        return value

    @field_validator("timeout_seconds")
    @classmethod
    def validate_timeout_seconds(cls, value: int | float | None):
        if value is None:
            return value
        if value < 0:
            raise ValueError("timeout_seconds must be >= 0")
        return value
