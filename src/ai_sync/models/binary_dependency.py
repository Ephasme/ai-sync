"""Artifact-scoped binary dependency model."""

from pydantic import BaseModel

from ai_sync.models.binary_dependency_version import BinaryDependencyVersion


class BinaryDependency(BaseModel):
    name: str
    version: BinaryDependencyVersion
