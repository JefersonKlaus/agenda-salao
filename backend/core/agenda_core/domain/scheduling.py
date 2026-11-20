"""Time rules: business hours, the past, and overlap between appointments. Pure functions."""
from __future__ import annotations

from datetime import date, datetime
from typing import Iterable, Optional

from .models import STEP_MIN, Appointment, Professional, Settings, TimeOff, format_time, parse_time


def busy_intervals(appointments: Iterable[Appointment], professional_id: str) -> list[tuple[int, int]]:
    """[start, end) intervals already taken by a professional."""
    return [(a.start_min, a.end_min) for a in appointments if a.professional_id == professional_id]


def overlaps(start: int, end: int, busy: Iterable[tuple[int, int]]) -> bool:
    """Two intervals overlap if each one starts before the other ends. Touching does not count."""
    return any(start < b_end and b_start < end for b_start, b_end in busy)


def is_past(day: date, start: int, now: Optional[datetime]) -> bool:
    if now is None:
        return False
    if day != now.date():
        return day < now.date()
    return start <= now.hour * 60 + now.minute


def working_interval(settings: Settings, day: date,
                     professional: Optional[Professional] = None) -> Optional[tuple[int, int]]:
    """[start, end) in minutes when appointments can happen on `day`. The salon's business hours are
    the outer limit: a professional with hours of her own works them only inside that window; one
    without them works the whole window. None = closed / does not work that day."""
    if day.weekday() not in settings.open_days:
        return None
    start, end = parse_time(settings.opens), parse_time(settings.closes)
    if professional is not None and professional.work_hours is not None:
        shift = professional.shift_on(day.weekday())
        if shift is None:
            return None
        start, end = max(start, parse_time(shift.start)), min(end, parse_time(shift.end))
    return (start, end) if end > start else None


def away_intervals(time_offs: Iterable[TimeOff], professional_id: str, day: str) -> list[tuple[int, int]]:
    """[start, end) intervals when a professional is absent on `day` (sick, travelling...)."""
    return [i for t in time_offs if t.professional_id == professional_id and (i := t.interval_on(day))]


def fits_business_hours(settings: Settings, day: date, start: int, duration: int,
                        professional: Optional[Professional] = None) -> bool:
    interval = working_interval(settings, day, professional)
    return (interval is not None and start % STEP_MIN == 0
            and interval[0] <= start and start + duration <= interval[1])


def free_slots(settings: Settings, day: date, duration: int, busy: list[tuple[int, int]],
               now: Optional[datetime] = None, professional: Optional[Professional] = None) -> list[str]:
    """Possible start times for an appointment lasting `duration` minutes."""
    interval = working_interval(settings, day, professional)
    if interval is None:
        return []
    return [format_time(start) for start in range(interval[0], interval[1] - duration + 1, STEP_MIN)
            if not overlaps(start, start + duration, busy) and not is_past(day, start, now)]


def lock_keys(professional_id: str, date: str, start: int, duration: int) -> list[str]:
    """One key per 15-minute block. Whoever manages to create all of the keys gets the slot:
    this is what prevents two simultaneous bookings for the same time."""
    return [f"{professional_id}#{date}#{block // 60:02d}{block % 60:02d}"
            for block in range(start, start + duration, STEP_MIN)]
