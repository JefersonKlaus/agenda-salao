"""Ports: what the use cases need from the outside world, without knowing how it is done.
adapters/dynamo_repository.py implements Repository in AWS; local/memory_repository.py, locally.
adapters/cognito_identity.py implements Identity in AWS; local/memory_identity.py, locally."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Optional, Protocol

from .domain.models import Access, Appointment, Client, Settings, TimeOff

Clock = Callable[[], datetime]          # the salon's current date and time (Brasília, no tzinfo)


class Repository(Protocol):
    """Every salon's data. `owner` is the salon id, always taken from the login token."""

    # services (kind "service") and professionals (kind "professional")
    def list_items(self, owner: str, kind: str) -> list[Any]: ...
    def get(self, owner: str, kind: str, id: str) -> Optional[Any]: ...
    def save(self, owner: str, kind: str, item: Any) -> None: ...
    def delete(self, owner: str, kind: str, id: str) -> None: ...

    def get_settings(self, owner: str) -> Optional[Settings]: ...
    def save_settings(self, owner: str, settings: Settings) -> None: ...

    def appointments_on_day(self, owner: str, date: str) -> list[Appointment]: ...
    def appointments_between(self, owner: str, first: str, last: str) -> list[Appointment]: ...
    def get_appointment(self, owner: str, id: str) -> Optional[Appointment]: ...
    def create_appointment(self, owner: str, appt: Appointment) -> None:
        """Atomic: raises SlotConflict if the time was taken in the meantime."""
    def change_appointment_professional(self, owner: str, old: Appointment, new: Appointment) -> None: ...
    def update_appointment(self, owner: str, old: Appointment, new: Appointment) -> None:
        """Same time and professional, other details (payment). Conflict if it changed since read."""
    def cancel_appointment(self, owner: str, id: str) -> Optional[Appointment]: ...

    def time_off_between(self, owner: str, first: str, last: str) -> list[TimeOff]: ...
    def get_time_off(self, owner: str, id: str) -> Optional[TimeOff]: ...
    def save_time_off(self, owner: str, time_off: TimeOff) -> None: ...
    def delete_time_off(self, owner: str, id: str) -> bool: ...

    def list_clients(self, owner: str) -> list[Client]: ...
    def get_client(self, owner: str, phone: str) -> Optional[Client]: ...
    def save_client(self, owner: str, client: Client) -> None: ...
    def client_appointments(self, owner: str, phone: str) -> list[Appointment]:
        """Every appointment of this client (by her phone), whatever the date."""

    def list_accesses(self, owner: str) -> list[Access]: ...
    def save_access(self, owner: str, access: Access) -> None: ...
    def delete_access(self, owner: str, id: str) -> None: ...


class Identity(Protocol):
    """Who can log in (Cognito in AWS)."""

    def create_login(self, email: str, name: str, salon: str, professional_id: Optional[str], manager: bool) -> str:
        """Creates the login (the person gets a temporary password by e-mail) and returns its id.
        ValidationError if the e-mail already has one. `salon` and `professional_id` are written in the
        login itself, unchangeable: the token says which salon and which professional it is."""

    def delete_login(self, email: str) -> None:
        """Removes the login: that person can no longer get in (nothing happens if it is already gone)."""


@dataclass(frozen=True)
class Dependencies:
    """What every use case receives: the ports, already plugged into their adapters."""
    repo: Repository
    now: Clock
    identity: Optional[Identity] = None     # only the Lambdas that create logins get one
