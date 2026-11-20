"""In-memory repository: used in tests and to run without AWS. Never deployed (the Lambdas use DynamoDB)."""
from __future__ import annotations

import threading
from typing import Any, Optional

from agenda_core.domain.models import MODELS, Access, Appointment, Settings, TimeOff
from agenda_core.domain.errors import SlotConflict
from agenda_core.domain.scheduling import lock_keys


class MemoryRepository:
    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()       # mimics the atomicity of the DynamoDB transaction

    def _salon(self, owner: str) -> dict[str, Any]:
        return self._data.setdefault(owner, {"service": {}, "professional": {}, "appointments": {},
                                             "locks": set(), "settings": None, "time_off": {}, "accesses": {}})

    def list_items(self, owner: str, kind: str) -> list[Any]:
        return list(self._salon(owner)[kind].values())

    def get(self, owner: str, kind: str, id: str) -> Optional[Any]:
        return self._salon(owner)[kind].get(id)

    def save(self, owner: str, kind: str, item: Any) -> None:
        self._salon(owner)[kind][item.id] = MODELS[kind].from_dict(item.to_dict())

    def delete(self, owner: str, kind: str, id: str) -> None:
        self._salon(owner)[kind].pop(id, None)

    def get_settings(self, owner: str) -> Optional[Settings]:
        return self._salon(owner)["settings"]

    def save_settings(self, owner: str, settings: Settings) -> None:
        self._salon(owner)["settings"] = settings

    def appointments_on_day(self, owner: str, date: str) -> list[Appointment]:
        return [a for a in self._salon(owner)["appointments"].values() if a.date == date]

    def appointments_between(self, owner: str, first: str, last: str) -> list[Appointment]:
        return [a for a in self._salon(owner)["appointments"].values() if first <= a.date <= last]

    def get_appointment(self, owner: str, id: str) -> Optional[Appointment]:
        return self._salon(owner)["appointments"].get(id)

    def create_appointment(self, owner: str, appt: Appointment) -> None:
        keys = lock_keys(appt.professional_id, appt.date, appt.start_min, appt.duration_min)
        with self._lock:
            salon = self._salon(owner)
            if appt.id in salon["appointments"] or any(k in salon["locks"] for k in keys):
                raise SlotConflict("esse horário acabou de ser ocupado")
            salon["appointments"][appt.id] = appt
            salon["locks"].update(keys)

    def change_appointment_professional(self, owner: str, old: Appointment, new: Appointment) -> None:
        old_keys = lock_keys(old.professional_id, old.date, old.start_min, old.duration_min)
        new_keys = lock_keys(new.professional_id, new.date, new.start_min, new.duration_min)
        with self._lock:
            salon = self._salon(owner)
            if salon["appointments"].get(old.id) != old:
                raise SlotConflict("esse agendamento acabou de ser alterado; atualize a agenda")
            if any(k in salon["locks"] for k in new_keys):
                raise SlotConflict("esse horário acabou de ser ocupado")
            salon["appointments"][new.id] = new
            salon["locks"].difference_update(old_keys)
            salon["locks"].update(new_keys)

    def update_appointment(self, owner: str, old: Appointment, new: Appointment) -> None:
        with self._lock:
            salon = self._salon(owner)
            if salon["appointments"].get(old.id) != old:
                raise SlotConflict("esse agendamento acabou de ser alterado; atualize a agenda")
            salon["appointments"][new.id] = new

    def time_off_between(self, owner: str, first: str, last: str) -> list[TimeOff]:
        return [t for t in self._salon(owner)["time_off"].values() if t.first_day <= last and t.last_day >= first]

    def save_time_off(self, owner: str, time_off: TimeOff) -> None:
        self._salon(owner)["time_off"][time_off.id] = time_off

    def get_time_off(self, owner: str, id: str) -> Optional[TimeOff]:
        return self._salon(owner)["time_off"].get(id)

    def list_accesses(self, owner: str) -> list[Access]:
        return list(self._salon(owner)["accesses"].values())

    def save_access(self, owner: str, access: Access) -> None:
        self._salon(owner)["accesses"][access.id] = access

    def delete_access(self, owner: str, id: str) -> None:
        self._salon(owner)["accesses"].pop(id, None)

    def delete_time_off(self, owner: str, id: str) -> bool:
        return self._salon(owner)["time_off"].pop(id, None) is not None

    def cancel_appointment(self, owner: str, id: str) -> Optional[Appointment]:
        with self._lock:
            salon = self._salon(owner)
            appt = salon["appointments"].pop(id, None)
            if appt:
                salon["locks"].difference_update(
                    lock_keys(appt.professional_id, appt.date, appt.start_min, appt.duration_min))
            return appt
