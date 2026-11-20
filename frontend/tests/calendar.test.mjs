// Unit tests for the calendar logic. Run:  node --test frontend/tests/*.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  availableIntervals, awayIntervals, closedIntervals, colorClass, hourRange, hoursOutsideSalon, layoutColumns,
  openIntervals, shiftDate, subtractIntervals, toMinutes, toTime, uncoveredHours, uncoveredIntervals, viewTitle, visibleDays, weekday,
  weekStart, workHoursSummary, workingInterval,
} from "../js/calendar.js";
import { salonNow } from "../js/util.js";

test("weekday and week start use Monday = 0, like the backend", () => {
  assert.equal(weekday("2026-11-16"), 0);                      // Monday
  assert.equal(weekday("2026-11-22"), 6);                      // Sunday
  assert.equal(weekStart("2026-11-22"), "2026-11-16");
  assert.equal(weekStart("2026-11-16"), "2026-11-16");
  assert.equal(weekStart("2027-01-01"), "2026-12-28");         // across the year
});

test("visible days for each view", () => {
  assert.deepEqual(visibleDays("day", "2026-11-18"), ["2026-11-18"]);
  const week = visibleDays("week", "2026-11-18");
  assert.deepEqual([week.length, week[0], week[6]], [7, "2026-11-16", "2026-11-22"]);
  const month = visibleDays("month", "2026-11-18");           // Nov 2026: starts on Sunday -> 6 rows
  assert.deepEqual([month.length, month[0], month.at(-1)], [42, "2026-10-26", "2026-12-06"]);
  const feb = visibleDays("month", "2027-02-10");             // Feb 2027 starts on a Monday
  assert.deepEqual([feb.length, feb[0], feb.at(-1)], [28, "2027-02-01", "2027-02-28"]);
  for (const iso of ["2026-03-05", "2026-10-20", "2026-12-31"]) {
    const days = visibleDays("month", iso);
    assert.equal(days.length % 7, 0);
    assert.equal(weekday(days[0]), 0);
    assert.ok(days.includes(iso.slice(0, 8) + "01"));
    assert.equal(new Set(days).size, days.length);
  }
});

test("navigation steps", () => {
  assert.equal(shiftDate("day", "2026-12-31", 1), "2027-01-01");
  assert.equal(shiftDate("week", "2026-11-18", -1), "2026-11-11");
  assert.equal(shiftDate("month", "2026-01-31", 1), "2026-02-28");        // clamped to the month's end
  assert.equal(shiftDate("month", "2028-01-31", 1), "2028-02-29");        // leap year
  assert.equal(shiftDate("month", "2026-01-15", -1), "2025-12-15");
});

test("titles are in Portuguese, like Google Calendar's", () => {
  assert.equal(viewTitle("day", "2026-11-16"), "Segunda-feira, 16 de novembro de 2026");
  const plain = (text) => text.replace(/\s/g, " ");           // Intl uses thin spaces around the dash
  assert.equal(plain(viewTitle("week", "2026-11-18")), "16 – 22 de nov. de 2026");
  assert.equal(plain(viewTitle("week", "2026-12-02")), "30 de nov. – 6 de dez. de 2026");
  assert.equal(viewTitle("month", "2026-11-18"), "Novembro de 2026");
});

test("time conversions", () => {
  assert.equal(toMinutes("09:30"), 570);
  assert.equal(toTime(570), "09:30");
  assert.equal(toTime(0), "00:00");
});

const shifts = (days, start, end) => days.map((day) => ({ day, start, end }));

const SALON = { hours: shifts([0, 1, 2, 3, 4, 5], "09:00", "19:00") };           // Monday to Saturday

test("working interval mirrors the backend rule: her hours, inside the salon's", () => {
  assert.deepEqual(workingInterval(SALON, null, "2026-11-16"), [540, 1140]);
  assert.equal(workingInterval(SALON, null, "2026-11-22"), null);                    // salon closed on Sunday
  assert.deepEqual(workingInterval(SALON, { work_hours: null }, "2026-11-18"), [540, 1140]);
  const ana = { work_hours: [...shifts([0], "08:00", "12:00"), ...shifts([1], "14:00", "20:00"), ...shifts([6], "10:00", "14:00")] };
  assert.deepEqual(workingInterval(SALON, ana, "2026-11-16"), [540, 720]);           // cut at opening
  assert.deepEqual(workingInterval(SALON, ana, "2026-11-17"), [840, 1140]);          // cut at closing
  assert.equal(workingInterval(SALON, ana, "2026-11-22"), null);                     // salon closed: no Sunday
  assert.equal(workingInterval(SALON, ana, "2026-11-18"), null);                     // her day off
  assert.equal(workingInterval(SALON, { work_hours: shifts([0], "19:00", "21:00") }, "2026-11-16"), null);
});

test("hours outside the salon", () => {
  assert.equal(hoursOutsideSalon(SALON, null), false);
  assert.equal(hoursOutsideSalon(SALON, shifts([0, 5], "09:00", "19:00")), false);
  assert.equal(hoursOutsideSalon(SALON, shifts([6], "10:00", "12:00")), true);       // Sunday: closed
  assert.equal(hoursOutsideSalon(SALON, shifts([1], "08:45", "12:00")), true);
  assert.equal(hoursOutsideSalon(SALON, shifts([1], "12:00", "19:15")), true);
  const shortSaturday = { hours: [...shifts([0], "09:00", "19:00"), ...shifts([5], "09:00", "13:00")] };
  assert.equal(hoursOutsideSalon(shortSaturday, shifts([0], "14:00", "18:00")), false);
  assert.equal(hoursOutsideSalon(shortSaturday, shifts([5], "14:00", "18:00")), true);  // Saturday closes at 13:00
});

test("each day has its own salon hours", () => {
  const salon = { hours: [...shifts([0], "09:00", "19:00"), ...shifts([5], "08:00", "12:00")] };
  assert.deepEqual(workingInterval(salon, null, "2026-11-16"), [540, 1140]);         // Monday
  assert.deepEqual(workingInterval(salon, null, "2026-11-21"), [480, 720]);          // Saturday
  assert.equal(workingInterval(salon, null, "2026-11-17"), null);                    // Tuesday: closed
  assert.deepEqual(workingInterval(salon, { work_hours: shifts([5], "10:00", "18:00") }, "2026-11-21"), [600, 720]);
});

const ABSENCES = [
  { professional_id: "ana", first_day: "2026-11-16", last_day: "2026-11-18", start: null, end: null },
  { professional_id: "bia", first_day: "2026-11-17", last_day: "2026-11-17", start: "10:00", end: "12:00" },
  { professional_id: "bia", first_day: "2026-11-17", last_day: "2026-11-17", start: "15:00", end: "16:00" },
];

test("absences: when each one is away and what is left to book", () => {
  assert.deepEqual(awayIntervals(ABSENCES, "ana", "2026-11-17"), [[0, 1440]]);
  assert.deepEqual(awayIntervals(ABSENCES, "ana", "2026-11-19"), []);
  assert.deepEqual(awayIntervals(ABSENCES, "bia", "2026-11-17"), [[600, 720], [900, 960]]);
  assert.deepEqual(subtractIntervals([[540, 1140]], [[600, 720], [900, 960]]), [[540, 600], [720, 900], [960, 1140]]);
  assert.deepEqual(subtractIntervals([[540, 1140]], [[0, 1440]]), []);
  assert.deepEqual(subtractIntervals([[540, 600]], [[600, 700]]), [[540, 600]]);
  const ana = { id: "ana", work_hours: null }, bia = { id: "bia", work_hours: null };
  assert.deepEqual(availableIntervals(SALON, ana, "2026-11-17", ABSENCES), []);
  assert.deepEqual(availableIntervals(SALON, bia, "2026-11-17", ABSENCES), [[540, 600], [720, 900], [960, 1140]]);
  assert.deepEqual(availableIntervals(SALON, ana, "2026-11-19", ABSENCES), [[540, 1140]]);
});

test("open intervals: a time is free when at least one professional can be booked", () => {
  const bia = { id: "bia", work_hours: shifts([0, 1, 2, 3, 4], "09:00", "12:00") };
  const carla = { id: "carla", work_hours: [...shifts([0], "11:00", "15:00"), ...shifts([1, 5], "15:00", "19:00")] };
  assert.deepEqual(openIntervals(SALON, [bia, carla], "2026-11-16"), [[540, 900]]);      // overlapping: merged
  assert.deepEqual(openIntervals(SALON, [bia, carla], "2026-11-17"), [[540, 720], [900, 1140]]);   // a gap
  assert.deepEqual(openIntervals(SALON, [bia, carla], "2026-11-21"), [[900, 1140]]);     // Saturday: Carla
  assert.deepEqual(openIntervals(SALON, [bia, carla], "2026-11-22"), []);                // Sunday: salon closed
  assert.deepEqual(openIntervals(SALON, [], "2026-11-16"), [[540, 1140]]);              // no professionals yet
  assert.deepEqual(openIntervals(SALON, [bia], "2026-11-17", ABSENCES), [[540, 600]]);   // her absence 10-12
  const ana = { id: "ana", work_hours: null };
  assert.deepEqual(openIntervals(SALON, [ana], "2026-11-17", ABSENCES), []);             // away all day
});

test("closed intervals are the gaps, clipped to the grid", () => {
  assert.deepEqual(closedIntervals([[600, 840]], 540, 1140), [[540, 600], [840, 1140]]);
  assert.deepEqual(closedIntervals([[540, 720], [900, 1140]], 540, 1140), [[720, 900]]);
  assert.deepEqual(closedIntervals([], 540, 1140), [[540, 1140]]);
  assert.deepEqual(closedIntervals([[480, 1200]], 540, 1140), []);
  assert.deepEqual(closedIntervals([[540, 600], [570, 660]], 540, 700), [[660, 700]]);
});

test("hour range covers the salon and any appointment outside it", () => {
  assert.deepEqual(hourRange(SALON, []), [9, 19]);
  assert.deepEqual(hourRange({ hours: shifts([0], "08:30", "18:15") }, []), [8, 19]);
  // each day has its own hours: one grid from the earliest opening to the latest closing
  assert.deepEqual(hourRange({ hours: [...shifts([0], "10:00", "14:00"), ...shifts([5], "08:00", "12:00")] }, []), [8, 14]);
  assert.deepEqual(hourRange(SALON, [{ start: "07:45", duration_min: 30 }, { start: "19:30", duration_min: 60 }]), [7, 21]);
  assert.deepEqual(hourRange(SALON, [{ start: "23:00", duration_min: 120 }]), [9, 24]);
});

test("overlapping appointments share the width, separate groups do not", () => {
  const out = layoutColumns([
    { id: "a", start: 600, end: 660 }, { id: "b", start: 630, end: 690 }, { id: "c", start: 660, end: 720 },
    { id: "d", start: 720, end: 780 },                                                  // touches c: new group
  ]);
  const by = Object.fromEntries(out.map((e) => [e.id, [e.col, e.cols]]));
  assert.deepEqual(by, { a: [0, 2], b: [1, 2], c: [0, 2], d: [0, 1] });
});

test("layout never puts two overlapping appointments in the same column", () => {
  let seed = 7;
  const random = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  for (let round = 0; round < 200; round++) {
    const events = Array.from({ length: 1 + Math.floor(random() * 12) }, (_, i) => {
      const start = 540 + 15 * Math.floor(random() * 40);
      return { id: i, start, end: start + 15 * (1 + Math.floor(random() * 8)) };
    });
    const out = layoutColumns(events);
    assert.equal(out.length, events.length);
    for (const x of out) {
      assert.ok(x.col < x.cols);
      for (const y of out) {
        if (x !== y && x.start < y.end && y.start < x.end) {
          assert.notEqual(x.col, y.col);
          assert.equal(x.cols, y.cols);                        // same group, same width
        }
      }
    }
  }
});

test("colors follow the professionals' order and wrap around", () => {
  const list = Array.from({ length: 10 }, (_, i) => ({ id: `p${i}` }));
  assert.equal(colorClass(list, "p0"), "c0");
  assert.equal(colorClass(list, "p9"), "c1");
  assert.equal(colorClass(list, "deleted"), "c-none");
});

test("work hours summary", () => {
  assert.equal(workHoursSummary(null), "Horário do salão");
  assert.equal(workHoursSummary([]), "Não trabalha em nenhum dia");
  const week = [0, 1, 2, 3, 4].map((day) => ({ day, start: "09:00", end: "18:00" }));
  assert.equal(workHoursSummary([...week, { day: 5, start: "09:00", end: "13:00" }]), "Seg a Sex 09:00–18:00 · Sáb 09:00–13:00");
  assert.equal(workHoursSummary([{ day: 2, start: "10:00", end: "14:00" }, { day: 0, start: "10:00", end: "14:00" }]), "Seg, Qua 10:00–14:00");
  assert.equal(workHoursSummary([0, 1, 3, 4, 5].map((day) => ({ day, start: "09:00", end: "18:00" }))), "Seg, Ter, Qui a Sáb 09:00–18:00");
});

test("the salon's clock is Brasília time (UTC-3) whatever the device's time zone", () => {
  assert.deepEqual(salonNow(new Date("2026-11-18T17:59:30Z")), { date: "2026-11-18", minutes: 14 * 60 + 59 });
  assert.deepEqual(salonNow(new Date("2026-11-19T02:30:00Z")), { date: "2026-11-18", minutes: 23 * 60 + 30 });  // UTC already the 19th
  assert.deepEqual(salonNow(new Date("2026-11-19T03:00:00Z")), { date: "2026-11-19", minutes: 0 });            // midnight in Brasília
  assert.deepEqual(salonNow(new Date("2027-01-01T01:15:00Z")), { date: "2026-12-31", minutes: 22 * 60 + 15 }); // across the year
});

test("uncovered hours: the salon is open but nobody works", () => {
  const salon = { hours: [...shifts([0], "09:00", "19:00"), ...shifts([5], "08:00", "12:00")] };   // Mon, Sat
  assert.deepEqual(uncoveredHours(salon, [{ work_hours: null }]), []);                 // follows the salon: all covered
  const ana = { work_hours: shifts([0], "09:00", "13:00") };
  const bia = { work_hours: [...shifts([0], "15:00", "19:00"), ...shifts([5], "08:00", "10:00")] };
  assert.deepEqual(uncoveredHours(salon, [ana, bia]), [
    { day: 0, start: "13:00", end: "15:00" },                                         // Monday lunch: nobody
    { day: 5, start: "10:00", end: "12:00" },                                         // Saturday after Bia leaves
  ]);
  assert.deepEqual(uncoveredHours(salon, [{ work_hours: [] }]), [                      // works no day at all
    { day: 0, start: "09:00", end: "19:00" }, { day: 5, start: "08:00", end: "12:00" }]);
  assert.deepEqual(uncoveredHours(salon, [ana, bia, { work_hours: null }]), []);
});

test("uncovered intervals: the salon is open that day, but nobody can be booked", () => {
  const ana = { id: "a", work_hours: shifts([0], "09:00", "13:00") };
  const bia = { id: "b", work_hours: shifts([0], "15:00", "19:00") };
  assert.deepEqual(uncoveredIntervals(SALON, [ana, bia], "2026-11-16"), [[780, 900]]);             // Monday 13-15
  assert.deepEqual(uncoveredIntervals(SALON, [ana, bia], "2026-11-17"), [[540, 1140]]);            // Tuesday: nobody
  assert.deepEqual(uncoveredIntervals(SALON, [ana, bia], "2026-11-22"), []);                       // Sunday: closed
  assert.deepEqual(uncoveredIntervals(SALON, [], "2026-11-16"), []);                               // no professionals yet
  const away = [{ professional_id: "b", first_day: "2026-11-16", last_day: "2026-11-16", start: null, end: null }];
  assert.deepEqual(uncoveredIntervals(SALON, [ana, bia], "2026-11-16", away), [[780, 1140]]);       // Bia away all day
});
