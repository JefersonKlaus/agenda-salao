"""Use case (application layer): deletes an absence.
Depends only on the core's domain and ports, never on AWS."""
from __future__ import annotations

from typing import Any

from agenda_core.domain.errors import NotFound
from agenda_core.domain.models import TIME_OFF_ID_RE
from agenda_core.ports import Dependencies


def delete_time_off(deps: Dependencies, owner: str, id: Any) -> None:
    if not isinstance(id, str) or not TIME_OFF_ID_RE.match(id) or not deps.repo.delete_time_off(owner, id):
        raise NotFound("ausência não encontrada")
