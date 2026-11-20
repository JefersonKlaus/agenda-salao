"""Use case (application layer): saves the salon's business hours: open days, opening and closing.
Depends only on the core's domain and ports, never on AWS."""
from __future__ import annotations

from typing import Any, Mapping

from agenda_core.domain.models import Settings
from agenda_core.ports import Dependencies


def save_settings(deps: Dependencies, owner: str, payload: Mapping[str, Any]) -> Settings:
    settings = Settings.from_input(payload)
    deps.repo.save_settings(owner, settings)
    return settings
