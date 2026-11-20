"""Application rules that more than one use case applies. They only go through the ports."""
from __future__ import annotations

from datetime import date
from typing import Any

from .domain.errors import NotFound, ValidationError
from .domain.models import DAY_NAMES, Professional, Service, Settings, parse_date, parse_time
from .domain.scheduling import away_intervals, busy_intervals, fits_business_hours, overlaps
from .ports import Repository

MAX_RANGE_DAYS = 62                 # longest period the calendar asks for at once (a month view is 42)
LIMITS = {"service": 200, "professional": 50}
LABELS = {"service": "serviço", "professional": "profissional"}     # shown to the user


def sorted_by_name(items: list[Any]) -> list[Any]:
    return sorted(items, key=lambda i: i.name.lower())


def get_item(repo: Repository, owner: str, kind: str, id: Any) -> Any:
    item = repo.get(owner, kind, id) if isinstance(id, str) else None
    if item is None:
        raise NotFound(f"{LABELS[kind]} não encontrado")
    return item


def check_limit(repo: Repository, owner: str, kind: str) -> None:
    if len(repo.list_items(owner, kind)) >= LIMITS[kind]:
        raise ValidationError(f"limite de {LIMITS[kind]} itens atingido")


def salon_settings(repo: Repository, owner: str) -> Settings:
    return repo.get_settings(owner) or Settings()


def check_professional(repo: Repository, owner: str, prof: Professional) -> None:
    """Her services must exist, and she only works inside the salon's days and hours."""
    existing = {s.id for s in repo.list_items(owner, "service")}
    if not set(prof.services) <= existing:
        raise ValidationError("servicos: há serviço que não existe")
    settings = salon_settings(repo, owner)
    for shift in prof.work_hours or ():
        if shift.day not in settings.open_days:
            raise ValidationError(f"{DAY_NAMES[shift.day]}: o salão não abre nesse dia")
        if parse_time(shift.start) < parse_time(settings.opens) or parse_time(shift.end) > parse_time(settings.closes):
            raise ValidationError(f"{DAY_NAMES[shift.day]}: fora do horário do salão "
                                  f"({settings.opens}–{settings.closes})")


def service_and_professional(repo: Repository, owner: str, service_id: Any, professional_id: Any):
    service = get_item(repo, owner, "service", service_id)
    prof = get_item(repo, owner, "professional", professional_id)
    if service.id not in prof.services:
        raise ValidationError("essa profissional não faz esse serviço")
    return service, prof


def check_active(service: Service) -> None:
    if not service.active:
        raise ValidationError("esse serviço está desativado")


def check_slot(repo: Repository, owner: str, day: date, start: int, duration: int, prof: Professional) -> None:
    """Refuses a time outside the salon's hours or hers, while she is away, or already taken."""
    settings, iso = salon_settings(repo, owner), day.isoformat()
    if not fits_business_hours(settings, day, start, duration):
        raise ValidationError("esse horário está fora do expediente do salão")
    if not fits_business_hours(settings, day, start, duration, prof):
        raise ValidationError("essa profissional não trabalha nesse horário")
    if overlaps(start, start + duration, away_intervals(repo.time_off_between(owner, iso, iso), prof.id, iso)):
        raise ValidationError("essa profissional está ausente nesse horário")
    if overlaps(start, start + duration, busy_intervals(repo.appointments_on_day(owner, iso), prof.id)):
        raise ValidationError("esse horário já está ocupado")   # the lock in the database covers the race


def check_period(first: Any, last: Any) -> None:
    first_day, last_day = parse_date(first), parse_date(last)
    if last_day < first_day:
        raise ValidationError("período inválido: o fim vem antes do início")
    if (last_day - first_day).days >= MAX_RANGE_DAYS:
        raise ValidationError(f"período grande demais: no máximo {MAX_RANGE_DAYS} dias")
