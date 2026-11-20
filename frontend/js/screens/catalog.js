// Services and professionals: the same list-with-form screen, only the fields change.
import { api } from "../api.js";
import { isManager } from "../auth.js";
import { colorClass, DAY_NAMES, hoursOutsideSalon, salonShift, workHoursSummary } from "../calendar.js";
import { actionsMenu, addDays, durationText, formatMoney, h, notify, render, toCents, today, whileDisabled } from "../util.js";
import { absenceSummary, openTimeOffDetails, openTimeOffDialog } from "./agenda-dialogs.js";
import { openAccessDialog } from "./access-dialog.js";
import { coverageWarning } from "./coverage.js";
import { pagedList } from "./paged-list.js";

const DURATIONS = Array.from({ length: 32 }, (_, i) => (i + 1) * 15);

function serviceFields(item = {}) {
  const name = h("input", { id: "c-name", value: item.name || "", maxLength: 80 });
  const duration = h("select", { id: "c-duration" }, DURATIONS.map((m) =>
    h("option", { value: m, selected: m === (item.duration_min || 60) }, durationText(m))));
  const price = h("input", { id: "c-price", inputMode: "decimal", placeholder: "80,00",
    value: item.price_cents != null ? (item.price_cents / 100).toFixed(2).replace(".", ",") : "" });
  return {
    nodes: [h("label", { htmlFor: "c-name" }, "Nome"), name, h("label", { htmlFor: "c-duration" }, "Duração"), duration,
      h("label", { htmlFor: "c-price" }, "Preço (R$)"), price],
    read() {
      const cents = toCents(price.value);
      if (cents === null) throw new Error("Preço inválido. Use algo como 80,00.");
      return { name: name.value, duration_min: Number(duration.value), price_cents: cents };
    },
  };
}

/** One row per weekday: does she work that day, and from/to what time. Only inside the salon's business
 *  hours: days it is closed cannot be chosen. Without hours of her own (null) she starts from the salon's. */
function workHoursFields(workHours, settings) {
  const rows = DAY_NAMES.map((dayName, day) => {
    const salon = salonShift(settings, day);
    const salonOpen = Boolean(salon);
    const shift = salonOpen && (workHours ? workHours.find((s) => s.day === day) : salon);
    const works = h("input", { type: "checkbox", checked: Boolean(shift), disabled: !salonOpen });
    const limits = { type: "time", step: 900, min: salon?.start, max: salon?.end };
    const start = h("input", { ...limits, value: shift ? shift.start : salon?.start || "", disabled: !shift, "aria-label": `${dayName}: entrada` });
    const end = h("input", { ...limits, value: shift ? shift.end : salon?.end || "", disabled: !shift, "aria-label": `${dayName}: saída` });
    works.addEventListener("change", () => { start.disabled = end.disabled = !works.checked; });
    return { day, dayName, works, start, end,
      node: h("div", { className: "work-row" + (salonOpen ? "" : " salon-closed") },
        h("label", { className: "choice" }, works, dayName), start, h("span", { className: "muted" }, "às"), end,
        h("span", { className: "muted closed-note" }, salonOpen ? `salão: ${salon.start}–${salon.end}` : "salão fechado")) };
  });
  return {
    nodes: [h("label", {}, "Dias e horários de trabalho"), rows.map((r) => r.node),
      h("p", { className: "muted" }, "Sempre dentro do funcionamento do salão em cada dia (veja em Configurações › Funcionamento). "
        + "A agenda oferece horários com ela só nesses dias e horários.")],
    read() {
      const chosen = rows.filter((r) => r.works.checked);
      const empty = chosen.find((r) => !r.start.value || !r.end.value);
      if (empty) throw new Error(`${empty.dayName}: informe a entrada e a saída.`);
      return chosen.map((r) => ({ day: r.day, start: r.start.value, end: r.end.value }));
    },
  };
}

/** One row per service: does she perform it, and her commission for it: % of the price or a fixed
 *  amount each time (empty = no commission). */
function offeredServicesFields(services, item) {
  const rows = services.map((s) => {
    const rule = (item.commissions || {})[s.id];
    const does = h("input", { type: "checkbox", value: s.id, checked: (item.services || []).includes(s.id) });
    const kind = h("select", { "aria-label": `${s.name}: tipo de comissão`, disabled: !does.checked },
      h("option", { value: "percent", selected: rule?.kind !== "fixed" }, "%"),
      h("option", { value: "fixed", selected: rule?.kind === "fixed" }, "R$"));
    const value = h("input", { inputMode: "decimal", placeholder: "sem comissão", disabled: !does.checked,
      "aria-label": `${s.name}: comissão`,
      value: !rule ? "" : rule.kind === "fixed" ? (rule.value / 100).toFixed(2).replace(".", ",") : String(rule.value) });
    does.addEventListener("change", () => { kind.disabled = value.disabled = !does.checked; });
    return { service: s, does, kind, value,
      node: h("div", { className: "service-row" },
        h("label", { className: "choice" }, does, s.name, !s.active && " (desativado)"), kind, value) };
  });
  return {
    nodes: [h("label", {}, "Serviços que ela faz e a comissão de cada um"),
      services.length === 0 && h("p", { className: "muted" }, "Cadastre os serviços primeiro."),
      rows.map((r) => r.node),
      services.length > 0 && h("p", { className: "muted" }, "Comissão: percentual do preço do serviço, ou um valor fixo em R$ "
        + "por atendimento. Fica gravada em cada agendamento, como o preço.")],
    read() {
      const chosen = rows.filter((r) => r.does.checked);
      const commissions = {};
      for (const r of chosen) {
        const text = r.value.value.trim();
        if (!text) continue;
        const number = r.kind.value === "fixed" ? toCents(text) : Number(text.replace(",", "."));
        if (number === null || !Number.isInteger(number) || number < 0 || (r.kind.value === "percent" && number > 100)) {
          throw new Error(`${r.service.name}: comissão inválida (percentual inteiro de 0 a 100, ou um valor como 30,00).`);
        }
        commissions[r.service.id] = { kind: r.kind.value, value: number };
      }
      return { services: chosen.map((r) => r.service.id), commissions };
    },
  };
}

function professionalFields(item = {}, services = [], settings) {
  const name = h("input", { id: "c-name", value: item.name || "", maxLength: 80 });
  const offered = offeredServicesFields(services, item);
  const hours = workHoursFields(item.work_hours, settings);
  return {
    nodes: [h("label", { htmlFor: "c-name" }, "Nome"), name, offered.nodes, hours.nodes],
    read: () => ({ name: name.value, ...offered.read(),
      work_hours: hours.read() }),
  };
}

/** What the screen shows before anything is registered: a picture, what goes here and how to start. */
function emptyState({ image, heading, text, button, hint }, onAdd) {
  return h("div", { className: "card empty-state" },
    h("img", { src: image, alt: "", width: 160, height: 120 }),
    h("h2", {}, heading),
    h("p", { className: "muted" }, text),
    hint && h("p", { className: "muted" }, hint),
    onAdd && h("button", { className: "primary", onclick: onAdd }, button));
}

export function createScreen({ route, title, empty, summary, details = null, marker = null, menuItems = null, notice = null }) {
  return async function mount(container) {
    let editing = null;                        // null = list, {} = new, object = edit

    async function draw() {
      let items, services = [], settings = null, timeOffs = [];
      const professionalsOnly = (request) => (route === "professionals" ? request() : null);
      try {
        [items, services, settings, timeOffs] = await Promise.all([api("GET", `/${route}`),
          professionalsOnly(() => api("GET", "/services")) || [],
          professionalsOnly(() => api("GET", "/settings")),
          // from today to a year ahead: ongoing and planned absences (vacations are booked early)
          professionalsOnly(() => api("GET", "/time-off", null, { from: today(), to: addDays(today(), 365) })) || []]);
      } catch (error) { return render(container, h("p", { className: "notice" }, error.message)); }
      render(container, editing ? formView(services, settings) : listView(items, services, settings, timeOffs));
    }

    function listView(items, services, settings, timeOffs) {
      const serviceNames = Object.fromEntries(services.map((s) => [s.id, s.name]));
      const manager = isManager();                // employees only see the list
      const add = manager ? () => { editing = {}; draw(); } : null;
      // One compact row per item, in pages, with a search once the list is long (paged-list.js).
      const row = (item) => h("li", { className: "list-item" + (item.active === false ? " inactive" : "") },
        h("div", { className: "list-main" },
          h("div", { className: "list-title" }, h("strong", {}, marker && marker(item, items), item.name,
            item.active === false && h("span", { className: "badge" }, "Desativado")),
          h("span", { className: "muted" }, summary(item, serviceNames))),
          details && details(item, { settings, timeOffs, all: items, redraw: draw, serviceNames })),
        manager && actionsMenu(item.name, [
          { text: "Editar", onclick: () => { editing = item; draw(); } },
          ...(menuItems ? menuItems(item, draw) : []),
          { text: "Excluir", danger: true, onclick: (e) => remove(e.target, item) }]));
      return [
        h("div", { className: "row" }, h("h1", {}, title, items.length > 0 && h("span", { className: "count" }, ` (${items.length})`)),
          add && items.length > 0 && h("button", { className: "primary", onclick: add }, "Adicionar")),
        items.length === 0 && emptyState(empty(services), add),
        notice && notice(items, settings),
        items.length > 0 && pagedList(items, row, { label: title.toLowerCase() }),
      ];
    }

    function formView(services, settings) {
      const fields = route === "services" ? serviceFields(editing) : professionalFields(editing, services, settings);
      const saveButton = h("button", { className: "primary" }, "Salvar");
      saveButton.addEventListener("click", () => whileDisabled(saveButton, async () => {
        try {
          const body = fields.read();
          if (editing.id) await api("PUT", `/${route}/${editing.id}`, body);
          else await api("POST", `/${route}`, body);
          notify("Salvo!");
          editing = null;
          draw();
        } catch (error) { notify(error.message, true); }
      }));
      return h("div", { className: "card" }, h("h1", {}, editing.id ? "Editar" : "Novo"), fields.nodes,
        h("div", { className: "actions" }, saveButton,
          h("button", { className: "secondary", onclick: () => { editing = null; draw(); } }, "Voltar")));
    }

    function remove(button, item) {
      const access = item.login ? ` O acesso dela ao sistema (${item.login}) também é removido.` : "";
    if (!confirm(`Excluir "${item.name}"? Os agendamentos já feitos continuam na agenda.${access}`)) return;
      whileDisabled(button, async () => {
        try { await api("DELETE", `/${route}/${item.id}`); notify("Excluído."); draw(); }
        catch (error) { notify(error.message, true); }
      });
    }

    draw();
  };
}

/** Her current and coming absences (vacation, sick...), each one opens to be removed, and a button to
 *  add one: the place to plan vacations, without paging through the calendar. */
function absencesOf(p, timeOffs, all, redraw) {
  const hers = timeOffs.filter((t) => t.professional_id === p.id);
  const add = () => openTimeOffDialog({ date: today(), professionalId: p.id, professionals: all, onSaved: redraw });
  return h("div", { className: "absences" },
    h("span", { className: "muted" }, hers.length ? "Ausências:" : "Sem ausências marcadas."),
    hers.map((t) => h("button", { className: "away-chip", title: t.reason || "", onclick: () => openTimeOffDetails(t, p.name, redraw) },
      absenceSummary(t), t.reason && ` · ${t.reason}`)),
    h("button", { className: "link", onclick: add }, "+ Adicionar ausência"));
}

/** Disabling keeps the service (and its appointments) but stops offering it for new appointments. */
function toggleActive(service, redraw) {
  const enabling = !service.active;
  return [{ text: enabling ? "Ativar" : "Desativar", onclick: async () => {
    if (!enabling && !confirm(`Desativar "${service.name}"? Ele deixa de aparecer em novos agendamentos até ser ativado de novo. `
      + "Os agendamentos já feitos continuam.")) return;
    try {
      await api("PUT", `/services/${service.id}`, { name: service.name, duration_min: service.duration_min,
        price_cents: service.price_cents, active: enabling });
      notify(enabling ? "Serviço ativado." : "Serviço desativado.");
      redraw();
    } catch (error) { notify(error.message, true); }
  } }];
}

/** "Corte 40% · Manicure R$ 15,00" for the professionals list. */
function commissionSummary(p, serviceNames) {
  const parts = Object.entries(p.commissions || {}).filter(([id]) => serviceNames[id])
    .sort(([a], [b]) => serviceNames[a].localeCompare(serviceNames[b], "pt-BR"))          // by the service's name
    .map(([id, c]) => `${serviceNames[id]} ${c.kind === "percent" ? `${c.value}%` : formatMoney(c.value)}`);
  return parts.length ? `Comissão: ${parts.join(" · ")}` : "Sem comissão definida";
}

export const services = createScreen({ route: "services", title: "Serviços",
  empty: () => ({ image: "img/empty-services.svg", heading: "Nenhum serviço cadastrado", button: "Adicionar serviço",
    text: "Cadastre os serviços que o salão oferece, com a duração e o preço de cada um. Eles aparecem na hora de agendar." }),
  summary: (s) => `${durationText(s.duration_min)} · ${formatMoney(s.price_cents)}`,
  menuItems: toggleActive });

export const professionals = createScreen({ route: "professionals", title: "Profissionais",
  empty: (services) => ({ image: "img/empty-professionals.svg", heading: "Nenhuma profissional cadastrada",
    button: "Adicionar profissional",
    text: "Cadastre quem atende no salão, os serviços que cada uma faz e os dias e horários de trabalho.",
    hint: services.length === 0 && "Dica: cadastre os serviços primeiro, para marcar o que cada uma faz." }),
  summary: (p, serviceNames) => p.services.map((id) => serviceNames[id]).filter(Boolean).join(", ") || "sem serviços",
  details: (p, { settings, timeOffs, all, redraw, serviceNames }) => [h("div", { className: "muted" }, workHoursSummary(p.work_hours)),
    h("div", { className: "muted" }, commissionSummary(p, serviceNames)),
    hoursOutsideSalon(settings, p.work_hours) && h("div", { className: "warning" },
      "⚠ Parte deste horário fica fora do funcionamento do salão e não é oferecida na agenda."),
    p.login && h("div", { className: "muted" }, `Acesso ao sistema: ${p.login}`),
    absencesOf(p, timeOffs, all, redraw)],
  // the reverse path of Acessos: a professional registered here gets her login
  menuItems: (p, redraw) => (p.login ? [] : [{ text: "Criar acesso",
    onclick: () => openAccessDialog({ professional: p, onCreated: redraw }) }]),
  marker: (p, all) => h("span", { className: `dot ${colorClass(all, p.id)}`, "aria-hidden": "true" }),   // her color in the agenda
  notice: (all, settings) => coverageWarning(settings, all) });
