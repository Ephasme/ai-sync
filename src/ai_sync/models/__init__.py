"""Pydantic models used across ai-sync."""

from ai_sync.models.apply_plan import PLAN_SCHEMA_VERSION, ApplyPlan
from ai_sync.models.env_dependency import EnvDependency, parse_env_dependencies
from ai_sync.models.mcp_client_override_config import McpClientOverrideConfig
from ai_sync.models.mcp_server_config import McpServerConfig
from ai_sync.models.oauth_config import OAuthConfig
from ai_sync.models.oauth_override_config import OAuthOverrideConfig
from ai_sync.models.plan_action import PlanAction
from ai_sync.models.plan_source import PlanSource
from ai_sync.models.project_manifest import (
    DEFAULT_PROJECT_MANIFEST_FILENAME,
    LOCAL_PROJECT_MANIFEST_FILENAME,
    PROJECT_MANIFEST_FILENAMES,
    ProjectManifest,
    split_scoped_ref,
)
from ai_sync.models.requirement import Requirement
from ai_sync.models.requirement_version import RequirementVersion
from ai_sync.models.requirements_manifest import RequirementsManifest
from ai_sync.models.source_config import SourceConfig

__all__ = [
    "ApplyPlan",
    "DEFAULT_PROJECT_MANIFEST_FILENAME",
    "EnvDependency",
    "LOCAL_PROJECT_MANIFEST_FILENAME",
    "McpClientOverrideConfig",
    "McpServerConfig",
    "OAuthConfig",
    "OAuthOverrideConfig",
    "PLAN_SCHEMA_VERSION",
    "PROJECT_MANIFEST_FILENAMES",
    "PlanAction",
    "PlanSource",
    "ProjectManifest",
    "Requirement",
    "RequirementVersion",
    "RequirementsManifest",
    "SourceConfig",
    "parse_env_dependencies",
    "split_scoped_ref",
]
