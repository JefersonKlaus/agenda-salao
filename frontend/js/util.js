// Small helpers. Text coming from the user ALWAYS goes in as text (never as HTML).

export function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === false || value == null) continue;
    if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else if (key in el && key !== "list") el[key] = value;
    else el.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat(Infinity)) {
    if (child == null || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

export function render(container, ...children) {
  container.replaceChildren(...children.flat(Infinity).filter(Boolean));
}

export function notify(text, isError = false) {
  const el = h("div", { className: "toast" + (isError ? " error" : "") }, text);
  document.getElementById("toasts").append(el);
  setTimeout(() => el.remove(), isError ? 6000 : 3000);
}

export const formatMoney = (cents) =>
  (cents / 100).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });

/** "80,50" or "1.200" (Brazilian format) -> integer cents. Returns null if it is not an amount. */
export function toCents(text) {
  const cleaned = String(text).trim().replace(/\s/g, "").replace("R$", "");
  if (!/^\d{1,3}(\.\d{3})*(,\d{1,2})?$|^\d+(,\d{1,2})?$/.test(cleaned)) return null;
  const [whole, cents = ""] = cleaned.replace(/\./g, "").split(",");
  return Number(whole) * 100 + Number(cents.padEnd(2, "0"));
}

// The salon's clock: Brasília, UTC-3 all year (no daylight saving time since 2019), exactly like the
// backend's (backend/src/agenda/clock.py). The device's own time zone does not matter.
const SALON_UTC_OFFSET_MIN = -3 * 60;

/** The salon's current date ("YYYY-MM-DD") and time in minutes since midnight. */
export function salonNow(at = new Date()) {
  const shifted = new Date(at.getTime() + SALON_UTC_OFFSET_MIN * 60_000);
  return { date: shifted.toISOString().slice(0, 10), minutes: shifted.getUTCHours() * 60 + shifted.getUTCMinutes() };
}

export const today = () => salonNow().date;

export function addDays(iso, days) {
  const [y, m, d] = iso.split("-").map(Number);
  const result = new Date(y, m - 1, d + days);
  return [result.getFullYear(), String(result.getMonth() + 1).padStart(2, "0"), String(result.getDate()).padStart(2, "0")].join("-");
}

export function prettyDate(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  const text = new Date(y, m - 1, d).toLocaleDateString("pt-BR", { weekday: "long", day: "2-digit", month: "long" });
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function addMinutes(time, minutes) {
  const [hh, mm] = time.split(":").map(Number);
  const total = hh * 60 + mm + minutes;
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

export const durationText = (min) => (min >= 60 ? `${Math.floor(min / 60)} h` : "") + (min % 60 ? ` ${min % 60} min` : "");

/** Runs an action with the button disabled, so repeated clicks don't send it twice. */
export async function whileDisabled(button, action) {
  button.disabled = true;
  try { return await action(); } finally { button.disabled = false; }
}

/** Opens a modal <dialog> (like Google Calendar's pop-ups). It is removed from the page when closed;
 *  clicking outside it closes it too. */
export function openDialog(title, ...children) {
  const dialog = h("dialog", { className: "dialog" }, h("h2", {}, title), ...children);
  dialog.addEventListener("click", (e) => {          // the backdrop counts as the <dialog> itself
    const r = dialog.getBoundingClientRect();
    const outside = e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom;
    if (e.target === dialog && outside) dialog.close();
  });
  dialog.addEventListener("close", () => dialog.remove());
  document.body.append(dialog);
  dialog.showModal();
  return dialog;
}
