"""Service for resolving runtime env from selected artifact dependencies."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from ai_sync.data_classes.runtime_env import RuntimeEnv
from ai_sync.models.env_dependency import EnvDependency
from ai_sync.services.one_password_cli_service import OnePasswordCliService
from ai_sync.services.one_password_secret_service import OnePasswordSecretService


class EnvironmentService:
    """Resolve runtime env from selected dependency declarations."""

    def __init__(self, *, op_secret_service: OnePasswordSecretService) -> None:
        self._op_secret_service = op_secret_service

    def read_existing_env_file(self, project_root: Path) -> dict[str, str]:
        """Read an existing .env.ai-sync file to recover previously filled values."""
        env_path = project_root / ".env.ai-sync"
        if not env_path.exists():
            return {}
        content = env_path.read_text(encoding="utf-8")
        if not content.strip():
            return {}
        return OnePasswordCliService.parse_injected_env(content)

    def resolve_runtime_env(
        self,
        project_root: Path,
        selected_dependencies: Mapping[str, EnvDependency],
        config_root: Path | None,
    ) -> RuntimeEnv:
        existing_env = self.read_existing_env_file(project_root)

        env: dict[str, str] = {}
        env_deps: dict[str, EnvDependency] = {}
        warnings: list[str] = []
        secret_refs: dict[str, str] = {}

        for name in sorted(selected_dependencies):
            dependency = selected_dependencies[name]
            env_deps[name] = dependency
            if dependency.mode == "literal":
                assert dependency.literal is not None
                env[name] = dependency.literal
                continue
            if dependency.mode == "local":
                if name in existing_env and existing_env[name]:
                    env[name] = existing_env[name]
                elif dependency.local_default is not None:
                    env[name] = dependency.local_default
                else:
                    hint = (
                        f" ({dependency.description})"
                        if dependency.description
                        else ""
                    )
                    env_file = project_root / ".env.ai-sync"
                    warnings.append(
                        f"{name}{hint} is local-scoped with no value. "
                        f"Add a line `{name}=...` to {env_file}, then re-run ai-sync."
                    )
                continue
            assert dependency.mode == "secret"
            assert dependency.secret_ref is not None
            secret_refs[name] = dependency.secret_ref

        if secret_refs:
            try:
                env.update(self._op_secret_service.resolve(secret_refs, config_root))
            except Exception as exc:
                warnings.append(f"Failed to resolve selected secret references: {exc}")

        unfilled = {
            name
            for name, dep in env_deps.items()
            if dep.mode == "local" and name not in env
        }
        return RuntimeEnv(
            env=env,
            env_deps=env_deps,
            unfilled_local_vars=unfilled,
            warnings=warnings,
        )
