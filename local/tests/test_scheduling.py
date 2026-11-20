from datetime import date, datetime

import pytest

from agenda_core.domain.models import Professional, Settings, Shift, TimeOff
from agenda_core.domain.scheduling import (away_intervals, fits_business_hours, free_slots, is_past, lock_keys, overlaps,
                              working_interval)

SETTINGS = Settings(tuple(Shift(day, "09:00", "12:00") for day in range(6)))      # Monday to Saturday
MONDAY, SUNDAY = date(2026, 11, 16), date(2026, 11, 22)


@pytest.mark.parametrize("a, b, expected", [
    ((600, 660), (630, 690), True),     # overlaps in the middle
    ((600, 660), (660, 720), False),    # touching: the end of one is the start of the other
    ((600, 660), (540, 600), False),
    ((600, 660), (600, 660), True),     # identical
    ((600, 720), (630, 660), True),     # one inside the other
    ((630, 660), (600, 720), True),
])
def test_interval_overlap(a, b, expected):
    assert overlaps(a[0], a[1], [b]) is expected


def test_free_slots_with_nothing_busy():
    times = free_slots(SETTINGS, MONDAY, 60, [])
    assert times[0] == "09:00" and times[-1] == "11:00" and len(times) == 9


def test_appointment_cannot_go_past_closing_time():
    assert free_slots(SETTINGS, MONDAY, 180, []) == ["09:00"]
    assert free_slots(SETTINGS, MONDAY, 195, []) == []


def test_busy_slots_disappear_and_neighbours_remain():
    times = free_slots(SETTINGS, MONDAY, 60, [(600, 660)])             # busy 10:00-11:00
    assert "10:00" not in times and "09:30" not in times and "10:30" not in times
    assert "09:00" in times and "11:00" in times


def test_closed_day_has_no_slots():
    assert free_slots(SETTINGS, SUNDAY, 30, []) == []


def test_past_slots_disappear_only_today():
    now = datetime(2026, 11, 16, 10, 20)
    times = free_slots(SETTINGS, MONDAY, 30, [], now)
    assert times[0] == "10:30"
    assert free_slots(SETTINGS, date(2026, 11, 17), 30, [], now)[0] == "09:00"
    assert free_slots(SETTINGS, date(2026, 11, 15), 30, [], now) == []


def test_is_past():
    now = datetime(2026, 11, 16, 10, 0)
    assert is_past(MONDAY, 600, now) and not is_past(MONDAY, 615, now)
    assert is_past(date(2026, 11, 15), 1000, now) and not is_past(date(2026, 11, 17), 0, now)
    assert not is_past(MONDAY, 0, None)


def test_fits_business_hours():
    assert fits_business_hours(SETTINGS, MONDAY, 540, 180)
    assert not fits_business_hours(SETTINGS, MONDAY, 540, 195)       # goes past closing time
    assert not fits_business_hours(SETTINGS, MONDAY, 525, 30)        # before opening
    assert not fits_business_hours(SETTINGS, MONDAY, 545, 30)        # off the 15-minute step
    assert not fits_business_hours(SETTINGS, SUNDAY, 600, 30)


def test_locks_cover_each_block_except_the_end():
    assert lock_keys("p", "2026-11-17", 600, 45) == [
        "p#2026-11-17#1000", "p#2026-11-17#1015", "p#2026-11-17#1030"]
    # 10:00-10:30 and 10:30-11:00 do not share any lock
    assert not set(lock_keys("p", "d", 600, 30)) & set(lock_keys("p", "d", 630, 30))


def ana(*shifts):
    return Professional("bbbbbbbb", "Ana", (), None if shifts == (None,) else tuple(shifts))


@pytest.mark.parametrize("professional, day, expected", [
    (None, MONDAY, (540, 720)),                                             # salon: 09:00-12:00
    (None, SUNDAY, None),                                                   # salon closed on Sundays
    (ana(None), MONDAY, (540, 720)),                                        # no hours of her own: salon's
    (ana(None), SUNDAY, None),
    (ana(Shift(0, "10:00", "11:00")), MONDAY, (600, 660)),                  # her own hours...
    (ana(Shift(0, "07:00", "20:00")), MONDAY, (540, 720)),                  # ...only inside the salon's
    (ana(Shift(0, "10:30", "15:00")), MONDAY, (630, 720)),
    (ana(Shift(0, "13:00", "18:00")), MONDAY, None),                        # only after closing: nothing
    (ana(Shift(6, "09:00", "12:00")), SUNDAY, None),                        # salon closed: nobody works
    (ana(Shift(1, "09:00", "12:00")), MONDAY, None),                        # does not work on Mondays
    (ana(), MONDAY, None),                                                  # works no day at all
])
def test_working_interval(professional, day, expected):
    assert working_interval(SETTINGS, day, professional) == expected


def test_free_slots_and_fits_follow_the_professional_hours():
    part_time = ana(Shift(0, "10:00", "11:30"))
    assert free_slots(SETTINGS, MONDAY, 60, [], professional=part_time) == ["10:00", "10:15", "10:30"]
    assert free_slots(SETTINGS, MONDAY, 60, [(600, 660)], professional=part_time) == []
    assert free_slots(SETTINGS, date(2026, 11, 17), 60, [], professional=part_time) == []      # Tuesday: off
    assert fits_business_hours(SETTINGS, MONDAY, 600, 90, part_time)
    assert not fits_business_hours(SETTINGS, MONDAY, 540, 60, part_time)    # the salon is open, she is not
    assert fits_business_hours(SETTINGS, MONDAY, 540, 60)


def test_away_intervals():
    offs = [TimeOff("2026-11-16_aaaaaaaa", "p1", "2026-11-16", "2026-11-18", None, None, "Viagem"),
            TimeOff("2026-11-17_bbbbbbbb", "p1", "2026-11-17", "2026-11-17", "14:00", "16:00", ""),
            TimeOff("2026-11-17_cccccccc", "p2", "2026-11-17", "2026-11-17", "09:00", "10:00", "")]
    assert away_intervals(offs, "p1", "2026-11-17") == [(0, 1440), (840, 960)]
    assert away_intervals(offs, "p2", "2026-11-17") == [(540, 600)]
    assert away_intervals(offs, "p1", "2026-11-19") == []


def test_each_day_has_its_own_salon_hours():
    settings = Settings((Shift(0, "09:00", "12:00"), Shift(5, "08:00", "10:00")))     # Monday and Saturday
    saturday = date(2026, 11, 21)
    assert working_interval(settings, MONDAY) == (540, 720)
    assert working_interval(settings, saturday) == (480, 600)
    assert working_interval(settings, date(2026, 11, 17)) is None                     # Tuesday: closed
    assert free_slots(settings, saturday, 60, []) == ["08:00", "08:15", "08:30", "08:45", "09:00"]
    her = Professional("p1", "Ana", (), (Shift(5, "09:00", "18:00"),))
    assert working_interval(settings, saturday, her) == (540, 600)                    # cut at Saturday's closing
