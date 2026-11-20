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
TIME_OFF_KINDS = ("vacation", "sick", "travel", "day_off", "other")   # the screen shows them in Portuguese
DAY_NAMES = ("Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo")   # shown to the user

# How each API field is named in the (Portuguese) error messages shown to the user.
FIELD_LABELS = {
    "name": "nome", "duration_min": "duracao_min", "price_cents": "preco_centavos",
    "services": "servicos", "open_days": "dias_abertos",
    "client_name": "cliente_nome", "client_phone": "cliente_telefone", "reason": "motivo",
    "email": "e-mail", "phone": "telefone",
}
PHONE_RE = re.compile(r"^\d{10,11}$")       # a client's key: area code + number, digits only
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


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
    """Opening hours on one weekday (0 = Monday ... 6 = Sunday): the salon's, or a professional's."""
    day: int
    start: str
    end: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _parse_work_hours(value: Any, label: str = "horário de trabalho") -> Optional[tuple[Shift, ...]]:
    """None = follows the salon's hours. A list = only those days, at those times
    (an empty list means she does not work on any day)."""
    if value is None:
        return None
    if not isinstance(value, list) or len(value) > 7 or not all(
            isinstance(s, dict) and isinstance(s.get("day"), int) and not isinstance(s.get("day"), bool)
            and 0 <= s["day"] <= 6 for s in value):
        raise ValidationError(f"{label}: envie uma lista de dias (0 a 6) com entrada e saída")
    shifts = []
    for s in value:
        start, end = parse_time(s.get("start")), parse_time(s.get("end"))
        if start % STEP_MIN or end % STEP_MIN:
            raise ValidationError(f"{DAY_NAMES[s['day']]}: use horários de {STEP_MIN} em {STEP_MIN} minutos")
        if end - start < STEP_MIN:
            raise ValidationError(f"{DAY_NAMES[s['day']]}: a saída precisa ser depois da entrada")
        shifts.append(Shift(s["day"], format_time(start), format_time(end)))
    if len({s.day for s in shifts}) != len(shifts):
        raise ValidationError(f"{label}: cada dia só pode aparecer uma vez")
    return tuple(sorted(shifts, key=lambda s: s.day))


COMMISSION_KINDS = ("percent", "fixed")       # % of the service's price, or a fixed amount (cents) per service


@dataclass(frozen=True)
class Commission:
    """What a professional earns each time she performs a service: `value` % of its price
    ("percent", 0 to 100), or `value` cents ("fixed")."""
    service_id: str
    kind: str
    value: int

    def of(self, price_cents: int) -> int:
        return round(price_cents * self.value / 100) if self.kind == "percent" else self.value


def _parse_commissions(value: Any, services: tuple[str, ...]) -> tuple[Commission, ...]:
    """{service_id: {"kind": "percent" | "fixed", "value": int}}, only for services she performs."""
    if value is None:
        return ()
    if not isinstance(value, dict):
        raise ValidationError("comissão: envie um objeto por serviço")
    found = []
    for service_id, rule in value.items():
        if service_id not in services:
            raise ValidationError("comissão: só para os serviços que ela faz")
        kind = rule.get("kind") if isinstance(rule, dict) else None
        number = rule.get("value") if isinstance(rule, dict) else None
        if kind not in COMMISSION_KINDS or isinstance(number, bool) or not isinstance(number, int):
            raise ValidationError("comissão: informe percentual ou valor fixo")
        if kind == "percent" and not 0 <= number <= 100:
            raise ValidationError("comissão: o percentual vai de 0 a 100")
        if kind == "fixed" and not 0 <= number <= MAX_PRICE_CENTS:
            raise ValidationError("comissão: valor fixo inválido")
        found.append(Commission(service_id, kind, number))
    return tuple(sorted(found, key=lambda c: c.service_id))


@dataclass(frozen=True)
class Professional:
    id: str
    name: str
    services: tuple[str, ...]       # ids of the services she performs
    work_hours: Optional[tuple[Shift, ...]] = None      # None = follows the salon's business hours
    login: Optional[str] = None     # e-mail of her access to the app; set only when the access is created
    commissions: tuple[Commission, ...] = ()       # per service she performs; none = no commission

    @classmethod
    def from_input(cls, payload: Mapping[str, Any], id: Optional[str] = None) -> "Professional":
        """`login` is never taken from here: only creating an access sets it (create_access)."""
        ids = payload.get("services", [])
        if not isinstance(ids, list) or len(ids) > 100 or not all(
                isinstance(i, str) and ITEM_ID_RE.match(i) for i in ids):
            raise ValidationError("servicos: envie uma lista de ids de serviço")
        services = tuple(dict.fromkeys(ids))
        return cls(id or new_id(), _text(payload, "name"), services, _parse_work_hours(payload.get("work_hours")),
                   None, _parse_commissions(payload.get("commissions"), services))

    def commission_for(self, service_id: str, price_cents: int) -> int:
        """What she earns for performing this service at this price (0 without a commission for it)."""
        rule = next((c for c in self.commissions if c.service_id == service_id), None)
        return rule.of(price_cents) if rule else 0

    def shift_on(self, weekday: int) -> Optional[Shift]:
        return next((s for s in self.work_hours or () if s.day == weekday), None)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "services": list(self.services),
                "work_hours": None if self.work_hours is None else [s.to_dict() for s in self.work_hours],
                "login": self.login,
                "commissions": {c.service_id: {"kind": c.kind, "value": c.value} for c in self.commissions}}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Professional":
        hours = d.get("work_hours")         # missing in professionals saved before it existed
        return cls(d["id"], d["name"], tuple(d["services"]),
                   None if hours is None else tuple(Shift(**s) for s in hours), d.get("login"),
                   tuple(Commission(sid, r["kind"], r["value"]) for sid, r in sorted((d.get("commissions") or {}).items())))


@dataclass(frozen=True)
class Settings:
    """The salon's business hours: one shift per day it opens, each day with its own times.
    Default (until the salon saves its own): Monday to Saturday, 09:00-19:00."""
    hours: tuple[Shift, ...] = tuple(Shift(day, "09:00", "19:00") for day in range(6))

    @property
    def open_days(self) -> tuple[int, ...]:
        return tuple(s.day for s in self.hours)

    def shift_on(self, weekday: int) -> Optional[Shift]:
        """The salon's hours that weekday; None = closed."""
        return next((s for s in self.hours if s.day == weekday), None)

    @classmethod
    def from_input(cls, payload: Mapping[str, Any]) -> "Settings":
        hours = _parse_work_hours(payload.get("hours"), "horário de funcionamento")
        if not hours:
            raise ValidationError("horário de funcionamento: o salão precisa abrir em pelo menos um dia")
        return cls(hours)

    def to_dict(self) -> dict[str, Any]:
        return {"hours": [s.to_dict() for s in self.hours]}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Settings":
        if "hours" in d:
            return cls(tuple(Shift(**s) for s in d["hours"]))
        # saved before each day had its own hours: the same opening and closing on every open day
        return cls(tuple(Shift(day, d["opens"], d["closes"]) for day in sorted(d["open_days"])))


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
    paid: bool = False              # the client already paid (appointments saved before it existed: not paid)
    commission_cents: int = 0       # what the professional earns for it, copied when booked (like the price)

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
        return cls(**{field: d[field] for field in cls.__dataclass_fields__ if field in d})


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
    reason: str                     # free note, optional
    kind: str = "other"             # one of TIME_OFF_KINDS (absences saved before it existed: "other")

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
        kind = payload.get("kind") or "other"
        if kind not in TIME_OFF_KINDS:
            raise ValidationError("ausência: tipo inválido")
        return cls(f"{first.isoformat()}_{new_id()}", professional_id, first.isoformat(), last.isoformat(),
                   start, end, _text(payload, "reason", required=False), kind)

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
        return cls(**{field: d[field] for field in cls.__dataclass_fields__ if field in d})


def parse_name(payload: Mapping[str, Any]) -> str:
    return _text(payload, "name")


def parse_email(payload: Mapping[str, Any]) -> str:
    email = _text(payload, "email", max_length=120).lower()
    if not _EMAIL_RE.match(email):
        raise ValidationError("e-mail inválido")
    return email


@dataclass(frozen=True)
class Access:
    """A login to the app, created by the manager. `professional_id`: the professional it belongs to
    (a service provider); None for someone who does not attend clients (a receptionist, a partner)."""
    id: str                         # the login's id in the identity provider (Cognito's `sub`)
    email: str
    name: str
    manager: bool
    professional_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Access":
        return cls(**{field: d[field] for field in cls.__dataclass_fields__ if field in d})


def _phone(payload: Mapping[str, Any], field: str) -> str:
    """"(11) 98888-7777" -> "11988887777": area code + number, digits only. Required: it is the client's key."""
    phone = re.sub(r"\D", "", _text(payload, field, 20))
    if not PHONE_RE.match(phone):
        raise ValidationError(f"{FIELD_LABELS[field]}: use DDD + número")
    return phone


def parse_client(payload: Mapping[str, Any]) -> tuple[str, str]:
    """Name and phone of the client of an appointment. The phone is required: it registers her."""
    return _text(payload, "client_name"), _phone(payload, "client_phone")


@dataclass(frozen=True)
class Client:
    """A client of the salon. Her phone is her key: booking with it registers her (or finds her)."""
    phone: str
    name: str

    @classmethod
    def from_input(cls, payload: Mapping[str, Any]) -> "Client":
        return cls(_phone(payload, "phone"), _text(payload, "name"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Client":
        return cls(d["phone"], d["name"])


MODELS = {"service": Service, "professional": Professional}
