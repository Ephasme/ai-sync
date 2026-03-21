"""Top-level dependency container for ai-sync."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Mapping
from typing import TextIO

from dependency_injector import containers, providers

from ai_sync.adapters.filesystem import FileSystem
from ai_sync.adapters.process_runner import ProcessRunner
from ai_sync.clients import ClientFactory
from ai_sync.services.agent_artifact_service import AgentArtifactService
from ai_sync.services.apply_service import ApplyService
from ai_sync.services.artifact_bundle_service import ArtifactBundleService
from ai_sync.services.artifact_preparation_service import ArtifactPreparationService
from ai_sync.services.artifact_service import ArtifactService
from ai_sync.services.command_artifact_service import CommandArtifactService
from ai_sync.services.config_store_service import ConfigStoreService
from ai_sync.services.doctor_service import DoctorService
from ai_sync.services.environment_service import EnvironmentService
from ai_sync.services.error_handler_service import ErrorHandlerService
from ai_sync.services.git_safety_service import GitSafetyService
from ai_sync.services.git_source_fetcher_service import GitSourceFetcherService
from ai_sync.services.install_service import InstallService
from ai_sync.services.managed_output_service import ManagedOutputService
from ai_sync.services.mcp_artifact_service import McpArtifactService
from ai_sync.services.mcp_preparation_service import McpPreparationService
from ai_sync.services.one_password_auth_service import OnePasswordAuthService
from ai_sync.services.one_password_cli_service import OnePasswordCliService
from ai_sync.services.one_password_sdk_service import OnePasswordSdkService
from ai_sync.services.one_password_secret_service import OnePasswordSecretService
from ai_sync.services.plan_builder_service import PlanBuilderService
from ai_sync.services.plan_persistence_service import PlanPersistenceService
from ai_sync.services.plan_service import PlanService
from ai_sync.services.project_artifact_service import ProjectArtifactService
from ai_sync.services.project_locator_service import ProjectLocatorService
from ai_sync.services.project_manifest_service import ProjectManifestService
from ai_sync.services.rule_artifact_service import RuleArtifactService
from ai_sync.services.skill_artifact_service import SkillArtifactService
from ai_sync.services.source_catalog_service import SourceCatalogService
from ai_sync.services.source_fingerprint_service import SourceFingerprintService
from ai_sync.services.source_resolver_service import SourceResolverService
from ai_sync.services.tool_requirement_service import ToolRequirementService
from ai_sync.services.tool_version_service import ToolVersionService
from ai_sync.services.uninstall_service import UninstallService


class AppContainer(containers.DeclarativeContainer):
    """Application dependency container."""

    config = providers.Configuration()

    runtime_environ: providers.Object[Mapping[str, str]] = providers.Object(os.environ)
    runtime_stdin: providers.Object[TextIO] = providers.Object(sys.stdin)
    prompt_input: providers.Object[Callable[[str], str]] = providers.Object(input)

    process_runner = providers.Singleton(ProcessRunner)
    filesystem = providers.Singleton(FileSystem)
    client_factory = providers.Singleton(ClientFactory)
    artifact_bundle_service = providers.Singleton(ArtifactBundleService)
    agent_artifact_service = providers.Singleton(
        AgentArtifactService,
        artifact_bundle_service=artifact_bundle_service,
    )
    command_artifact_service = providers.Singleton(
        CommandArtifactService,
        artifact_bundle_service=artifact_bundle_service,
    )
    skill_artifact_service = providers.Singleton(
        SkillArtifactService,
        artifact_bundle_service=artifact_bundle_service,
    )
    rule_artifact_service = providers.Singleton(
        RuleArtifactService,
        artifact_bundle_service=artifact_bundle_service,
    )
    mcp_artifact_service = providers.Singleton(McpArtifactService)
    project_artifact_service = providers.Singleton(ProjectArtifactService)
    artifact_service = providers.Singleton(
        ArtifactService,
        agent_artifact_service=agent_artifact_service,
        command_artifact_service=command_artifact_service,
        skill_artifact_service=skill_artifact_service,
        rule_artifact_service=rule_artifact_service,
        mcp_artifact_service=mcp_artifact_service,
        project_artifact_service=project_artifact_service,
    )

    config_store_service = providers.Singleton(
        ConfigStoreService,
        environ=runtime_environ,
    )
    git_safety_service = providers.Singleton(GitSafetyService)
    project_locator_service = providers.Singleton(ProjectLocatorService)
    project_manifest_service = providers.Singleton(ProjectManifestService)
    mcp_preparation_service = providers.Singleton(McpPreparationService)
    tool_version_service = providers.Singleton(ToolVersionService)
    tool_requirement_service = providers.Singleton(
        ToolRequirementService,
        version_check_service=tool_version_service,
    )
    plan_persistence_service = providers.Singleton(PlanPersistenceService)
    managed_output_service = providers.Singleton(ManagedOutputService)
    plan_builder_service = providers.Singleton(
        PlanBuilderService,
        artifact_service=artifact_service,
        git_safety_service=git_safety_service,
        managed_output_service=managed_output_service,
        client_factory=client_factory,
    )

    source_fingerprint_service = providers.Singleton(
        SourceFingerprintService,
        process_runner=process_runner,
        filesystem=filesystem,
    )
    git_source_fetcher_service = providers.Singleton(
        GitSourceFetcherService,
        process_runner=process_runner,
        filesystem=filesystem,
    )
    source_resolver_service = providers.Singleton(
        SourceResolverService,
        git_fetcher=git_source_fetcher_service,
        fingerprinter=source_fingerprint_service,
    )
    source_catalog_service = providers.Singleton(
        SourceCatalogService,
        artifact_bundle_service=artifact_bundle_service,
    )

    one_password_auth_service = providers.Singleton(
        OnePasswordAuthService,
        config_store_service=config_store_service,
    )
    one_password_cli_service = providers.Singleton(
        OnePasswordCliService,
        process_runner=process_runner,
        auth_resolver=one_password_auth_service,
    )
    one_password_sdk_service = providers.Singleton(
        OnePasswordSdkService,
        auth_resolver=one_password_auth_service,
    )
    one_password_secret_service = providers.Singleton(
        OnePasswordSecretService,
        cli_injector=one_password_cli_service,
        sdk_resolver=one_password_sdk_service,
        environ=runtime_environ,
    )

    environment_service = providers.Singleton(
        EnvironmentService,
        op_secret_service=one_password_secret_service,
    )

    error_handler_service = providers.Singleton(ErrorHandlerService)

    artifact_preparation_service = providers.Singleton(
        ArtifactPreparationService,
        mcp_preparation_service=mcp_preparation_service,
        artifact_bundle_service=artifact_bundle_service,
        environment_service=environment_service,
    )

    plan_service = providers.Singleton(
        PlanService,
        source_resolver_service=source_resolver_service,
        artifact_preparation_service=artifact_preparation_service,
        project_locator_service=project_locator_service,
        project_manifest_service=project_manifest_service,
        tool_requirement_service=tool_requirement_service,
        plan_builder_service=plan_builder_service,
        plan_persistence_service=plan_persistence_service,
        config_store_service=config_store_service,
        tool_version_service=tool_version_service,
    )

    install_service = providers.Factory(
        InstallService,
        config_store_service=config_store_service,
        environ=runtime_environ,
        stdin=runtime_stdin,
        prompt_input=prompt_input,
    )

    apply_service = providers.Singleton(
        ApplyService,
        managed_output_service=managed_output_service,
        git_safety_service=git_safety_service,
        plan_service=plan_service,
        plan_persistence_service=plan_persistence_service,
        project_locator_service=project_locator_service,
        config_store_service=config_store_service,
        tool_version_service=tool_version_service,
        stdin=runtime_stdin,
        prompt_input=prompt_input,
    )

    uninstall_service = providers.Singleton(
        UninstallService,
        git_safety_service=git_safety_service,
        project_locator_service=project_locator_service,
        managed_output_service=managed_output_service,
    )

    doctor_service = providers.Factory(
        DoctorService,
        config_store_service=config_store_service,
        git_safety_service=git_safety_service,
        project_locator_service=project_locator_service,
        project_manifest_service=project_manifest_service,
        plan_service=plan_service,
        environ=runtime_environ,
    )
