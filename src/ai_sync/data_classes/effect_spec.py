"""Effect spec for managed side effects."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EffectSpec:
    """A managed side effect such as hook installation or permission changes.

    Unlike WriteSpec (which targets file content), EffectSpec models
    non-content operations that the apply/reconcile engine must track,
    execute, and reverse through the same state-backed mechanism.
    """

    effect_type: str
    target: str
    target_key: str
    params: dict = field(default_factory=dict)
