import pytest

from agenda_core.domain.models import (Appointment, Professional, Service, Settings, Shift, TimeOff, format_time,
                           parse_client, parse_date, parse_time)
from agenda_core.domain.errors import ValidationError


@pytest.mark.parametrize("text, minutes", [("00:00", 0), ("09:30", 570), ("23:59", 1439)])
def test_time_round_trip(text, minutes):
    assert parse_time(text) == minutes
    assert format_time(minutes) == text


@pytest.mark.parametrize("bad", ["9:30", "24:00", "10:60", "", None, 930, "10:00:00", "ab:cd"])
def test_invalid_time(bad):
    with pytest.raises(ValidationError):
        parse_time(bad)


@pytest.mark.parametrize("bad", ["2026-02-30", "26-01-01", "2026/01/01", None, 20260101, "2026-1-1"])
def test_invalid_date(bad):
    with pytest.raises(ValidationError):
        parse_date(bad)


def test_valid_service_trims_whitespace():
    s = Service.from_input({"name": "  Women's   haircut ", "duration_min": 45, "price_cents": 0})
    assert s.name == "Women's haircut" and len(s.id) == 8
    assert Service.from_dict(s.to_dict()) == s


@pytest.mark.parametrize("field, value", [
    ("name", ""), ("name", "   "), ("name", "x" * 81), ("name", 5),
    ("duration_min", 20), ("duration_min", 0), ("duration_min", 495), ("duration_min", True),
    ("duration_min", "30"), ("duration_min", 30.0),
    ("price_cents", -1), ("price_cents", 1_000_001), ("price_cents", 10.5),
])
def test_service_rejects_bad_data(field, value):
    payload = {"name": "Haircut", "duration_min": 30, "price_cents": 100, field: value}
    with pytest.raises(ValidationError):
        Service.from_input(payload)


def test_service_missing_required_field():
    with pytest.raises(ValidationError):
        Service.from_input({"name": "Haircut"})


def test_professional_removes_duplicates_and_validates_ids():
    p = Professional.from_input({"name": "Ana", "services": ["aaaaaaaa", "aaaaaaaa", "bbbbbbbb"]})
    assert p.services == ("aaaaaaaa", "bbbbbbbb")
    assert Professional.from_dict(p.to_dict()) == p
    for bad in ("aaaaaaaa", [1], ["short"], ["../etc"], ["a" * 8] * 101, None):
        with pytest.raises(ValidationError):
            Professional.from_input({"name": "Ana", "services": bad})


def test_settings_defaults_and_validation():
    s = Settings.from_input({"open_days": [5, 1, 1], "opens": "08:00", "closes": "18:30"})
    assert s.open_days == (1, 5) and Settings.from_dict(s.to_dict()) == s
    bad_inputs = [{"open_days": [], "opens": "08:00", "closes": "18:00"},
                  {"open_days": [7], "opens": "08:00", "closes": "18:00"},
                  {"open_days": [True], "opens": "08:00", "closes": "18:00"},
                  {"open_days": [1], "opens": "18:00", "closes": "08:00"},
                  {"open_days": [1], "opens": "08:10", "closes": "18:00"},
                  {"open_days": [1], "opens": "08:00", "closes": "08:00"}]
    for payload in bad_inputs:
        with pytest.raises(ValidationError):
            Settings.from_input(payload)


@pytest.mark.parametrize("given, phone", [
    ("(11) 98888-7777", "11988887777"), ("1133334444", "1133334444"), ("", ""), (None, "")])
def test_client_phone(given, phone):
    assert parse_client({"client_name": "Maria", "client_phone": given}) == ("Maria", phone)


def test_client_rejects_short_phone_and_empty_name():
    with pytest.raises(ValidationError):
        parse_client({"client_name": "Maria", "client_phone": "9999"})
    with pytest.raises(ValidationError):
        parse_client({"client_name": " ", "client_phone": ""})


def test_appointment_computes_end():
    a = Appointment("2026-11-17_1000_aaaaaaaa", "2026-11-17", "10:00", 90, "p", "Ana", "s",
                    "Haircut", 100, "Maria", "")
    assert (a.start_min, a.end_min) == (600, 690)
    assert Appointment.from_dict(a.to_dict()) == a


def test_professional_work_hours_are_optional_and_round_trip():
    assert Professional.from_input({"name": "Ana", "services": []}).work_hours is None
    p = Professional.from_input({"name": "Ana", "services": [], "work_hours": [
        {"day": 5, "start": "08:00", "end": "12:00"}, {"day": 1, "start": "10:00", "end": "18:30"}]})
    assert p.work_hours == (Shift(1, "10:00", "18:30"), Shift(5, "08:00", "12:00"))     # sorted by day
    assert p.shift_on(5) == Shift(5, "08:00", "12:00") and p.shift_on(0) is None
    assert Professional.from_dict(p.to_dict()) == p
    assert Professional.from_input({"name": "Ana", "services": [], "work_hours": []}).work_hours == ()


def test_professional_saved_before_work_hours_existed():
    assert Professional.from_dict({"id": "bbbbbbbb", "name": "Ana", "services": []}).work_hours is None


@pytest.mark.parametrize("hours, fragment", [
    ("Mon-Fri", "lista"), ([{"day": 7, "start": "09:00", "end": "18:00"}], "lista"),
    ([{"day": True, "start": "09:00", "end": "18:00"}], "lista"), ([None], "lista"),
    ([{"day": 1, "start": "9h", "end": "18:00"}], "hora inválida"),
    ([{"day": 1, "start": "09:10", "end": "18:00"}], "Terça: use horários de 15"),
    ([{"day": 1, "start": "18:00", "end": "09:00"}], "Terça: a saída precisa ser depois"),
    ([{"day": 6, "start": "09:00", "end": "09:00"}], "Domingo: a saída"),
    ([{"day": 1, "start": "09:00", "end": "12:00"}, {"day": 1, "start": "13:00", "end": "18:00"}], "uma vez"),
    ([{"day": d, "start": "09:00", "end": "10:00"} for d in range(7)] * 2, "lista"),
])
def test_professional_rejects_bad_work_hours(hours, fragment):
    with pytest.raises(ValidationError, match=fragment):
        Professional.from_input({"name": "Ana", "services": [], "work_hours": hours})


def test_service_is_active_unless_disabled():
    assert Service.from_input({"name": "Corte", "duration_min": 30, "price_cents": 1}).active is True
    off = Service.from_input({"name": "Corte", "duration_min": 30, "price_cents": 1, "active": False})
    assert off.active is False and Service.from_dict(off.to_dict()) == off
    assert Service.from_dict({"id": "aaaaaaaa", "name": "Corte", "duration_min": 30, "price_cents": 1}).active  # saved before
    with pytest.raises(ValidationError, match="ativo"):
        Service.from_input({"name": "Corte", "duration_min": 30, "price_cents": 1, "active": "no"})


def test_time_off_whole_days_and_hours():
    days = TimeOff.from_input({"professional_id": "bbbbbbbb", "first_day": "2026-11-17", "last_day": "2026-11-19",
                               "reason": "  Viagem  "})
    assert days.whole_day and days.reason == "Viagem" and days.id.startswith("2026-11-17_")
    assert [days.interval_on(d) for d in ("2026-11-16", "2026-11-17", "2026-11-19", "2026-11-20")] == [
        None, (0, 1440), (0, 1440), None]
    hours = TimeOff.from_input({"professional_id": "bbbbbbbb", "first_day": "2026-11-17", "start": "14:00", "end": "16:00"})
    assert hours.last_day == "2026-11-17" and hours.interval_on("2026-11-17") == (840, 960) and hours.reason == ""
    assert TimeOff.from_dict(hours.to_dict()) == hours


@pytest.mark.parametrize("payload, fragment", [
    ({"first_day": "2026-11-17"}, "escolha a profissional"),
    ({"professional_id": "bbbbbbbb"}, "data inválida"),
    ({"professional_id": "bbbbbbbb", "first_day": "2026-11-17", "last_day": "2026-11-16"}, "antes do primeiro"),
    ({"professional_id": "bbbbbbbb", "first_day": "2026-01-01", "last_day": "2026-06-30"}, "no máximo 180 dias"),
    ({"professional_id": "bbbbbbbb", "first_day": "2026-11-17", "start": "14:00"}, "início e o fim"),
    ({"professional_id": "bbbbbbbb", "first_day": "2026-11-17", "start": "14:00", "end": "14:00"}, "depois do início"),
    ({"professional_id": "bbbbbbbb", "first_day": "2026-11-17", "start": "14:10", "end": "15:00"}, "15 em 15"),
    ({"professional_id": "bbbbbbbb", "first_day": "2026-11-17", "reason": "x" * 81}, "motivo"),
])
def test_time_off_rejects_bad_input(payload, fragment):
    with pytest.raises(ValidationError, match=fragment):
        TimeOff.from_input(payload)
