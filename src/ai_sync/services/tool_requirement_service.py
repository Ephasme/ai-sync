"""Service for validating runtime binary dependency versions."""

from __future__ import annotations

import shlex

from ai_sync.data_classes.requirement_check_result import RequirementCheckResult
from ai_sync.models.binary_dependency import BinaryDependency

from .tool_version_service import VERSION_RE, ToolVersionService


class ToolRequirementService:
    """Check collected binary dependencies against local tool versions."""

    def __init__(self, *, version_check_service: ToolVersionService) -> None:
        self._version_check_service = version_check_service

    def check_binary_dependencies(
        self, dependencies: list[BinaryDependency]
    ) -> list[RequirementCheckResult]:
        results: list[RequirementCheckResult] = []
        for dep in dependencies:
            name = dep.name
            constraint = dep.version.require

            if dep.version.get_cmd is not None:
                try:
                    cmd = shlex.split(dep.version.get_cmd)
                    output = self._version_check_service.run_command_capture_output(cmd)
                except (ValueError, OSError) as exc:
                    results.append(
                        RequirementCheckResult(
                            name=name,
                            ok=False,
                            actual=None,
                            required=constraint,
                            error=f"{name}: invalid get_cmd – {exc}",
                        )
                    )
                    continue
            else:
                output = self._version_check_service.run_command_capture_output(
                    [name, "--version"]
                )

            match = VERSION_RE.search(output)
            if match is None:
                results.append(
                    RequirementCheckResult(
                        name=name,
                        ok=False,
                        actual=None,
                        required=constraint,
                        error=f"{name}: not found",
                    )
                )
                continue

            actual = f"{match.group(1)}.{match.group(2)}.{match.group(3)}"
            actual_tuple = (int(match.group(1)), int(match.group(2)), int(match.group(3)))

            if self._satisfies(actual_tuple, constraint):
                results.append(
                    RequirementCheckResult(
                        name=name, ok=True, actual=actual, required=constraint
                    )
                )
            else:
                results.append(
                    RequirementCheckResult(
                        name=name,
                        ok=False,
                        actual=actual,
                        required=constraint,
                        error=f"{name}: found {actual}, require {constraint}",
                    )
                )

        return results

    @staticmethod
    def _parse_version(version: str) -> tuple[int, int, int]:
        match = VERSION_RE.search(version)
        if match is None:
            raise ValueError(f"Cannot parse version from: {version!r}")
        return (int(match.group(1)), int(match.group(2)), int(match.group(3)))

    def _satisfies(
        self, actual_tuple: tuple[int, int, int], constraint: str
    ) -> bool:
        prefix = constraint[0]
        required_tuple = self._parse_version(constraint[1:])
        if prefix == "~":
            upper = (required_tuple[0], required_tuple[1] + 1, 0)
            return actual_tuple >= required_tuple and actual_tuple < upper

        upper = (required_tuple[0] + 1, 0, 0)
        return actual_tuple >= required_tuple and actual_tuple < upper
