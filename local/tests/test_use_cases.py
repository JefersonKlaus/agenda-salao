import threading

import pytest

from agenda_core.application import LIMITS
from agenda_core.domain.errors import NotFound, SlotConflict, ValidationError
from conftest import OTHER, OWNER, booking, salon_hours


def test_create_list_and_sort(agenda):
    for name in ("Nails", "aloe", "Haircut"):
        agenda.create(OWNER, "service", {"name": name, "duration_min": 30, "price_cents": 100})
    assert [s.name for s in agenda.list_items(OWNER, "service")] == ["aloe", "Haircut", "Nails"]


def test_each_salon_only_sees_its_own_data(agenda, salon):
    haircut, _, ana = salon
    assert agenda.list_items(OTHER, "service") == [] and agenda.list_items(OTHER, "professional") == []
    with pytest.raises(NotFound):
        agenda.update(OTHER, "service", haircut.id, {"name": "X", "duration_min": 30, "price_cents": 1})
    with pytest.raises(NotFound):
        agenda.remove(OTHER, "professional", ana.id)
    agenda.book(OWNER, booking(haircut, ana))
    assert agenda.day_schedule(OTHER, "2026-11-17") == []


def test_salon_cannot_book_with_another_salons_service(agenda, salon):
    haircut, _, ana = salon
    with pytest.raises(NotFound):
        agenda.book(OTHER, booking(haircut, ana))


def test_update_keeps_the_id(agenda, salon):
    haircut = salon[0]
    updated = agenda.update(OWNER, "service", haircut.id, {"name": "Long haircut", "duration_min": 45, "price_cents": 9000})
    assert updated.id == haircut.id and agenda.list_items(OWNER, "service")[0] == updated


def test_professional_only_accepts_existing_services(agenda, salon):
    with pytest.raises(ValidationError):
        agenda.create(OWNER, "professional", {"name": "Bia", "services": ["deadbeef"]})


def test_removing_a_service_removes_it_from_the_professionals(agenda, salon):
    haircut, nails, ana = salon
    agenda.remove(OWNER, "service", haircut.id)
    assert agenda.list_items(OWNER, "professional")[0].services == (nails.id,)
    with pytest.raises(NotFound):
        agenda.remove(OWNER, "service", haircut.id)


def test_item_limit(agenda, monkeypatch):
    monkeypatch.setitem(LIMITS, "service", 2)
    for i in range(2):
        agenda.create(OWNER, "service", {"name": f"S{i}", "duration_min": 30, "price_cents": 1})
    with pytest.raises(ValidationError):
        agenda.create(OWNER, "service", {"name": "S3", "duration_min": 30, "price_cents": 1})


def test_booking_keeps_a_copy_of_the_service_data(agenda, salon):
    haircut, _, ana = salon
    appt = agenda.book(OWNER, booking(haircut, ana))
    assert (appt.service_name, appt.price_cents, appt.duration_min) == ("Haircut", 8000, 60)
    assert appt.client_phone == "11988887777" and appt.id.startswith("2026-11-17_1000_")
    agenda.update(OWNER, "service", haircut.id, {"name": "Other", "duration_min": 30, "price_cents": 1})
    assert agenda.day_schedule(OWNER, "2026-11-17")[0].service_name == "Haircut"     # history intact


def test_adjacent_slots_are_accepted_and_overlaps_are_refused(agenda, salon):
    haircut, nails, ana = salon
    agenda.book(OWNER, booking(haircut, ana, "10:00"))                 # 10:00-11:00
    agenda.book(OWNER, booking(haircut, ana, "11:00"))                 # touches: allowed
    agenda.book(OWNER, booking(haircut, ana, "09:00"))                 # 09:00-10:00: allowed
    for start in ("09:30", "10:00", "10:30", "10:45"):
        with pytest.raises(ValidationError, match="ocupado"):
            agenda.book(OWNER, booking(nails, ana, start))


def test_two_professionals_can_work_at_the_same_time(agenda, salon):
    haircut, nails, ana = salon
    bia = agenda.create(OWNER, "professional", {"name": "Bia", "services": [haircut.id]})
    agenda.book(OWNER, booking(haircut, ana))
    agenda.book(OWNER, booking(haircut, bia))
    assert len(agenda.day_schedule(OWNER, "2026-11-17")) == 2


# The expected fragments are from the (Portuguese) error messages shown to the user.
@pytest.mark.parametrize("extra, fragment", [
    ({"date": "2026-11-22"}, "fora do expediente"),                     # Sunday
    ({"start": "08:45"}, "fora do expediente"),
    ({"start": "18:30"}, "fora do expediente"),                         # 60 min goes past 19:00
    ({"start": "10:10"}, "fora do expediente"),                         # off the 15-minute step
    ({"start": "9h"}, "hora inválida"),
    ({"date": "tomorrow"}, "data inválida"),
    ({"client_name": ""}, "cliente_nome"),
    ({"client_phone": "123"}, "DDD"),
])
def test_refused_bookings(agenda, salon, extra, fragment):
    haircut, _, ana = salon
    with pytest.raises(ValidationError, match=fragment):
        agenda.book(OWNER, booking(haircut, ana, **extra))


@pytest.mark.parametrize("extra", [{"date": "2026-11-16", "start": "09:30"},    # today, before now (10:00)
                                   {"date": "2026-11-14"}])                  # last Saturday
def test_booking_what_already_happened(agenda, salon, extra):
    """Only the manager books (the API refuses employees), and she may record what already happened."""
    haircut, _, ana = salon
    assert agenda.book(OWNER, booking(haircut, ana, **extra)).professional_id == ana.id


def test_professional_who_does_not_perform_the_service(agenda, salon):
    haircut, nails, ana = salon
    bia = agenda.create(OWNER, "professional", {"name": "Bia", "services": [nails.id]})
    with pytest.raises(ValidationError, match="não faz"):
        agenda.book(OWNER, booking(haircut, bia))


def test_made_up_ids(agenda, salon):
    haircut, _, ana = salon
    with pytest.raises(NotFound):
        agenda.book(OWNER, {**booking(haircut, ana), "service_id": "deadbeef"})
    with pytest.raises(NotFound):
        agenda.book(OWNER, {**booking(haircut, ana), "professional_id": None})


def test_availability_reflects_the_appointments(agenda, salon):
    haircut, nails, ana = salon
    before = agenda.availability(OWNER, "2026-11-17", haircut.id, ana.id)
    assert before[0] == "09:00" and "10:00" in before
    agenda.book(OWNER, booking(haircut, ana, "10:00"))
    after = agenda.availability(OWNER, "2026-11-17", haircut.id, ana.id)
    assert "10:00" not in after and "09:30" not in after and "11:00" in after
    assert "09:00" in after and "09:15" not in after
    assert agenda.availability(OWNER, "2026-11-22", haircut.id, ana.id) == []


def test_settings_change_the_availability(agenda, salon):
    haircut, _, ana = salon
    assert agenda.settings(OWNER).shift_on(1).start == "09:00"
    agenda.save_settings(OWNER, salon_hours([1], "13:00", "15:00"))
    assert agenda.availability(OWNER, "2026-11-17", haircut.id, ana.id) == ["13:00", "13:15", "13:30", "13:45", "14:00"]
    assert agenda.availability(OWNER, "2026-11-18", haircut.id, ana.id) == []
    assert agenda.settings(OTHER).shift_on(1).start == "09:00"          # the other salon did not change


def test_each_day_its_own_salon_hours(agenda, salon):
    haircut, _, ana = salon
    agenda.save_settings(OWNER, {"hours": [{"day": 1, "start": "09:00", "end": "11:00"},      # Tuesday
                                           {"day": 2, "start": "14:00", "end": "16:00"}]})    # Wednesday
    assert agenda.availability(OWNER, "2026-11-17", haircut.id, ana.id) == ["09:00", "09:15", "09:30", "09:45", "10:00"]
    assert agenda.availability(OWNER, "2026-11-18", haircut.id, ana.id)[0] == "14:00"
    with pytest.raises(ValidationError, match="fora do expediente do salão"):
        agenda.book(OWNER, booking(haircut, ana, "14:00", "2026-11-17"))       # Wednesday's hours, on Tuesday
    with pytest.raises(ValidationError, match=r"Terça: fora do horário do salão \(09:00–11:00\)"):
        agenda.update(OWNER, "professional", ana.id, {"name": "Ana", "services": [haircut.id], "work_hours": [
            {"day": 1, "start": "14:00", "end": "16:00"}]})


def test_cancelling_frees_the_slot(agenda, salon):
    haircut, _, ana = salon
    appt = agenda.book(OWNER, booking(haircut, ana))
    assert agenda.cancel(OWNER, appt.id).id == appt.id
    assert agenda.day_schedule(OWNER, "2026-11-17") == []
    agenda.book(OWNER, booking(haircut, ana))                          # fits again
    with pytest.raises(NotFound):
        agenda.cancel(OWNER, appt.id)


def test_cancel_from_another_salon_or_weird_id(agenda, salon):
    haircut, _, ana = salon
    appt = agenda.book(OWNER, booking(haircut, ana))
    for owner, id in ((OTHER, appt.id), (OWNER, "../x"), (OWNER, ""), (OWNER, None), (OWNER, "2026-11-17_1000_zzzzzzzz")):
        with pytest.raises(NotFound):
            agenda.cancel(owner, id)
    assert len(agenda.day_schedule(OWNER, "2026-11-17")) == 1


def test_day_schedule_sorted_by_time(agenda, salon):
    haircut, nails, ana = salon
    for start in ("15:00", "09:00", "11:30"):
        agenda.book(OWNER, booking(nails, ana, start))
    assert [a.start for a in agenda.day_schedule(OWNER, "2026-11-17")] == ["09:00", "11:30", "15:00"]


def test_simultaneous_bookings_for_the_same_slot_only_one_wins(agenda, salon):
    """Fires several bookings at the same time for the same slot: exactly one succeeds."""
    haircut, _, ana = salon
    results = []

    def attempt():
        try:
            agenda.book(OWNER, booking(haircut, ana, "14:00"))
            results.append("ok")
        except (ValidationError, SlotConflict):
            results.append("refused")

    threads = [threading.Thread(target=attempt) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results.count("ok") == 1 and len(agenda.day_schedule(OWNER, "2026-11-17")) == 1


PART_TIME = [{"day": 1, "start": "10:00", "end": "14:00"}]                 # Tuesdays only, 10:00-14:00


def test_availability_follows_the_professional_work_hours(agenda, salon):
    haircut, _, ana = salon
    agenda.update(OWNER, "professional", ana.id, {"name": "Ana", "services": [haircut.id], "work_hours": PART_TIME})
    assert agenda.availability(OWNER, "2026-11-17", haircut.id, ana.id) == [
        "10:00", "10:15", "10:30", "10:45", "11:00", "11:15", "11:30", "11:45", "12:00", "12:15", "12:30", "12:45", "13:00"]
    assert agenda.availability(OWNER, "2026-11-18", haircut.id, ana.id) == []        # Wednesday: day off


@pytest.mark.parametrize("start, date, fragment", [
    ("09:00", "2026-11-17", "não trabalha"), ("13:30", "2026-11-17", "não trabalha"),   # 13:30-14:30
    ("10:00", "2026-11-18", "não trabalha"),
    ("08:00", "2026-11-17", "fora do expediente do salão"),               # the salon's window comes first
])
def test_booking_outside_the_professional_work_hours_is_refused(agenda, salon, start, date, fragment):
    haircut, _, ana = salon
    agenda.update(OWNER, "professional", ana.id, {"name": "Ana", "services": [haircut.id], "work_hours": PART_TIME})
    with pytest.raises(ValidationError, match=fragment):
        agenda.book(OWNER, booking(haircut, ana, start, date))
    agenda.book(OWNER, booking(haircut, ana, "13:00"))                      # 13:00-14:00 fits exactly


@pytest.mark.parametrize("shift, fragment", [
    ({"day": 6, "start": "10:00", "end": "12:00"}, "Domingo: o salão não abre nesse dia"),
    ({"day": 1, "start": "07:00", "end": "12:00"}, r"Terça: fora do horário do salão \(09:00–19:00\)"),
    ({"day": 1, "start": "12:00", "end": "19:15"}, "Terça: fora do horário do salão"),
])
def test_professional_hours_must_fit_inside_the_salon_hours(agenda, salon, shift, fragment):
    haircut, _, ana = salon
    with pytest.raises(ValidationError, match=fragment):
        agenda.update(OWNER, "professional", ana.id, {"name": "Ana", "services": [haircut.id], "work_hours": [shift]})
    with pytest.raises(ValidationError, match=fragment):
        agenda.create(OWNER, "professional", {"name": "Bia", "services": [], "work_hours": [shift]})
    agenda.update(OWNER, "professional", ana.id, {"name": "Ana", "services": [haircut.id], "work_hours": [
        {"day": 1, "start": "09:00", "end": "19:00"}]})                                 # exactly the window: fine


def test_narrowing_the_salon_hours_later_cuts_her_hours(agenda, salon):
    haircut, _, ana = salon
    agenda.update(OWNER, "professional", ana.id, {"name": "Ana", "services": [haircut.id], "work_hours": PART_TIME})
    agenda.save_settings(OWNER, salon_hours([1], "12:00", "19:00"))
    assert agenda.availability(OWNER, "2026-11-17", haircut.id, ana.id) == ["12:00", "12:15", "12:30", "12:45", "13:00"]
    with pytest.raises(ValidationError, match="fora do expediente do salão"):
        agenda.book(OWNER, booking(haircut, ana, "10:00"))


def test_two_professionals_same_time_each_with_her_own_schedule(agenda, salon):
    haircut, _, ana = salon
    bia = agenda.create(OWNER, "professional", {"name": "Bia", "services": [haircut.id], "work_hours": [
        {"day": 1, "start": "10:00", "end": "14:00"}]})
    agenda.book(OWNER, booking(haircut, ana, "10:00"))                               # follows the salon
    agenda.book(OWNER, booking(haircut, bia, "10:00"))                               # same time, her own hours
    assert "10:00" not in agenda.availability(OWNER, "2026-11-17", haircut.id, ana.id)
    assert "10:00" not in agenda.availability(OWNER, "2026-11-17", haircut.id, bia.id)
    assert [(a.start, a.professional_name) for a in agenda.day_schedule(OWNER, "2026-11-17")] == [
        ("10:00", "Ana"), ("10:00", "Bia")]


def test_removing_a_service_keeps_the_professional_work_hours(agenda, salon):
    haircut, nails, ana = salon
    agenda.update(OWNER, "professional", ana.id,
                  {"name": "Ana", "services": [haircut.id, nails.id], "work_hours": PART_TIME})
    agenda.remove(OWNER, "service", haircut.id)
    [prof] = agenda.list_items(OWNER, "professional")
    assert prof.services == (nails.id,) and prof.work_hours[0].start == "10:00"


def test_schedule_between_sorts_and_isolates_salons(agenda, salon):
    haircut, nails, ana = salon
    agenda.save_settings(OWNER, salon_hours(range(7), "09:00", "19:00"))
    for date, start in (("2026-11-22", "09:00"), ("2026-11-17", "15:00"), ("2026-11-17", "10:00"), ("2026-11-23", "10:00")):
        agenda.book(OWNER, booking(nails, ana, start, date))
    week = agenda.schedule_between(OWNER, "2026-11-16", "2026-11-22")
    assert [(a.date, a.start) for a in week] == [("2026-11-17", "10:00"), ("2026-11-17", "15:00"), ("2026-11-22", "09:00")]
    assert agenda.schedule_between(OTHER, "2026-11-16", "2026-11-22") == []


@pytest.mark.parametrize("first, last, fragment", [
    ("2026-11-22", "2026-11-16", "fim vem antes"), ("2026-11-01", "2027-01-02", "no máximo 62 dias"),
    ("2026-11-16", None, "data inválida"), (None, "2026-11-16", "data inválida"), ("2026-11-16", "x", "data inválida"),
])
def test_schedule_between_rejects_bad_periods(agenda, first, last, fragment):
    with pytest.raises(ValidationError, match=fragment):
        agenda.schedule_between(OWNER, first, last)


def test_schedule_between_accepts_the_longest_period(agenda):
    assert agenda.schedule_between(OWNER, "2026-11-01", "2027-01-01") == []     # 62 days


# ---------------------------------------------------------------- disabled services

def test_disabled_service_is_not_offered_until_enabled_again(agenda, salon):
    haircut, _, ana = salon
    appt = agenda.book(OWNER, booking(haircut, ana, "10:00"))
    agenda.update(OWNER, "service", haircut.id, {"name": "Haircut", "duration_min": 60, "price_cents": 8000, "active": False})
    with pytest.raises(ValidationError, match="desativado"):
        agenda.availability(OWNER, "2026-11-17", haircut.id, ana.id)
    with pytest.raises(ValidationError, match="desativado"):
        agenda.book(OWNER, booking(haircut, ana, "14:00"))
    assert agenda.day_schedule(OWNER, "2026-11-17") == [appt]                         # existing ones stay
    agenda.update(OWNER, "service", haircut.id, {"name": "Corte", "duration_min": 60, "price_cents": 9000})
    assert agenda.list_items(OWNER, "service")[0].active is False                     # editing keeps it disabled
    agenda.update(OWNER, "service", haircut.id, {"name": "Corte", "duration_min": 60, "price_cents": 9000, "active": True})
    agenda.book(OWNER, booking(haircut, ana, "14:00"))


# ---------------------------------------------------------------- absences

def absence(prof, first="2026-11-17", last=None, start=None, end=None, reason="Doente"):
    return {"professional_id": prof.id, "first_day": first, "last_day": last or first, "start": start, "end": end,
            "reason": reason}


def test_whole_day_absence_blocks_her_only(agenda, salon):
    haircut, _, ana = salon
    bia = agenda.create(OWNER, "professional", {"name": "Bia", "services": [haircut.id]})
    agenda.create_time_off(OWNER, absence(ana, "2026-11-17", "2026-11-18"))
    for day in ("2026-11-17", "2026-11-18"):
        assert agenda.availability(OWNER, day, haircut.id, ana.id) == []
    assert agenda.availability(OWNER, "2026-11-19", haircut.id, ana.id)[0] == "09:00"
    assert agenda.availability(OWNER, "2026-11-17", haircut.id, bia.id)[0] == "09:00"
    with pytest.raises(ValidationError, match="ausente"):
        agenda.book(OWNER, booking(haircut, ana, "10:00"))
    agenda.book(OWNER, booking(haircut, bia, "10:00"))


def test_absence_of_some_hours(agenda, salon):
    haircut, nails, ana = salon
    agenda.create_time_off(OWNER, absence(ana, start="10:00", end="12:00", reason="Médico"))
    free = agenda.availability(OWNER, "2026-11-17", haircut.id, ana.id)
    assert "09:00" in free and "09:15" not in free and "11:00" not in free and "12:00" in free
    with pytest.raises(ValidationError, match="ausente"):
        agenda.book(OWNER, booking(nails, ana, "11:30"))
    agenda.book(OWNER, booking(haircut, ana, "09:00"))                                # ends as she leaves
    agenda.book(OWNER, booking(haircut, ana, "12:00"))


def test_absence_reports_her_appointments_inside_it(agenda, salon):
    haircut, nails, ana = salon
    bia = agenda.create(OWNER, "professional", {"name": "Bia", "services": [haircut.id]})
    inside = agenda.book(OWNER, booking(haircut, ana, "10:00"))
    agenda.book(OWNER, booking(haircut, ana, "15:00"))                                # outside the hours
    agenda.book(OWNER, booking(haircut, bia, "10:00"))                                # someone else
    agenda.book(OWNER, booking(haircut, ana, "10:00", "2026-11-19"))                  # another day
    time_off, affected = agenda.create_time_off(OWNER, absence(ana, start="09:00", end="12:00"))
    assert affected == [inside]
    assert agenda.day_schedule(OWNER, "2026-11-17").count(inside) == 1                # still there, to be moved
    assert agenda.time_off_between(OWNER, "2026-11-16", "2026-11-22") == [time_off]


def test_deleting_an_absence_frees_her_again(agenda, salon):
    haircut, _, ana = salon
    time_off, _ = agenda.create_time_off(OWNER, absence(ana))
    with pytest.raises(NotFound):
        agenda.delete_time_off(OTHER, time_off.id)                                    # another salon's
    agenda.delete_time_off(OWNER, time_off.id)
    assert agenda.availability(OWNER, "2026-11-17", haircut.id, ana.id)[0] == "09:00"
    for bad in (time_off.id, "../x", None, "2026-11-17_zzzzzzzz"):
        with pytest.raises(NotFound):
            agenda.delete_time_off(OWNER, bad)


def test_absence_needs_an_existing_professional_of_this_salon(agenda, salon):
    _, _, ana = salon
    with pytest.raises(NotFound):
        agenda.create_time_off(OTHER, absence(ana))
    assert agenda.time_off_between(OTHER, "2026-11-16", "2026-11-22") == []


# ---------------------------------------------------------------- changing the professional

def test_change_professional_moves_the_appointment_and_frees_the_old_time(agenda, salon):
    haircut, _, ana = salon
    bia = agenda.create(OWNER, "professional", {"name": "Bia", "services": [haircut.id]})
    appt = agenda.book(OWNER, booking(haircut, ana, "10:00"))
    moved = agenda.change_professional(OWNER, appt.id, {"professional_id": bia.id})
    assert (moved.id, moved.start, moved.professional_id, moved.professional_name) == (appt.id, "10:00", bia.id, "Bia")
    assert agenda.day_schedule(OWNER, "2026-11-17") == [moved]
    assert "10:00" in agenda.availability(OWNER, "2026-11-17", haircut.id, ana.id)     # Ana is free again
    assert "10:00" not in agenda.availability(OWNER, "2026-11-17", haircut.id, bia.id)
    agenda.book(OWNER, booking(haircut, ana, "10:00"))                                # and can be booked
    with pytest.raises(ValidationError, match="ocupado"):
        agenda.book(OWNER, booking(haircut, bia, "10:30"))


def test_change_professional_is_refused_when_she_cannot_take_it(agenda, salon):
    haircut, nails, ana = salon
    appt = agenda.book(OWNER, booking(haircut, ana, "10:00"))
    nails_only = agenda.create(OWNER, "professional", {"name": "Bia", "services": [nails.id]})
    busy = agenda.create(OWNER, "professional", {"name": "Carla", "services": [haircut.id]})
    agenda.book(OWNER, booking(haircut, busy, "10:30"))
    away = agenda.create(OWNER, "professional", {"name": "Duda", "services": [haircut.id]})
    agenda.create_time_off(OWNER, absence(away, start="09:00", end="10:30"))
    off_day = agenda.create(OWNER, "professional", {"name": "Eva", "services": [haircut.id], "work_hours": [
        {"day": 0, "start": "09:00", "end": "19:00"}]})
    for prof, fragment in ((nails_only, "não faz"), (busy, "ocupado"), (away, "ausente"), (off_day, "não trabalha"),
                           (ana, "já é com essa profissional")):
        with pytest.raises(ValidationError, match=fragment):
            agenda.change_professional(OWNER, appt.id, {"professional_id": prof.id})
    for owner, id, prof_id in ((OWNER, "2026-11-17_1000_zzzzzzzz", busy.id), (OTHER, appt.id, busy.id),
                               (OWNER, appt.id, "deadbeef"), (OWNER, appt.id, None)):
        with pytest.raises(NotFound):
            agenda.change_professional(owner, id, {"professional_id": prof_id})
    assert agenda.day_schedule(OWNER, "2026-11-17")[0] == appt                        # untouched
