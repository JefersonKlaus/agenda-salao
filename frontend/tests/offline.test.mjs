// Unit tests for what the agenda keeps to show offline. Run:  node --test frontend/tests/*.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";

import { isOnline, missingDays, onConnectionChange, recall, remember, setOnline } from "../js/offline.js";

const appt = (date, start, id = `${date}_${start.replace(":", "")}_aaaaaaaa`) => ({ id, date, start });

test("appointments are kept per day: a week downloaded is there for a day or a month too", () => {
  const week = { from: "2026-11-16", to: "2026-11-22" };
  remember("/appointments", week, [appt("2026-11-17", "10:00"), appt("2026-11-19", "15:00")]);
  assert.deepEqual(recall("/appointments", { date: "2026-11-17" }).map((a) => a.start), ["10:00"]);
  assert.deepEqual(recall("/appointments", { date: "2026-11-18" }), []);            // known: nothing booked
  assert.equal(recall("/appointments", { date: "2026-12-01" }), undefined);          // never downloaded
  const month = { from: "2026-10-26", to: "2026-12-06" };
  assert.equal(recall("/appointments", month).length, 2);                           // what is known of it
  assert.equal(missingDays(month).length, 42 - 7);
  assert.deepEqual(missingDays(week), []);
  // downloaded again: the newer answer wins (one was cancelled meanwhile)
  remember("/appointments", { date: "2026-11-17" }, []);
  assert.deepEqual(recall("/appointments", week).map((a) => a.start), ["15:00"]);
});

test("absences: any that touch the period, and the removed ones go away", () => {
  const off = (id, first, last) => ({ id, professional_id: "p", first_day: first, last_day: last });
  const week = { from: "2026-11-16", to: "2026-11-22" };
  remember("/time-off", week, [off("a", "2026-11-10", "2026-11-17"), off("b", "2026-11-20", "2026-11-20")]);
  assert.deepEqual(recall("/time-off", { from: "2026-11-18", to: "2026-11-19" }), []);
  assert.deepEqual(recall("/time-off", { from: "2026-11-20", to: "2026-11-21" }).map((t) => t.id), ["b"]);
  assert.equal(recall("/time-off", { from: "2027-01-01", to: "2027-01-07" }), undefined);
  remember("/time-off", week, [off("a", "2026-11-10", "2026-11-17")]);               // "b" was removed
  assert.deepEqual(recall("/time-off", week).map((t) => t.id), ["a"]);
});

test("other answers are kept as they came", () => {
  remember("/services", undefined, [{ id: "s", name: "Corte" }]);
  assert.deepEqual(recall("/services", undefined), [{ id: "s", name: "Corte" }]);
  assert.equal(recall("/finance", { month: "2026-11" }), undefined);
});

test("connection changes are announced once each", () => {
  const seen = [];
  const stop = onConnectionChange((online) => seen.push(online));
  setOnline(false); setOnline(false); setOnline(true);
  stop();
  setOnline(false);
  assert.deepEqual(seen, [false, true]);
  assert.equal(isOnline(), false);
  setOnline(true);
});
