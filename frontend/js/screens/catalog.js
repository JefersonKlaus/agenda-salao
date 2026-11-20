// Services and professionals: the same list-with-form screen, only the fields change.
import { api } from "../api.js";
import { isManager } from "../auth.js";
import { colorClass, hoursOutsideSalon, workHoursSummary } from "../calendar.js";
import { durationText, formatMoney, h, notify, render, toCents, whileDisabled } from "../util.js";

const DURATIONS = Array.from({ length: 32 }, (_, i) => (i + 1) * 15);
const DAY_NAMES = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"];   // 0 = Monday

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
    const salonOpen = settings.open_days.includes(day);
    const shift = salonOpen && (workHours ? workHours.find((s) => s.day === day) : { start: settings.opens, end: settings.closes });
    const works = h("input", { type: "checkbox", checked: Boolean(shift), disabled: !salonOpen });
    const limits = { type: "time", step: 900, min: settings.opens, max: settings.closes };
    const start = h("input", { ...limits, value: shift ? shift.start : settings.opens, disabled: !shift, "aria-label": `${dayName}: entrada` });
    const end = h("input", { ...limits, value: shift ? shift.end : settings.closes, disabled: !shift, "aria-label": `${dayName}: saída` });
    works.addEventListener("change", () => { start.disabled = end.disabled = !works.checked; });
    return { day, dayName, works, start, end,
      node: h("div", { className: "work-row" + (salonOpen ? "" : " salon-closed") },
        h("label", { className: "choice" }, works, dayName), start, h("span", { className: "muted" }, "às"), end,
        !salonOpen && h("span", { className: "muted closed-note" }, "salão fechado")) };
  });
  return {
    nodes: [h("label", {}, "Dias e horários de trabalho"), rows.map((r) => r.node),
      h("p", { className: "muted" }, `Sempre dentro do funcionamento do salão (${settings.opens}–${settings.closes}, `
        + "nos dias em que ele abre; veja em Configurações). A agenda oferece horários com ela só nesses dias e horários.")],
    read() {
      const chosen = rows.filter((r) => r.works.checked);
      const empty = chosen.find((r) => !r.start.value || !r.end.value);
      if (empty) throw new Error(`${empty.dayName}: informe a entrada e a saída.`);
      return chosen.map((r) => ({ day: r.day, start: r.start.value, end: r.end.value }));
    },
  };
}

function professionalFields(item = {}, services = [], settings) {
  const name = h("input", { id: "c-name", value: item.name || "", maxLength: 80 });
  const checkboxes = services.map((s) => h("input", { type: "checkbox", value: s.id,
    checked: (item.services || []).includes(s.id) }));
  const hours = workHoursFields(item.work_hours, settings);
  return {
    nodes: [h("label", { htmlFor: "c-name" }, "Nome"), name, h("label", {}, "Serviços que ela faz"),
      services.length === 0 && h("p", { className: "muted" }, "Cadastre os serviços primeiro."),
      services.map((s, i) => h("label", { className: "choice" }, checkboxes[i], s.name, !s.active && " (desativado)")),
      hours.nodes],
    read: () => ({ name: name.value, services: checkboxes.filter((c) => c.checked).map((c) => c.value),
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

export function createScreen({ route, title, empty, summary, details = null, marker = null, extraActions = null }) {
  return async function mount(container) {
    let editing = null;                        // null = list, {} = new, object = edit

    async function draw() {
      let items, services = [], settings = null;
      try {
        [items, services, settings] = await Promise.all([api("GET", `/${route}`),
          route === "professionals" ? api("GET", "/services") : [],
          route === "professionals" ? api("GET", "/settings") : null]);
      } catch (error) { return render(container, h("p", { className: "notice" }, error.message)); }
      render(container, editing ? formView(services, settings) : listView(items, services, settings));
    }

    function listView(items, services, settings) {
      const serviceNames = Object.fromEntries(services.map((s) => [s.id, s.name]));
      const manager = isManager();                // employees only see the list
      const add = manager ? () => { editing = {}; draw(); } : null;
      return [
        h("div", { className: "row" }, h("h1", {}, title),
          add && items.length > 0 && h("button", { className: "primary", onclick: add }, "Adicionar")),
        items.length === 0 && emptyState(empty(services), add),
        items.map((item) => h("div", { className: "card" + (item.active === false ? " inactive" : "") },
          h("div", { className: "row" }, h("strong", {}, marker && marker(item, items), item.name,
            item.active === false && h("span", { className: "badge" }, "Desativado")),
          h("span", { className: "muted" }, summary(item, serviceNames))),
          details && details(item, settings),
          manager && h("div", { className: "actions" },
            h("button", { className: "secondary", onclick: () => { editing = item; draw(); } }, "Editar"),
            extraActions && extraActions(item, draw),
            h("button", { className: "danger", onclick: (e) => remove(e.target, item) }, "Excluir")))),
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
      if (!confirm(`Excluir "${item.name}"? Os agendamentos já feitos continuam na agenda.`)) return;
      whileDisabled(button, async () => {
        try { await api("DELETE", `/${route}/${item.id}`); notify("Excluído."); draw(); }
        catch (error) { notify(error.message, true); }
      });
    }

    draw();
  };
}

/** Disabling keeps the service (and its appointments) but stops offering it for new appointments. */
function toggleActive(service, redraw) {
  const enabling = !service.active;
  return h("button", { className: "secondary", onclick: (e) => {
    if (!enabling && !confirm(`Desativar "${service.name}"? Ele deixa de aparecer em novos agendamentos até ser ativado de novo. `
      + "Os agendamentos já feitos continuam.")) return;
    whileDisabled(e.target, async () => {
      try {
        await api("PUT", `/services/${service.id}`, { name: service.name, duration_min: service.duration_min,
          price_cents: service.price_cents, active: enabling });
        notify(enabling ? "Serviço ativado." : "Serviço desativado.");
        redraw();
      } catch (error) { notify(error.message, true); }
    });
  } }, enabling ? "Ativar" : "Desativar");
}

export const services = createScreen({ route: "services", title: "Serviços",
  empty: () => ({ image: "img/empty-services.svg", heading: "Nenhum serviço cadastrado", button: "Adicionar serviço",
    text: "Cadastre os serviços que o salão oferece, com a duração e o preço de cada um. Eles aparecem na hora de agendar." }),
  summary: (s) => `${durationText(s.duration_min)} · ${formatMoney(s.price_cents)}`,
  extraActions: toggleActive });

export const professionals = createScreen({ route: "professionals", title: "Profissionais",
  empty: (services) => ({ image: "img/empty-professionals.svg", heading: "Nenhuma profissional cadastrada",
    button: "Adicionar profissional",
    text: "Cadastre quem atende no salão, os serviços que cada uma faz e os dias e horários de trabalho.",
    hint: services.length === 0 && "Dica: cadastre os serviços primeiro, para marcar o que cada uma faz." }),
  summary: (p, serviceNames) => p.services.map((id) => serviceNames[id]).filter(Boolean).join(", ") || "sem serviços",
  details: (p, settings) => [h("div", { className: "muted" }, workHoursSummary(p.work_hours)),
    hoursOutsideSalon(settings, p.work_hours) && h("div", { className: "warning" },
      "⚠ Parte deste horário fica fora do funcionamento do salão e não é oferecida na agenda.")],
  marker: (p, all) => h("span", { className: `dot ${colorClass(all, p.id)}`, "aria-hidden": "true" }) });   // her color in the agenda
