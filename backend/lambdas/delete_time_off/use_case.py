"""Use case (application layer): deletes an absence. The manager deletes anyone's; an employee only her own.
Depends only on the core's domain and ports, never on AWS."""
from __future__ import annotations

from typing import Any, Optional

from agenda_core.application import check_own_absence
from agenda_core.domain.errors import NotFound
from agenda_core.domain.models import TIME_OFF_ID_RE
from agenda_core.ports import Dependencies


def delete_time_off(deps: Dependencies, owner: str, id: Any, manager: bool = True,
                    professional_id: Optional[str] = None) -> None:
    time_off = deps.repo.get_time_off(owner, id) if isinstance(id, str) and TIME_OFF_ID_RE.match(id) else None
    if time_off is None:
        raise NotFound("ausência não encontrada")
    check_own_absence(time_off, manager, professional_id)
    deps.repo.delete_time_off(owner, id)
