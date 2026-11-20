"""Use case (application layer): the salon's business hours (the defaults until they are saved).
Depends only on the core's domain and ports, never on AWS."""
from __future__ import annotations

from agenda_core.application import salon_settings
from agenda_core.domain.models import Settings
from agenda_core.ports import Dependencies


def get_settings(deps: Dependencies, owner: str) -> Settings:
    return salon_settings(deps.repo, owner)
