"""Artifact-scoped dependency models and parsing."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import ValidationError

from ai_sync.models.binary_dependency import BinaryDependency

ENV_VAR_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")


@dataclass(frozen=True)
class EnvDependency:
    """Normalized env dependency for a single env var."""

    name: str
    mode: Literal["literal", "local", "secret"]
    description: str | None = None
    literal: str | None = None
    local_default: str | None = None
    secret_provider: Literal["op"] | None = None
    secret_ref: str | None = None

    def semantic_key(self) -> tuple[str, str | None, str | None, str | None, str | None]:
        """Return a merge key that ignores non-runtime description text."""
        return (
            self.mode,
            self.literal,
            self.local_default,
            self.secret_provider,
            self.secret_ref,
        )


def _parse_dependencies_env_section(env_raw: object, *, context: str) -> dict[str, EnvDependency]:
    if env_raw is None:
        return {}
    if not isinstance(env_raw, dict):
        raise RuntimeError(f"{context}: dependencies.env must be a mapping of env var names.")

    parsed: dict[str, EnvDependency] = {}
    for name, entry in env_raw.items():
        if not isinstance(name, str) or not ENV_VAR_NAME_RE.fullmatch(name):
            raise RuntimeError(
                f"{context}: invalid env var name {name!r}; expected pattern "
                f"{ENV_VAR_NAME_RE.pattern!r}."
            )
        parsed[name] = _parse_env_dependency_entry(name, entry, context=context)
    return parsed


@dataclass(frozen=True)
class ArtifactDependencies:
    """Parsed result of an artifact's ``dependencies`` block."""

    env: dict[str, EnvDependency] = field(default_factory=dict)
    binaries: list[BinaryDependency] = field(default_factory=list)


def parse_artifact_dependencies(raw: object, *, context: str) -> ArtifactDependencies:
    """Parse a dependencies block and return normalized env and binary dependencies."""
    if raw is None:
        return ArtifactDependencies()
    if not isinstance(raw, dict):
        raise RuntimeError(f"{context}: dependencies must be a mapping.")
    unknown_top = set(raw) - {"env", "binaries"}
    if unknown_top:
        extras = ", ".join(sorted(str(k) for k in unknown_top))
        raise RuntimeError(
            f"{context}: dependencies supports only 'env' and 'binaries'; found: {extras}."
        )
    env = _parse_dependencies_env_section(raw.get("env"), context=context)
    binaries = _parse_dependencies_binaries_section(raw.get("binaries"), context=context)
    return ArtifactDependencies(env=env, binaries=binaries)


def _parse_dependencies_binaries_section(
    raw: object, *, context: str
) -> list[BinaryDependency]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise RuntimeError(f"{context}: dependencies.binaries must be a list.")
    parsed: list[BinaryDependency] = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise RuntimeError(f"{context}: dependencies.binaries[{i}] must be a mapping.")
        try:
            parsed.append(BinaryDependency.model_validate(entry))
        except ValidationError as exc:
            raise RuntimeError(
                f"{context}: dependencies.binaries[{i}] validation failed: {exc}"
            ) from exc
    return parsed


def _parse_env_dependency_entry(name: str, entry: object, *, context: str) -> EnvDependency:
    if isinstance(entry, str):
        return EnvDependency(name=name, mode="literal", literal=entry)
    if not isinstance(entry, dict):
        raise RuntimeError(
            f"{context}: env dependency {name!r} must be a scalar string or mapping."
        )

    unknown_fields = set(entry) - {"local", "secret", "description"}
    if unknown_fields:
        extras = ", ".join(sorted(str(k) for k in unknown_fields))
        raise RuntimeError(
            f"{context}: env dependency {name!r} supports only "
            f"'local', 'secret', and 'description'; found: {extras}."
        )

    description = entry.get("description")
    if description is not None and not isinstance(description, str):
        raise RuntimeError(
            f"{context}: env dependency {name!r} description must be a string."
        )

    has_local = "local" in entry
    has_secret = "secret" in entry
    if has_local == has_secret:
        raise RuntimeError(
            f"{context}: env dependency {name!r} must define exactly one of "
            "'local' or 'secret'."
        )

    if has_local:
        local = entry.get("local")
        if not isinstance(local, dict):
            raise RuntimeError(
                f"{context}: env dependency {name!r} local must be a mapping "
                "(use local: {{}} when no default is needed)."
            )
        unknown_local = set(local) - {"default"}
        if unknown_local:
            extras = ", ".join(sorted(str(k) for k in unknown_local))
            raise RuntimeError(
                f"{context}: env dependency {name!r} local supports only "
                f"'default'; found: {extras}."
            )
        default = local.get("default")
        if default is not None and not isinstance(default, str):
            raise RuntimeError(
                f"{context}: env dependency {name!r} local.default must be a string."
            )
        return EnvDependency(
            name=name,
            mode="local",
            description=description,
            local_default=default,
        )

    secret = entry.get("secret")
    if not isinstance(secret, dict):
        raise RuntimeError(
            f"{context}: env dependency {name!r} secret must be a mapping."
        )
    unknown_secret = set(secret) - {"provider", "ref"}
    if unknown_secret:
        extras = ", ".join(sorted(str(k) for k in unknown_secret))
        raise RuntimeError(
            f"{context}: env dependency {name!r} secret supports only "
            f"'provider' and 'ref' in v1; found: {extras}."
        )
    provider = secret.get("provider")
    ref = secret.get("ref")
    if provider != "op":
        raise RuntimeError(
            f"{context}: env dependency {name!r} secret.provider must be 'op' in v1."
        )
    if not isinstance(ref, str) or not ref.startswith("op://"):
        raise RuntimeError(
            f"{context}: env dependency {name!r} secret.ref must be an op:// reference."
        )
    return EnvDependency(
        name=name,
        mode="secret",
        description=description,
        secret_provider="op",
        secret_ref=ref,
    )
