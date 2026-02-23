"""Pydantic models for manifest validation."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, StrictFloat, StrictInt, field_validator, model_validator


class OAuthConfig(BaseModel):
    enabled: bool = False
    clientId: str | None = None
    clientSecret: str | None = None
    scopes: list[str] = Field(default_factory=list)


class ServerConfig(BaseModel):
    method: Literal["stdio", "http", "sse"] = "stdio"
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    url: str | None = None
    httpUrl: str | None = None
    enabled: bool = True
    clients: list[str] | None = None
    description: str | None = None
    trust: bool | None = None
    timeout_seconds: StrictInt | StrictFloat | None = None
    env: dict[str, str] = Field(default_factory=dict)
    auth: dict[str, str] = Field(default_factory=dict)
    oauth: OAuthConfig = Field(default_factory=OAuthConfig)

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

    @field_validator("timeout_seconds")
    @classmethod
    def validate_timeout_seconds(cls, value: int | float | None):
        if value is None:
            return value
        if value < 0:
            raise ValueError("timeout_seconds must be >= 0")
        return value


class GlobalConfig(BaseModel):
    instructions: str | None = None


class MCPManifest(BaseModel):
    global_: GlobalConfig = Field(default_factory=GlobalConfig, alias="global")
    servers: dict[str, ServerConfig] = Field(default_factory=dict)
