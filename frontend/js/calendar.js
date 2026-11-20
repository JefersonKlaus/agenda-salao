// Calendar logic with no DOM: which days each view shows, titles, working hours and how
// overlapping appointments share a column. Unit tested in frontend/tests/ (node --test).
import { addDays } from "./util.js";

export const VIEWS = ["day", "week", "month"];
export const COLOR_COUNT = 8;                  // .c0 ... .c7 in style.css
export const DAY_NAMES = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"];   // 0 = Monday
const SHORT_DAYS = DAY_NAMES.map((name) => name.slice(0, 3));                                       // "Seg"...

export function parseIso(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
}

export function toIso(date) {
  return [date.getFullYear(), String(date.getMonth() + 1).padStart(2, "0"), String(date.getDate()).padStart(2, "0")].join("-");
}

/** 0 = Monday ... 6 = Sunday, the same numbering as the backend. */
export const weekday = (iso) => (parseIso(iso).getDay() + 6) % 7;

/** Weeks start on Monday, like the days in the salon's settings. */
export const weekStart = (iso) => addDays(iso, -weekday(iso));

export function toMinutes(time) {
  const [hh, mm] = time.split(":").map(Number);
  return hh * 60 + mm;
}

export const toTime = (minutes) => `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;

/** Same day of another month, clamped to that month's last day (31 Jan + 1 month = 28/29 Feb). */
function addMonths(iso, months) {
  const date = parseIso(iso);
  const target = new Date(date.getFullYear(), date.getMonth() + months, 1);
  const lastDay = new Date(target.getFullYear(), target.getMonth() + 1, 0).getDate();
  return toIso(new Date(target.getFullYear(), target.getMonth(), Math.min(date.getDate(), lastDay)));
}

/** The days on screen: one, a Monday-to-Sunday week, or the whole weeks that cover the month. */
export function visibleDays(view, iso) {
  let first = iso, count = 1;
  if (view === "week") { first = weekStart(iso); count = 7; }
  if (view === "month") {
    const monthFirst = iso.slice(0, 8) + "01";
    const monthLast = addDays(addMonths(monthFirst, 1), -1);
    first = weekStart(monthFirst);
    count = Math.round((parseIso(addDays(weekStart(monthLast), 7)) - parseIso(first)) / 86_400_000);
  }
  return Array.from({ length: count }, (_, i) => addDays(first, i));
}

/** The ◀ / ▶ buttons: one day, one week or one month at a time. */
export function shiftDate(view, iso, step) {
  if (view === "day") return addDays(iso, step);
  if (view === "week") return addDays(iso, 7 * step);
  return addMonths(iso, step);
}

const capitalize = (text) => text.charAt(0).toUpperCase() + text.slice(1);

export function viewTitle(view, iso) {
  if (view === "day") {
    return capitalize(parseIso(iso).toLocaleDateString("pt-BR", { weekday: "long", day: "numeric", month: "long", year: "numeric" }));
  }
  if (view === "week") {
    const days = visibleDays("week", iso);
    return new Intl.DateTimeFormat("pt-BR", { day: "numeric", month: "short", year: "numeric" })
      .formatRange(parseIso(days[0]), parseIso(days[6]));
  }
  return capitalize(parseIso(iso).toLocaleDateString("pt-BR", { month: "long", year: "numeric" }));
}

/** The salon's hours on a weekday (0 = Monday): {day, start, end}, or undefined when it is closed. */
export function salonShift(settings, day) {
  return settings.hours.find((s) => s.day === day);
}

/** [start, end] in minutes when she works that day; null = closed / day off. Mirrors the backend: the
 *  salon's hours that day are the outer limit; her own hours (when she has them) are cut to fit them. */
export function workingInterval(settings, professional, iso) {
  return weeklyInterval(settings, professional, weekday(iso));
}

/** Same as workingInterval, for a weekday (0 = Monday) instead of a date. */
export function weeklyInterval(settings, professional, day) {
  const salon = salonShift(settings, day);
  if (!salon) return null;
  let start = toMinutes(salon.start), end = toMinutes(salon.end);
  if (professional && professional.work_hours) {
    const shift = professional.work_hours.find((s) => s.day === day);
    if (!shift) return null;
    start = Math.max(start, toMinutes(shift.start));
    end = Math.min(end, toMinutes(shift.end));
  }
  return end > start ? [start, end] : null;
}

/** True when some of her hours fall outside the salon's days or hours (that part is never offered). */
export function hoursOutsideSalon(settings, workHours) {
  return (workHours || []).some((s) => {
    const salon = salonShift(settings, s.day);
    return !salon || toMinutes(s.start) < toMinutes(salon.start) || toMinutes(s.end) > toMinutes(salon.end);
  });
}

/** Times the salon is open but no professional works, in a regular week (absences, which are on
 *  specific dates, are not counted): [{day, start, end}], sorted by day. Nobody can book them. */
export function uncoveredHours(settings, professionals) {
  return [...settings.hours].sort((a, b) => a.day - b.day).flatMap((salon) => {
    const working = professionals.map((p) => weeklyInterval(settings, p, salon.day)).filter(Boolean);
    return subtractIntervals([[toMinutes(salon.start), toMinutes(salon.end)]], working)
      .map(([start, end]) => ({ day: salon.day, start: toTime(start), end: toTime(end) }));
  });
}

/** When she is away that day (sick, travelling...): [[start, end]], the whole day being [0, 1440]. */
export function awayIntervals(timeOffs, professionalId, iso) {
  return timeOffs.filter((t) => t.professional_id === professionalId && t.first_day <= iso && iso <= t.last_day)
    .map((t) => (t.start ? [toMinutes(t.start), toMinutes(t.end)] : [0, 24 * 60]));
}

/** `intervals` minus `cuts`: what is left of each interval after removing the cut parts. */
export function subtractIntervals(intervals, cuts) {
  let left = intervals.map(([s, e]) => [s, e]);
  for (const [cs, ce] of cuts) {
    left = left.flatMap(([s, e]) => [[s, Math.min(e, cs)], [Math.max(s, ce), e]].filter(([a, b]) => b > a));
  }
  return left;
}

/** When she can actually be booked that day: her working hours minus her absences. */
export function availableIntervals(settings, professional, iso, timeOffs = []) {
  const hours = workingInterval(settings, professional, iso);
  return hours ? subtractIntervals([hours], professional ? awayIntervals(timeOffs, professional.id, iso) : []) : [];
}

/** When at least one of `professionals` can be booked that day, merged into sorted, non-overlapping
 *  intervals. With no professionals registered yet, the salon's hours. */
export function openIntervals(settings, professionals, iso, timeOffs = []) {
  const list = professionals.length ? professionals : [null];
  const intervals = list.flatMap((p) => availableIntervals(settings, p, iso, timeOffs)).sort((a, b) => a[0] - b[0]);
  const merged = [];
  for (const [start, end] of intervals) {
    const last = merged.at(-1);
    if (last && start <= last[1]) last[1] = Math.max(last[1], end);
    else merged.push([start, end]);
  }
  return merged;
}

/** When the salon is open that day but no professional can be booked (their hours, their absences):
 *  [[start, end]]. Shown differently from "closed": it is a staffing gap, not the salon's choice.
 *  Empty when there are no professionals yet (the agenda shows the salon's hours as open then). */
export function uncoveredIntervals(settings, professionals, iso, timeOffs = []) {
  const salon = professionals.length ? workingInterval(settings, null, iso) : null;
  return salon ? subtractIntervals([salon], openIntervals(settings, professionals, iso, timeOffs)) : [];
}

/** The gaps between `open` intervals inside [from, to]: the hatched (nobody works) parts of a column. */
export function closedIntervals(open, from, to) {
  const gaps = [];
  let cursor = from;
  for (const [start, end] of open) {
    if (start > cursor) gaps.push([cursor, Math.min(start, to)]);
    cursor = Math.max(cursor, end);
  }
  if (cursor < to) gaps.push([cursor, to]);
  return gaps.filter(([start, end]) => end > start);
}

/** Whole hours shown by the time grid: from the salon's earliest opening to its latest closing (every
 *  day shares one grid), stretched to fit any appointment outside them (made before the hours changed). */
export function hourRange(settings, appointments) {
  let first = Math.min(...settings.hours.map((s) => toMinutes(s.start)));
  let last = Math.max(...settings.hours.map((s) => toMinutes(s.end)));
  for (const a of appointments) {
    first = Math.min(first, toMinutes(a.start));
    last = Math.max(last, toMinutes(a.start) + a.duration_min);
  }
  return [Math.floor(first / 60), Math.min(24, Math.ceil(last / 60))];
}

/** Google Calendar style: appointments that overlap are placed side by side. Each group of
 *  (transitively) overlapping events is split into columns; `cols` is that group's column count.
 *  Input: [{start, end, ...}] in minutes. Output: the same objects plus {col, cols}. */
export function layoutColumns(events) {
  const sorted = [...events].sort((a, b) => a.start - b.start || b.end - a.end);
  const placed = [];
  let group = [], columnEnds = [], groupEnd = -Infinity;
  const closeGroup = () => {
    for (const e of group) placed.push({ ...e, cols: columnEnds.length });
    group = []; columnEnds = []; groupEnd = -Infinity;
  };
  for (const e of sorted) {
    if (group.length && e.start >= groupEnd) closeGroup();
    let col = columnEnds.findIndex((end) => end <= e.start);
    if (col === -1) col = columnEnds.push(e.end) - 1;
    else columnEnds[col] = e.end;
    group.push({ ...e, col });
    groupEnd = Math.max(groupEnd, e.end);
  }
  closeGroup();
  return placed;
}

/** Each professional keeps the same color everywhere (the API returns them sorted by name). */
export function colorClass(professionals, professionalId) {
  const index = professionals.findIndex((p) => p.id === professionalId);
  return index === -1 ? "c-none" : `c${index % COLOR_COUNT}`;
}

/** "Seg a Sex 09:00–18:00 · Sáb 09:00–13:00" for the professionals list. */
export function workHoursSummary(workHours) {
  if (workHours == null) return "Horário do salão";
  if (workHours.length === 0) return "Não trabalha em nenhum dia";
  const byTime = new Map();
  for (const s of [...workHours].sort((a, b) => a.day - b.day)) {
    const key = `${s.start}–${s.end}`;
    byTime.set(key, [...(byTime.get(key) || []), s.day]);
  }
  return [...byTime].map(([time, days]) => `${dayList(days)} ${time}`).join(" · ");
}

/** [0,1,2,3,4] -> "Seg a Sex"; [0,2] -> "Seg, Qua". Runs of 3+ consecutive days are shortened. */
function dayList(days) {
  const parts = [];
  for (let i = 0; i < days.length;) {
    let j = i;
    while (j + 1 < days.length && days[j + 1] === days[j] + 1) j++;
    if (j - i >= 2) parts.push(`${SHORT_DAYS[days[i]]} a ${SHORT_DAYS[days[j]]}`);
    else for (let k = i; k <= j; k++) parts.push(SHORT_DAYS[days[k]]);
    i = j + 1;
  }
  return parts.join(", ");
}
