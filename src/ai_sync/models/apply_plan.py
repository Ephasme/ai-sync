"""Apply plan model."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ai_sync.models.plan_action import PlanAction
from ai_sync.models.plan_source import PlanSource

PLAN_SCHEMA_VERSION = 3


class ApplyPlan(BaseModel):
    schema_version: int = PLAN_SCHEMA_VERSION
    created_at: str
    project_root: str
    manifest_path: str
    manifest_fingerprint: str
    sources: list[PlanSource] = Field(default_factory=list)
    selections: dict[str, list[str]] = Field(default_factory=dict)
    settings: dict[str, Any] = Field(default_factory=dict)
    actions: list[PlanAction] = Field(default_factory=list)
