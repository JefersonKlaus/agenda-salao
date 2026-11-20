// Offline mode. Every answer the API gives to a GET is kept here, and saved on the device
// (localStorage), so that it is still there after reloading or reopening the page with no connection:
// the agenda keeps showing what was already downloaded, and nothing can be changed until the connection
// comes back (app.js and the agenda listen to `onConnectionChange`). Logging out erases it.
//
// Appointments and absences are kept per day, not per request: a week downloaded in the week view can
// be seen offline in the day or month view too. A day never downloaded is reported by `missingDays`.
import { addDays } from "./util.js";

let online = true;
const listeners = new Set();

export const isOnline = () => online;

/** fn(online) on every change. Returns a function that stops listening. */
export function onConnectionChange(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function setOnline(value) {
  if (value === online) return;
  online = value;
  for (const fn of [...listeners]) fn(online);
}

// ------------------------------------------------------------------ what was downloaded
const exact = new Map();            // "/services?" -> answer (services, professionals, settings...)
const appointmentsByDay = new Map(); // "2026-11-18" -> that day's appointments
const timeOffs = new Map();         // id -> absence
const timeOffDays = new Set();      // days whose absences are known

const keyOf = (path, params = {}) => `${path}?${new URLSearchParams(params)}`;

// ------------------------------------------------------------------ saved on the device
const STORAGE_KEY = "agenda.downloaded";

function save() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ exact: [...exact], appointmentsByDay: [...appointmentsByDay],
      timeOffs: [...timeOffs], timeOffDays: [...timeOffDays] }));
  } catch { /* no storage (private mode, full, tests): kept in memory only */ }
}

function restore() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY));
    if (!saved) return;
    saved.exact.forEach(([k, v]) => exact.set(k, v));
    saved.appointmentsByDay.forEach(([k, v]) => appointmentsByDay.set(k, v));
    saved.timeOffs.forEach(([k, v]) => timeOffs.set(k, v));
    saved.timeOffDays.forEach((day) => timeOffDays.add(day));
  } catch { /* nothing saved, or saved by an older version: start empty */ }
}
restore();

/** Erases everything downloaded, here and on the device (on logout: the data is the salon's). */
export function forgetDownloads() {
  exact.clear(); appointmentsByDay.clear(); timeOffs.clear(); timeOffDays.clear();
  try { localStorage.removeItem(STORAGE_KEY); } catch { /* no storage */ }
}

/** Every day from `first` to `last`, both included (the API never answers for more than a year). */
function daysBetween(first, last) {
  const days = [];
  for (let day = first; day && day <= last && days.length < 400; day = addDays(day, 1)) days.push(day);
  return days;
}

/** The days a request for appointments/absences covers: ?date= or ?from=&to=. */
function daysOf(params = {}) {
  return params.date ? [params.date] : daysBetween(params.from, params.to);
}

/** Keeps the answer to a GET. */
export function remember(path, params, data) {
  if (path === "/appointments") {
    for (const day of daysOf(params)) appointmentsByDay.set(day, data.filter((a) => a.date === day));
  } else if (path === "/time-off") {
    const days = daysOf(params);
    const first = days[0], last = days.at(-1);
    for (const [id, t] of timeOffs) {          // removed since: drop the ones in this period not answered
      if (t.first_day <= last && t.last_day >= first && !data.some((x) => x.id === id)) timeOffs.delete(id);
    }
    for (const t of data) timeOffs.set(t.id, t);
    days.forEach((day) => timeOffDays.add(day));
  } else {
    exact.set(keyOf(path, params), data);
  }
  save();
}

/** What was downloaded for this GET, or undefined if nothing was. Appointments and absences come
 *  from the days already known (the others are simply empty: see missingDays). */
export function recall(path, params) {
  if (path === "/appointments") {
    const days = daysOf(params).filter((day) => appointmentsByDay.has(day));
    return days.length ? days.flatMap((day) => appointmentsByDay.get(day)) : undefined;
  }
  if (path === "/time-off") {
    const days = daysOf(params);
    if (!days.some((day) => timeOffDays.has(day))) return undefined;
    return [...timeOffs.values()].filter((t) => t.first_day <= days.at(-1) && t.last_day >= days[0]);
  }
  return exact.get(keyOf(path, params));
}

/** Days of this period whose appointments were never downloaded (offline they look empty). */
export function missingDays(params) {
  return daysOf(params).filter((day) => !appointmentsByDay.has(day));
}
