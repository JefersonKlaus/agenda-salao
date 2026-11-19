"""Agenda use cases. They receive the `owner` (salon id) already validated by the login."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any, Callable, Mapping

from .domain import (APPOINTMENT_ID_RE, DAY_NAMES, MODELS, TIME_OFF_ID_RE, Appointment, Professional,
                     Service, Settings, TimeOff, new_id, parse_client, parse_date, parse_time)
from .errors import NotFound, ValidationError
from .scheduling import (away_intervals, busy_intervals, fits_business_hours, free_slots, is_past,
                         overlaps)

MAX_RANGE_DAYS = 62                 # longest period the calendar asks for at once (a month view is 42)
LIMITS = {"service": 200, "professional": 50}
LABELS = {"service": "serviço", "professional": "profissional"}     # shown to the user


class Agenda:
    def __init__(self, repo: Any, now: Callable[[], datetime]) -> None:
        self.repo, self.now = repo, now

    # ------------------------------------------------------------ services and professionals
    def list_items(self, owner: str, kind: str) -> list[Any]:
        return sorted(self.repo.list_items(owner, kind), key=lambda i: i.name.lower())

    def create(self, owner: str, kind: str, payload: Mapping[str, Any]) -> Any:
        if len(self.repo.list_items(owner, kind)) >= LIMITS[kind]:
            raise ValidationError(f"limite de {LIMITS[kind]} itens atingido")
        item = MODELS[kind].from_input(payload)
        self._check_services(owner, item)
        self.repo.save(owner, kind, item)
        return item

    def update(self, owner: str, kind: str, id: str, payload: Mapping[str, Any]) -> Any:
        current = self._get(owner, kind, id)
        if isinstance(current, Service) and "active" not in payload:
            payload = {**payload, "active": current.active}        # editing does not re-enable it
        item = MODELS[kind].from_input(payload, id=id)
        self._check_services(owner, item)
        self.repo.save(owner, kind, item)
        return item

    def remove(self, owner: str, kind: str, id: str) -> None:
        self._get(owner, kind, id)
        self.repo.delete(owner, kind, id)
        if kind == "service":           # nobody "performs" a service that no longer exists
            for prof in self.repo.list_items(owner, "professional"):
                if id in prof.services:
                    self.repo.save(owner, "professional", replace(
                        prof, services=tuple(s for s in prof.services if s != id)))

    def _get(self, owner: str, kind: str, id: str) -> Any:
        item = self.repo.get(owner, kind, id)
        if item is None:
            raise NotFound(f"{LABELS[kind]} não encontrado")
        return item

    def _check_services(self, owner: str, item: Any) -> None:
        if isinstance(item, Professional):
            existing = {s.id for s in self.repo.list_items(owner, "service")}
            if not set(item.services) <= existing:
                raise ValidationError("servicos: há serviço que não existe")
            self._check_work_hours(owner, item)

    def _check_work_hours(self, owner: str, prof: Professional) -> None:
        """Professionals only work inside the salon's business hours (its days, opening and closing)."""
        settings = self.settings(owner)
        for shift in prof.work_hours or ():
            if shift.day not in settings.open_days:
                raise ValidationError(f"{DAY_NAMES[shift.day]}: o salão não abre nesse dia")
            if parse_time(shift.start) < parse_time(settings.opens) or parse_time(shift.end) > parse_time(settings.closes):
                raise ValidationError(f"{DAY_NAMES[shift.day]}: fora do horário do salão "
                                      f"({settings.opens}–{settings.closes})")

    # ------------------------------------------------------------ business hours
    def settings(self, owner: str) -> Settings:
        return self.repo.get_settings(owner) or Settings()

    def save_settings(self, owner: str, payload: Mapping[str, Any]) -> Settings:
        settings = Settings.from_input(payload)
        self.repo.save_settings(owner, settings)
        return settings

    # ------------------------------------------------------------ appointments
    def availability(self, owner: str, date: str, service_id: str, professional_id: str) -> list[str]:
        day = parse_date(date)
        service, prof = self._service_and_professional(owner, service_id, professional_id)
        self._check_active(service)
        busy = (busy_intervals(self.repo.appointments_on_day(owner, date), prof.id)
                + away_intervals(self.repo.time_off_between(owner, date, date), prof.id, date))
        return free_slots(self.settings(owner), day, service.duration_min, busy, self.now(), prof)

    def day_schedule(self, owner: str, date: str) -> list[Appointment]:
        parse_date(date)
        return sorted(self.repo.appointments_on_day(owner, date),
                      key=lambda a: (a.start, a.professional_name))

    def schedule_between(self, owner: str, first: Any, last: Any) -> list[Appointment]:
        """Appointments from `first` to `last` (inclusive): what the week and month views show."""
        _check_period(first, last)
        return sorted(self.repo.appointments_between(owner, first, last),
                      key=lambda a: (a.date, a.start, a.professional_name))

    def book(self, owner: str, payload: Mapping[str, Any]) -> Appointment:
        day, start = parse_date(payload.get("date")), parse_time(payload.get("start"))
        client_name, phone = parse_client(payload)
        service, prof = self._service_and_professional(owner, payload.get("service_id"),
                                                       payload.get("professional_id"))
        self._check_active(service)
        if is_past(day, start, self.now()):
            raise ValidationError("esse horário já passou")
        self._check_slot(owner, day, start, service.duration_min, prof)
        date = day.isoformat()
        appt = Appointment(f"{date}_{start // 60:02d}{start % 60:02d}_{new_id()}", date,
                           payload["start"], service.duration_min, prof.id, prof.name, service.id,
                           service.name, service.price_cents, client_name, phone)
        self.repo.create_appointment(owner, appt)
        return appt

    def cancel(self, owner: str, id: str) -> Appointment:
        if not isinstance(id, str) or not APPOINTMENT_ID_RE.match(id):
            raise NotFound("agendamento não encontrado")
        appt = self.repo.cancel_appointment(owner, id)
        if appt is None:
            raise NotFound("agendamento não encontrado")
        return appt

    def change_professional(self, owner: str, id: str, payload: Mapping[str, Any]) -> Appointment:
        """Moves an appointment to another professional (same day, time and service)."""
        if not isinstance(id, str) or not APPOINTMENT_ID_RE.match(id):
            raise NotFound("agendamento não encontrado")
        appt = self.repo.get_appointment(owner, id)
        if appt is None:
            raise NotFound("agendamento não encontrado")
        professional_id = payload.get("professional_id")
        prof = self._get(owner, "professional", professional_id if isinstance(professional_id, str) else "")
        if prof.id == appt.professional_id:
            raise ValidationError("o agendamento já é com essa profissional")
        if appt.service_id not in prof.services:
            raise ValidationError("essa profissional não faz esse serviço")
        self._check_slot(owner, parse_date(appt.date), appt.start_min, appt.duration_min, prof)
        moved = replace(appt, professional_id=prof.id, professional_name=prof.name)
        self.repo.change_appointment_professional(owner, appt, moved)   # swaps the locks atomically
        return moved

    def _check_slot(self, owner: str, day: Any, start: int, duration: int, prof: Professional) -> None:
        """Refuses a time outside the salon's hours or hers, while she is away, or already taken."""
        settings, date = self.settings(owner), day.isoformat()
        if not fits_business_hours(settings, day, start, duration):
            raise ValidationError("esse horário está fora do expediente do salão")
        if not fits_business_hours(settings, day, start, duration, prof):
            raise ValidationError("essa profissional não trabalha nesse horário")
        if overlaps(start, start + duration, away_intervals(self.repo.time_off_between(owner, date, date), prof.id, date)):
            raise ValidationError("essa profissional está ausente nesse horário")
        if overlaps(start, start + duration, busy_intervals(self.repo.appointments_on_day(owner, date), prof.id)):
            raise ValidationError("esse horário já está ocupado")   # the lock in the database covers the race

    @staticmethod
    def _check_active(service: Service) -> None:
        if not service.active:
            raise ValidationError("esse serviço está desativado")

    # ------------------------------------------------------------ absences (sick, travelling...)
    def time_off_between(self, owner: str, first: Any, last: Any) -> list[TimeOff]:
        _check_period(first, last)
        return sorted(self.repo.time_off_between(owner, first, last), key=lambda t: (t.first_day, t.start or ""))

    def create_time_off(self, owner: str, payload: Mapping[str, Any]) -> tuple[TimeOff, list[Appointment]]:
        """Saves the absence and returns it with her appointments that fall inside it: those still
        exist and need to be moved to someone else or cancelled."""
        time_off = TimeOff.from_input(payload)
        self._get(owner, "professional", time_off.professional_id)
        self.repo.save_time_off(owner, time_off)
        affected = [a for a in self.repo.appointments_between(owner, time_off.first_day, time_off.last_day)
                    if a.professional_id == time_off.professional_id
                    and overlaps(a.start_min, a.end_min, [time_off.interval_on(a.date)])]
        return time_off, sorted(affected, key=lambda a: (a.date, a.start))

    def delete_time_off(self, owner: str, id: Any) -> None:
        if not isinstance(id, str) or not TIME_OFF_ID_RE.match(id) or not self.repo.delete_time_off(owner, id):
            raise NotFound("ausência não encontrada")

    def _service_and_professional(self, owner: str, service_id: Any, professional_id: Any):
        service = self._get(owner, "service", service_id if isinstance(service_id, str) else "")
        prof = self._get(owner, "professional", professional_id if isinstance(professional_id, str) else "")
        if service.id not in prof.services:
            raise ValidationError("essa profissional não faz esse serviço")
        return service, prof


def _check_period(first: Any, last: Any) -> None:
    first_day, last_day = parse_date(first), parse_date(last)
    if last_day < first_day:
        raise ValidationError("período inválido: o fim vem antes do início")
    if (last_day - first_day).days >= MAX_RANGE_DAYS:
        raise ValidationError(f"período grande demais: no máximo {MAX_RANGE_DAYS} dias")
