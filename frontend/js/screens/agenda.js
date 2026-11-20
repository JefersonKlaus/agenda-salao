// The agenda, Google Calendar style: day, week and month views, one color per professional.
// The day view has one column per professional who works that day (each her own schedule); the
// filter shows one, some or all of them. Hatched gray = the salon is closed (or that professional does not work then);
// hatched yellow, with a note = the salon is open but no professional at all can be booked. What
// already passed is shaded. Hatched areas never open the booking; past ones only for the manager, who
// records what happened (employees cannot book, change or cancel what already passed).
// Absences (sick, travelling...) show as "Ausente" blocks, or in the all-day strip when they take the
// whole day; appointments that fall inside one get a ⚠. Click an empty spot to book there; click an
// appointment to see it, cancel it or give it to another professional.
import { api } from "../api.js";
import { isManager, myProfessionalId } from "../auth.js";
import { isOnline, missingDays, onConnectionChange } from "../offline.js";
import {
  availableIntervals, awayIntervals, closedIntervals, colorClass, hourRange, layoutColumns, openIntervals,
  parseIso, shiftDate, subtractIntervals, toMinutes, toTime, uncoveredIntervals, viewTitle, VIEWS, visibleDays, weekday,
  workingInterval,
} from "../calendar.js";
import { h, prettyDate, render, salonNow, today } from "../util.js";
import { absenceLabel, openAppointmentDialog, openBookingDialog, openTimeOffDetails, openTimeOffDialog } from "./agenda-dialogs.js";

const HOUR_PX = 48;                            // keep in sync with --hour in style.css
const MONTH_CHIPS = 3;                         // items listed per day in the month view
const VIEW_LABELS = { day: "Dia", week: "Semana", month: "Mês" };
const NAV_LABELS = {
  day: ["Dia anterior", "Próximo dia"], week: ["Semana anterior", "Próxima semana"], month: ["Mês anterior", "Próximo mês"],
};
const WEEKDAY_NAMES = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"];
const NOW_TICK_MS = 30_000;                    // the "now" marker moves every 30 s: never more than a minute behind
const FOLD_AFTER = 6;                          // more professionals than this: the filter can be folded
const FOLDED_KEY = "agenda.filterFolded";      // remembered on this device (a convenience: may be missing)

function rememberedFolded() {
  try { return localStorage.getItem(FOLDED_KEY) === "1"; } catch { return false; }
}
function rememberFolded(folded) {
  try { localStorage.setItem(FOLDED_KEY, folded ? "1" : "0"); } catch { /* no storage: just not remembered */ }
}

// Kept while the app is open, so coming back to the agenda shows the same view and period.
const view = {
  mode: window.matchMedia("(max-width: 640px)").matches ? "day" : "week",
  date: today(),
  chosen: [],                                  // the professionals shown; [] = all of them
  folded: rememberedFolded(),                  // the filter shows only "Todas" and the chosen ones
};

export async function mount(container) {
  container.classList.add("calendar");
  render(container, h("p", { className: "notice" }, "Carregando…"));
  let services, professionals, settings, appointments = [], timeOffs = [], request = 0;
  try {
    [services, professionals, settings] = await Promise.all([
      api("GET", "/services"), api("GET", "/professionals"), api("GET", "/settings")]);
  } catch (error) { return render(container, h("p", { className: "notice" }, error.message)); }
  view.chosen = view.chosen.filter((id) => professionals.some((p) => p.id === id));   // deleted since

  // The "now" marker (a red line with the time, in today's column) keeps moving while the screen is open;
  // after midnight everything is redrawn so "today" moves to the new day. Stops when the screen is left.
  let placeNow = () => {}, drawnOn = today();
  const ticker = setInterval(() => {
    if (!container.isConnected) return clearInterval(ticker);
    if (today() !== drawnOn) { drawToolbar(); drawBody(); } else placeNow();
  }, NOW_TICK_MS);

  const toolbar = h("div", { className: "cal-toolbar" });
  const filterBar = h("div", { className: "cal-filter", role: "group", "aria-label": "Profissionais" });
  const body = h("div", { className: "cal-body" });
  const offlineNote = h("p", { className: "offline-note", hidden: true });   // offline: days never downloaded
  const legend = h("p", { className: "pay-legend muted" }, "Pagamento:",
    h("span", {}, h("span", { className: "pay paid" }, "✓"), " pago"),
    h("span", {}, h("span", { className: "pay late" }, "R$"), " já aconteceu e não foi pago"),
    h("span", {}, h("span", { className: "pay due" }, "R$"), " a receber"));
  render(container, toolbar, filterBar, legend, offlineNote, body);

  const filtered = () => view.chosen.length > 0;
  /** Just one professional chosen: her own agenda (week and day show her days, not split by person). */
  const single = () => (view.chosen.length === 1 ? professionals.find((p) => p.id === view.chosen[0]) : null);
  /** Who the hatching and the items are about: the chosen professionals, or everybody. */
  const team = () => (filtered() ? professionals.filter((p) => view.chosen.includes(p.id)) : professionals);
  const mine = (item) => !filtered() || view.chosen.includes(item.professional_id);
  const nameOf = (id) => professionals.find((p) => p.id === id)?.name || "Profissional";
  const color = (professionalId) => colorClass(professionals, professionalId);
  const showDay = (date) => { view.mode = "day"; view.date = date; load(); };
  const filterBy = (ids) => {
    view.chosen = ids.length === professionals.length ? [] : ids;    // all of them chosen: the same as "Todas"
    drawFilter();
    drawBody();
  };
  const toggle = (id) => filterBy(view.chosen.includes(id) ? view.chosen.filter((x) => x !== id) : [...view.chosen, id]);
  /** The appointment was made before an absence that now covers it: it needs another professional. */
  const isAway = (a) => awayIntervals(timeOffs, a.professional_id, a.date)
    .some(([s, e]) => toMinutes(a.start) < e && s < toMinutes(a.start) + a.duration_min);

  async function load() {
    const days = visibleDays(view.mode, view.date);
    const current = ++request;
    drawToolbar();
    drawFilter();
    body.classList.add("loading");
    try {
      const period = { from: days[0], to: days.at(-1) };
      const [found, away] = await Promise.all([api("GET", "/appointments", null, period), api("GET", "/time-off", null, period)]);
      if (current !== request) return;         // the user has already moved to another period
      appointments = found;
      timeOffs = away;
      // Offline, what is shown came from earlier downloads: say which days of it never were.
      const missing = isOnline() ? [] : missingDays(period);
      offlineNote.hidden = missing.length === 0;
      offlineNote.textContent = missing.length === days.length
        ? "Este período ainda não foi baixado: sem conexão, ele aparece vazio."
        : `Sem conexão: ${missing.length} dia(s) deste período ainda não foram baixados e aparecem vazios.`;
      drawBody();
    } catch (error) {
      if (current === request) { offlineNote.hidden = true; render(body, h("p", { className: "notice" }, error.message)); }
    } finally {
      if (current === request) body.classList.remove("loading");
    }
  }

  function book(date, time = null, professionalId = single()?.id || "") {
    openBookingDialog({ date, time, professionalId,                // only the manager books, also in the past
      services, professionals, onBooked: load });
  }

  // Offline: the agenda shows what was downloaded and blocks every change (back online, app.js opens
  // the page again, with fresh data).
  const stopListening = onConnectionChange((online) => {
    if (!container.isConnected) return stopListening();
    if (!online) { drawToolbar(); drawBody(); }
  });

  const openAppointment = (a) => openAppointmentDialog(a, { professionals, away: isAway(a), onChanged: load,
    manager: isManager() });
  // The manager handles anyone's absences; an employee, only her own (the API checks the same).
  const mayHandleAbsence = (professionalId) => isManager() || (professionalId && professionalId === myProfessionalId());
  const openAbsence = (t) => openTimeOffDetails(t, nameOf(t.professional_id), load, mayHandleAbsence(t.professional_id));
  const absenceButton = () => {
    const mine = professionals.filter((p) => mayHandleAbsence(p.id));      // all of them, or just her
    return mine.length > 0 && h("button", { className: "secondary", disabled: !isOnline(), onclick: () => openTimeOffDialog({
      date: view.date < today() ? today() : view.date, professionals: mine, onSaved: load,
      professionalId: isManager() ? single()?.id || "" : mine[0].id }) }, "Ausência");
  };

  function drawToolbar() {
    const [previous, next] = NAV_LABELS[view.mode];
    const go = (step) => () => { view.date = shiftDate(view.mode, view.date, step); load(); };
    render(toolbar,
      h("div", { className: "cal-nav" },
        h("button", { className: "secondary", onclick: () => { view.date = today(); load(); } }, "Hoje"),
        h("button", { className: "icon", onclick: go(-1), "aria-label": previous, title: previous }, "‹"),
        h("button", { className: "icon", onclick: go(1), "aria-label": next, title: next }, "›"),
        h("h1", { className: "cal-title" }, viewTitle(view.mode, view.date))),
      h("div", { className: "cal-controls" },
        h("div", { className: "segmented", role: "group", "aria-label": "Visualização" },
          VIEWS.map((mode) => h("button", { "aria-pressed": String(mode === view.mode),
            onclick: () => { view.mode = mode; load(); } }, VIEW_LABELS[mode]))),
        absenceButton(),
        isManager() && h("button", { className: "primary", disabled: !isOnline(), onclick: () => book(view.date) },
          "Novo agendamento")));
  }

  /** Paid, or not yet: "late" when it already happened (someone should charge it), "due" when ahead. */
  function payment(a) {
    if (a.paid) return { kind: "paid", label: "Pago" };
    const now = salonNow();
    const happened = a.date < now.date || (a.date === now.date && toMinutes(a.start) <= now.minutes);
    return happened ? { kind: "late", label: "Já aconteceu e não foi pago" } : { kind: "due", label: "A receber" };
  }
  const payMark = (a) => {
    const { kind, label } = payment(a);
    return h("span", { className: `pay ${kind}`, title: label, "aria-label": label }, kind === "paid" ? "✓" : "R$");
  };

  /** "Todas" + one button per professional, in her color: the filter and the color legend at once.
   *  Each name turns on and off, so the agenda shows one, some or all of them. With more than
   *  FOLD_AFTER professionals the names can be folded away: then only the chosen ones stay. */
  function drawFilter() {
    const all = h("button", { className: "pill", "aria-pressed": String(!filtered()), onclick: () => filterBy([]),
      title: "Ver a agenda de todas" }, "Todas");
    const pill = (p) => {
      const on = view.chosen.includes(p.id);
      return h("button", { className: "pill", "aria-pressed": String(on), onclick: () => toggle(p.id),
        title: on ? `Tirar ${p.name} da agenda` : `Mostrar ${p.name}` },
      h("span", { className: `dot ${color(p.id)}`, "aria-hidden": "true" }), p.name);
    };
    const many = professionals.length > FOLD_AFTER;
    const folded = many && view.folded;
    const pills = folded ? professionals.filter((p) => view.chosen.includes(p.id)) : professionals;
    const fold = many && h("button", { className: "link fold", "aria-expanded": String(!folded),
      onclick: () => { view.folded = !folded; rememberFolded(view.folded); drawFilter(); } },
    folded ? `Mostrar profissionais (${professionals.length}) ▾` : "Recolher ▴");
    render(filterBar, professionals.length > 0 && [all, pills.map(pill),
      filtered() && h("span", { className: "muted filter-count" },
        `${view.chosen.length} de ${professionals.length}`), fold]);
  }

  function drawBody() {
    const days = visibleDays(view.mode, view.date);
    drawnOn = today();
    placeNow = () => {};                       // set again by the time grid when today is on screen
    if (view.mode === "month") return render(body, monthGrid(days));
    const columns = columnsFor(days);
    if (columns.length === 0) {                // day view: nobody works that day (closed, or nobody to attend)
      const absences = timeOffs.filter((t) => t.first_day <= days[0] && days[0] <= t.last_day && mine(t));
      const salonOpens = workingInterval(settings, null, days[0]) !== null;
      const nobody = openIntervals(settings, professionals, days[0], timeOffs).length === 0;
      return render(body, h("div", { className: "card empty-day" + (salonOpens && nobody ? " gap-day" : "") },
        h("p", {}, !salonOpens ? "O salão não abre neste dia."
          : nobody ? "O salão abre neste dia, mas nenhuma profissional atende: não dá para agendar."
            : "Nenhuma das profissionais escolhidas atende neste dia."),
        absences.map((t) => absenceChip(t, `${nameOf(t.professional_id)} ausente`))));
    }
    // Day view: who is away all day (and has nothing booked) has no column; say so above the grid.
    const shown = new Set(columns.map((c) => c.professionalId));
    const hidden = view.mode === "day" && !single()
      && timeOffs.filter((t) => t.first_day <= days[0] && days[0] <= t.last_day && mine(t) && !shown.has(t.professional_id));
    render(body, hidden && hidden.length > 0 && h("div", { className: "away-line" },
      h("span", { className: "muted" }, "Ausentes:"), hidden.map((t) => absenceChip(t, nameOf(t.professional_id)))),
    timeGrid(columns));
  }

  // ------------------------------------------------------------------ day and week
  /** What each column of the time grid shows. Week: one column per day. Day: one per professional who
   *  can be booked that day or has appointments in it, among the chosen ones; a single one when just one
   *  professional is chosen. */
  function columnsFor(days) {
    const dayColumn = (date) => ({ date, professionalId: single()?.id || "", header: dayHeader(date),
      appts: appointments.filter((a) => a.date === date && mine(a)),
      absences: timeOffs.filter((t) => t.first_day <= date && date <= t.last_day && mine(t)),
      open: openIntervals(settings, team(), date, timeOffs) });
    if (view.mode === "week" || single() || professionals.length === 0) return days.map(dayColumn);

    const date = days[0];
    const ofDay = appointments.filter((a) => a.date === date && mine(a));
    const columns = team().map((p) => ({ date, professionalId: p.id, header: personHeader(p.id, p.name),
      appts: ofDay.filter((a) => a.professional_id === p.id),
      absences: timeOffs.filter((t) => t.professional_id === p.id && t.first_day <= date && date <= t.last_day),
      open: availableIntervals(settings, p, date, timeOffs) }))
      .filter((c) => c.open.length > 0 || c.appts.length > 0);
    // Appointments of professionals deleted since then stay on the agenda, in a column of their own.
    for (const a of ofDay) {
      if (columns.some((c) => c.professionalId === a.professional_id)) continue;
      columns.push({ date, professionalId: a.professional_id, header: personHeader(a.professional_id, a.professional_name),
        appts: ofDay.filter((x) => x.professional_id === a.professional_id), absences: [], open: [] });
    }
    return columns;
  }

  function dayHeader(date) {
    return h("button", { className: "tg-day-head" + (date === today() ? " today" : ""),
      onclick: () => showDay(date), "aria-label": prettyDate(date) },
    h("span", { className: "tg-weekday" }, WEEKDAY_NAMES[weekday(date)]),
    h("span", { className: "tg-date" }, String(parseIso(date).getDate())));
  }

  function personHeader(professionalId, name) {
    const known = professionals.some((p) => p.id === professionalId);
    return h("button", { className: "tg-person", title: known ? `Ver só a agenda de ${name}` : name,
      onclick: () => known && filterBy([professionalId]) },
    h("span", { className: `dot ${color(professionalId)}`, "aria-hidden": "true" }), h("span", {}, name));
  }

  function absenceChip(t, label) {
    return h("button", { className: "away-chip", title: absenceLabel(t) || "Ausente", onclick: () => openAbsence(t) },
      label, absenceLabel(t) && ` · ${absenceLabel(t)}`);
  }

  function timeGrid(columns) {
    const [firstHour, lastHour] = hourRange(settings, columns.flatMap((c) => c.appts));
    const gridStart = firstHour * 60, gridEnd = lastHour * 60;
    const px = (minutes) => `${(minutes * HOUR_PX) / 60}px`;          // a duration on screen
    const y = (time) => px(time - gridStart);                            // a time of day on screen
    const height = px(gridEnd - gridStart);
    const perPerson = view.mode === "day" && !single() && professionals.length > 0;

    const gutter = h("div", { className: "tg-gutter" });
    gutter.style.height = height;
    for (let hour = firstHour; hour < lastHour; hour++) {
      const label = h("span", { className: "tg-hour" }, toTime(hour * 60));
      label.style.top = y(hour * 60);
      gutter.append(label);
    }

    const nowLines = [];                       // one per column of today (the day view has one per professional)
    const pastBlocks = [];                     // today's "already passed" shade, one per column of today
    const column = ({ date, professionalId, appts, absences, open }) => {
      const col = h("div", { className: "tg-col", "data-date": date, "data-professional": professionalId || "" });
      col.style.height = height;
      // Hatched: yellow where the salon is open but nobody at all can be booked (with a note, when there
      // is room for it); gray for the rest of what this column cannot book (salon closed, her day off).
      const uncovered = uncoveredIntervals(settings, professionals, date, timeOffs)
        .map(([from, to]) => [Math.max(from, gridStart), Math.min(to, gridEnd)]).filter(([from, to]) => to > from);
      const hatch = (className, from, to, title, note) => {
        const block = h("div", { className, title }, note && to - from >= 30 && h("span", { className: "tg-gap-note" }, note));
        block.style.top = y(from);
        block.style.height = px(to - from);
        col.append(block);
      };
      for (const [from, to] of subtractIntervals(closedIntervals(open, gridStart, gridEnd), uncovered)) {
        hatch("tg-off", from, to, "Fora do horário de atendimento");
      }
      for (const [from, to] of uncovered) hatch("tg-off tg-gap", from, to, "Sem profissional atendendo", "Sem profissional atendendo");
      // What already passed is dimmed and cannot be clicked: whole days before today, and today up to now
      // (its height follows the clock, in placeNow).
      if (date <= drawnOn) {
        const past = h("div", { className: "tg-past" + (isManager() ? " manager" : ""), title: "Horário que já passou" });
        past.style.height = date < drawnOn ? height : "0px";
        if (date === drawnOn) pastBlocks.push(past);
        col.append(past);
      }
      // Click on an empty spot: book at that time (rounded down to 15 minutes), with her if it is her column.
      // Only where someone can be booked and the time has not passed; hatched and past areas take the
      // click themselves, so they never get here, and this check covers their edges.
      col.addEventListener("click", (event) => {
        if (event.target !== col) return;
        const clicked = gridStart + Math.floor(((event.clientY - col.getBoundingClientRect().top) * 60) / HOUR_PX / 15) * 15;
        const start = Math.min(clicked, gridEnd - 15);
        const bookable = open.some(([from, to]) => from <= start && start < to);
        if (bookable && isOnline() && isManager()) book(date, toTime(start), professionalId);
      });
      // Appointments and partial absences share the width when they overlap.
      const items = [
        ...appts.map((a) => ({ appt: a, start: toMinutes(a.start), end: toMinutes(a.start) + a.duration_min })),
        ...absences.filter((t) => t.start).map((t) => ({ absence: t, start: toMinutes(t.start), end: toMinutes(t.end) })),
      ];
      for (const e of layoutColumns(items)) {
        const node = e.appt ? appointmentBlock(e.appt) : absenceBlock(e.absence, perPerson);
        node.style.top = y(Math.max(e.start, gridStart));
        node.style.height = `calc(${px(Math.min(e.end, gridEnd) - Math.max(e.start, gridStart))} - 2px)`;
        node.style.left = `calc(${(100 * e.col) / e.cols}% + 2px)`;
        node.style.width = `calc(${100 / e.cols}% - 4px)`;
        col.append(node);
      }
      if (date === drawnOn) {                  // the red "now" line; its dot only on the first one
        const line = h("div", { className: "tg-now" + (nowLines.length ? "" : " with-dot"), "aria-hidden": "true" });
        nowLines.push(line);
        col.append(line);
      }
      return col;
    };

    const appointmentBlock = (a) => {
      const away = isAway(a);
      return h("button", { className: `tg-event ${color(a.professional_id)}${a.duration_min <= 30 ? " short" : ""}${away ? " conflict" : ""}`,
        title: `${away ? "⚠ Profissional ausente · " : ""}${a.start} ${a.client_name} · ${a.service_name} · ${a.professional_name}`
          + ` · ${payment(a).label}`,
        onclick: () => openAppointment(a) },
      payMark(a),
      h("strong", {}, `${away ? "⚠ " : ""}${a.start} ${a.client_name}`), h("span", {}, `${a.service_name} · ${a.professional_name}`));
    };
    const absenceBlock = (t, inHerColumn) => h("button", { className: "tg-away", title: absenceLabel(t) || "Ausente",
      onclick: () => openAbsence(t) },
    h("strong", {}, inHerColumn ? "Ausente" : `${nameOf(t.professional_id)} ausente`),
    h("span", {}, `${t.start}–${t.end}${absenceLabel(t) ? ` · ${absenceLabel(t)}` : ""}`));

    // Whole-day absences go in a strip under the headers (like Google's all-day events).
    const wholeDay = columns.map((c) => c.absences.filter((t) => !t.start));
    const allDay = wholeDay.some((list) => list.length) && h("div", { className: "tg-allday" },
      h("div", { className: "tg-allday-label" }, "Dia todo"),
      wholeDay.map((list) => h("div", {}, list.map((t) => absenceChip(t, perPerson ? "Ausente" : `${nameOf(t.professional_id)} ausente`)))));

    // Week: 7 days; day split by professional: as many as work that day (scrolls sideways on small screens).
    const minWidth = view.mode === "week" ? 92 : columns.length > 1 ? 120 : 0;
    const template = `56px repeat(${columns.length}, minmax(${minWidth}px, 1fr))`;
    const head = h("div", { className: "tg-head" }, h("div"), columns.map((c) => c.header));
    const grid = h("div", { className: "tg-grid" }, gutter, columns.map(column));
    for (const row of [head, grid, allDay].filter(Boolean)) row.style.gridTemplateColumns = template;
    if (nowLines.length) {                     // the current time, in the hours column, on the line's height
      const label = h("span", { className: "tg-now-label", title: "Agora (horário de Brasília)" });
      gutter.append(label);
      placeNow = () => {
        const { minutes } = salonNow();
        const visible = minutes >= gridStart && minutes <= gridEnd;
        for (const node of [...nowLines, label]) {
          node.hidden = !visible;
          node.style.top = y(minutes);
        }
        label.textContent = toTime(minutes);
        for (const past of pastBlocks) past.style.height = px(Math.min(Math.max(minutes, gridStart), gridEnd) - gridStart);
      };
      placeNow();
    }
    return h("div", { className: "tg" }, head, allDay, grid);
  }

  // ------------------------------------------------------------------ month
  function monthGrid(days) {
    const month = view.date.slice(0, 7);
    const cell = (date) => {
      const absences = timeOffs.filter((t) => t.first_day <= date && date <= t.last_day && mine(t));
      const appts = appointments.filter((a) => a.date === date && mine(a));
      const chips = [
        ...absences.map((t) => h("button", { className: "mv-chip mv-away", title: absenceLabel(t) || "Ausente", onclick: () => openAbsence(t) },
          h("span", { className: "wide-only" }, `${nameOf(t.professional_id)} `), "ausente")),
        ...appts.map((a) => h("button", { className: `mv-chip ${color(a.professional_id)}${isAway(a) ? " conflict" : ""}`,
          title: `${a.start} ${a.client_name} · ${a.service_name} · ${a.professional_name} · ${payment(a).label}`,
          onclick: () => openAppointment(a) }, payMark(a), isAway(a) && "⚠ ", a.start, h("span", { className: "wide-only" }, ` ${a.client_name}`))),
      ];
      // a whole day the salon opens with nobody to attend is yellow, not gray like a closed day
      const salonOpens = workingInterval(settings, null, date) !== null;
      const nobody = salonOpens && openIntervals(settings, professionals, date, timeOffs).length === 0
        && professionals.length > 0;
      const closed = !nobody && openIntervals(settings, team(), date, timeOffs).length === 0;
      const classes = ["mv-cell", date.slice(0, 7) !== month && "other", date === today() && "today",
        nobody && "uncovered", closed && "closed"].filter(Boolean).join(" ");
      const node = h("div", { className: classes, "data-date": date },
        h("button", { className: "mv-date", onclick: () => showDay(date), "aria-label": prettyDate(date) },
          String(parseIso(date).getDate())),
        nobody && h("span", { className: "mv-gap-note", title: "O salão abre, mas nenhuma profissional atende neste dia" },
          "Sem profissional"),
        chips.slice(0, MONTH_CHIPS),
        chips.length > MONTH_CHIPS && h("button", { className: "mv-more", onclick: () => showDay(date) },
          `+${chips.length - MONTH_CHIPS}`, h("span", { className: "wide-only" }, " mais")));
      // A click on the day books on it, unless it is over, closed, or has nobody to attend.
      const bookable = isManager() && !nobody && !closed;
      if (!bookable) node.classList.add("not-bookable");
      node.addEventListener("click", (e) => { if (e.target === node && bookable && isOnline()) book(date); });
      return node;
    };
    return h("div", { className: "mv" },
      h("div", { className: "mv-head" }, WEEKDAY_NAMES.map((name) => h("div", {}, name))),
      h("div", { className: "mv-grid" }, days.map(cell)));
  }

  load();
}
