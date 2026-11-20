"""Models and validation. Times are in the salon's local time, with no time zone:
date "YYYY-MM-DD" and time "HH:MM".

Error messages are shown to the user as-is, so they stay in Portuguese (the app's language)."""
from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Mapping, Optional

from .errors import ValidationError

STEP_MIN = 15                       # minutes between one time slot and the next
MIN_DURATION, MAX_DURATION = 15, 480
MAX_PRICE_CENTS = 1_000_000         # R$ 10,000.00 in cents
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ITEM_ID_RE = re.compile(r"^[0-9a-f]{8}$")
APPOINTMENT_ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{4}_[0-9a-f]{8}$")
TIME_OFF_ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_[0-9a-f]{8}$")
MAX_TIME_OFF_DAYS = 180             # longest absence (a long leave); also bounds the calendar's lookups
DAY_NAMES = ("Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo")   # shown to the user

# How each API field is named in the (Portuguese) error messages shown to the user.
FIELD_LABELS = {
    "name": "nome", "duration_min": "duracao_min", "price_cents": "preco_centavos",
    "services": "servicos", "open_days": "dias_abertos",
    "client_name": "cliente_nome", "client_phone": "cliente_telefone", "reason": "motivo",
}


def new_id() -> str:
    return uuid.uuid4().hex[:8]


def parse_date(value: Any) -> date:
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise ValidationError("data inválida: use AAAA-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValidationError("essa data não existe") from None


def parse_time(value: Any) -> int:
    """'09:30' -> 570 (minutes since midnight)."""
    match = _TIME_RE.match(value) if isinstance(value, str) else None
    if not match:
        raise ValidationError("hora inválida: use HH:MM")
    return int(match.group(1)) * 60 + int(match.group(2))


def format_time(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _text(payload: Mapping[str, Any], field: str, max_length: int = 80, required: bool = True) -> str:
    value = payload.get(field)
    label = FIELD_LABELS[field]
    if value is None and not required:
        return ""
    if not isinstance(value, str) or (required and not value.strip()):
        raise ValidationError(f"{label}: preencha este campo")
    cleaned = " ".join(value.split())
    if len(cleaned) > max_length:
        raise ValidationError(f"{label}: no máximo {max_length} caracteres")
    return cleaned


def _integer(payload: Mapping[str, Any], field: str, minimum: int, maximum: int) -> int:
    value = payload.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValidationError(f"{FIELD_LABELS[field]}: informe um número inteiro de {minimum} a {maximum}")
    return value


@dataclass(frozen=True)
class Service:
    id: str
    name: str
    duration_min: int
    price_cents: int
    active: bool = True             # a disabled service is not offered for new appointments

    @classmethod
    def from_input(cls, payload: Mapping[str, Any], id: Optional[str] = None) -> "Service":
        duration = _integer(payload, "duration_min", MIN_DURATION, MAX_DURATION)
        if duration % STEP_MIN:
            raise ValidationError(f"duracao_min: use múltiplos de {STEP_MIN} minutos")
        active = payload.get("active", True)
        if not isinstance(active, bool):
            raise ValidationError("ativo: envie true ou false")
        return cls(id or new_id(), _text(payload, "name"), duration,
                   _integer(payload, "price_cents", 0, MAX_PRICE_CENTS), active)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Service":
        return cls(d["id"], d["name"], d["duration_min"], d["price_cents"], d.get("active", True))


@dataclass(frozen=True)
class Shift:
    """The hours a professional works on one weekday (0 = Monday ... 6 = Sunday)."""
    day: int
    start: str
    end: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _parse_work_hours(value: Any) -> Optional[tuple[Shift, ...]]:
    """None = follows the salon's hours. A list = only those days, at those times
    (an empty list means she does not work on any day)."""
    if value is None:
        return None
    if not isinstance(value, list) or len(value) > 7 or not all(
            isinstance(s, dict) and isinstance(s.get("day"), int) and not isinstance(s.get("day"), bool)
            and 0 <= s["day"] <= 6 for s in value):
        raise ValidationError("horário de trabalho: envie uma lista de dias (0 a 6) com entrada e saída")
    shifts = []
    for s in value:
        start, end = parse_time(s.get("start")), parse_time(s.get("end"))
        if start % STEP_MIN or end % STEP_MIN:
            raise ValidationError(f"{DAY_NAMES[s['day']]}: use horários de {STEP_MIN} em {STEP_MIN} minutos")
        if end - start < STEP_MIN:
            raise ValidationError(f"{DAY_NAMES[s['day']]}: a saída precisa ser depois da entrada")
        shifts.append(Shift(s["day"], format_time(start), format_time(end)))
    if len({s.day for s in shifts}) != len(shifts):
        raise ValidationError("horário de trabalho: cada dia só pode aparecer uma vez")
    return tuple(sorted(shifts, key=lambda s: s.day))


@dataclass(frozen=True)
class Professional:
    id: str
    name: str
    services: tuple[str, ...]       # ids of the services she performs
    work_hours: Optional[tuple[Shift, ...]] = None      # None = follows the salon's business hours

    @classmethod
    def from_input(cls, payload: Mapping[str, Any], id: Optional[str] = None) -> "Professional":
        ids = payload.get("services", [])
        if not isinstance(ids, list) or len(ids) > 100 or not all(
                isinstance(i, str) and ITEM_ID_RE.match(i) for i in ids):
            raise ValidationError("servicos: envie uma lista de ids de serviço")
        return cls(id or new_id(), _text(payload, "name"), tuple(dict.fromkeys(ids)),
                   _parse_work_hours(payload.get("work_hours")))

    def shift_on(self, weekday: int) -> Optional[Shift]:
        return next((s for s in self.work_hours or () if s.day == weekday), None)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "services": list(self.services),
                "work_hours": None if self.work_hours is None else [s.to_dict() for s in self.work_hours]}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Professional":
        hours = d.get("work_hours")         # missing in professionals saved before it existed
        return cls(d["id"], d["name"], tuple(d["services"]),
                   None if hours is None else tuple(Shift(**s) for s in hours))


@dataclass(frozen=True)
class Settings:
    open_days: tuple[int, ...] = (0, 1, 2, 3, 4, 5)   # 0 = Monday ... 6 = Sunday
    opens: str = "09:00"
    closes: str = "19:00"

    @classmethod
    def from_input(cls, payload: Mapping[str, Any]) -> "Settings":
        days = payload.get("open_days")
        if not isinstance(days, list) or not days or not all(
                isinstance(d, int) and not isinstance(d, bool) and 0 <= d <= 6 for d in days):
            raise ValidationError("dias_abertos: lista de 0 (segunda) a 6 (domingo)")
        opens, closes = parse_time(payload.get("opens")), parse_time(payload.get("closes"))
        if opens % STEP_MIN or closes % STEP_MIN:
            raise ValidationError(f"os horários devem ser múltiplos de {STEP_MIN} minutos")
        if closes - opens < STEP_MIN:
            raise ValidationError("o salão precisa fechar depois de abrir")
        return cls(tuple(sorted(set(days))), format_time(opens), format_time(closes))

    def to_dict(self) -> dict[str, Any]:
        return {"open_days": list(self.open_days), "opens": self.opens, "closes": self.closes}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Settings":
        return cls(tuple(d["open_days"]), d["opens"], d["closes"])


@dataclass(frozen=True)
class Appointment:
    id: str
    date: str
    start: str
    duration_min: int
    professional_id: str
    professional_name: str
    service_id: str
    service_name: str
    price_cents: int
    client_name: str
    client_phone: str

    @property
    def start_min(self) -> int:
        return parse_time(self.start)

    @property
    def end_min(self) -> int:
        return self.start_min + self.duration_min

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Appointment":
        return cls(**{field: d[field] for field in cls.__dataclass_fields__})


@dataclass(frozen=True)
class TimeOff:
    """An absence: a professional does not work from `first_day` to `last_day` (sick, travelling...).
    Whole days when `start`/`end` are None; otherwise only those hours, on each of those days."""
    id: str                         # "<first_day>_<8 hex>": sorts by date in the table
    professional_id: str
    first_day: str
    last_day: str
    start: Optional[str]
    end: Optional[str]
    reason: str

    @classmethod
    def from_input(cls, payload: Mapping[str, Any]) -> "TimeOff":
        professional_id = payload.get("professional_id")
        if not isinstance(professional_id, str) or not ITEM_ID_RE.match(professional_id):
            raise ValidationError("ausência: escolha a profissional")
        first = parse_date(payload.get("first_day"))
        last = parse_date(payload.get("last_day") or payload.get("first_day"))
        if last < first:
            raise ValidationError("ausência: o último dia vem antes do primeiro")
        if (last - first).days >= MAX_TIME_OFF_DAYS:
            raise ValidationError(f"ausência: no máximo {MAX_TIME_OFF_DAYS} dias de uma vez")
        start, end = payload.get("start"), payload.get("end")
        if (start is None) != (end is None):
            raise ValidationError("ausência: informe o início e o fim, ou marque o dia inteiro")
        if start is not None:
            start_min, end_min = parse_time(start), parse_time(end)
            if start_min % STEP_MIN or end_min % STEP_MIN:
                raise ValidationError(f"ausência: use horários de {STEP_MIN} em {STEP_MIN} minutos")
            if end_min <= start_min:
                raise ValidationError("ausência: o fim precisa ser depois do início")
            start, end = format_time(start_min), format_time(end_min)
        return cls(f"{first.isoformat()}_{new_id()}", professional_id, first.isoformat(), last.isoformat(),
                   start, end, _text(payload, "reason", required=False))

    @property
    def whole_day(self) -> bool:
        return self.start is None

    def interval_on(self, day: str) -> Optional[tuple[int, int]]:
        """Minutes [start, end) she is away on `day` (the whole day = 0 to 24h); None if not that day."""
        if not self.first_day <= day <= self.last_day:
            return None
        return (0, 24 * 60) if self.whole_day else (parse_time(self.start), parse_time(self.end))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "TimeOff":
        return cls(**{field: d[field] for field in cls.__dataclass_fields__})


def parse_client(payload: Mapping[str, Any]) -> tuple[str, str]:
    """Name and phone (digits only, with area code). The phone is optional."""
    name = _text(payload, "client_name")
    phone = re.sub(r"\D", "", _text(payload, "client_phone", 20, required=False))
    if phone and len(phone) not in (10, 11):
        raise ValidationError("cliente_telefone: use DDD + número")
    return name, phone


MODELS = {"service": Service, "professional": Professional}
