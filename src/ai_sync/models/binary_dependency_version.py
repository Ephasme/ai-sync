"""Binary dependency version constraint model."""

from __future__ import annotations

import re

from pydantic import BaseModel, field_validator


class BinaryDependencyVersion(BaseModel):
    require: str
    get_cmd: str | None = None

    @field_validator("require")
    @classmethod
    def require_must_have_known_prefix(cls, value: str) -> str:
        if not value.startswith(("~", "^")):
            raise ValueError(f"require must start with '~' or '^', got: {value!r}")
        if not re.fullmatch(r"\d+\.\d+\.\d+", value[1:]):
            raise ValueError(f"require must be ~X.Y.Z or ^X.Y.Z, got: {value!r}")
        return value
