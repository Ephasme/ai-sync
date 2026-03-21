"""Common apply contract unifying WriteSpec and EffectSpec."""

from __future__ import annotations

from typing import Union

from ai_sync.data_classes.effect_spec import EffectSpec
from ai_sync.data_classes.write_spec import WriteSpec

ApplySpec = Union[WriteSpec, EffectSpec]
