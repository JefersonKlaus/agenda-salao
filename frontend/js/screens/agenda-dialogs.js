// The agenda's pop-ups: booking, seeing an appointment (to cancel it or give it to another
// professional) and registering or removing a professional's absence (sick, travelling...).
import { api } from "../api.js";
import { isOnline } from "../offline.js";
import { addMinutes, durationText, formatMoney, h, notify, openDialog, prettyDate, render, salonNow, whileDisabled } from "../util.js";

/** Booking to record something that already happened: a past day, or a time today that already went
 *  by (clicked on the agenda). Only then does the dialog offer times that passed. */
function recordingThePast(date, wantedTime) {
  const now = salonNow();
  if (date !== now.date) return date < now.date;
  return Boolean(wantedTime) && Number(wantedTime.slice(0, 2)) * 60 + Number(wantedTime.slice(3, 5)) <= now.minutes;
}

/** New appointment. `date`/`time` come from where the user clicked; `professionalId` from the filter. */
export function openBookingDialog({ date, time = null, professionalId = "", services: allServices, professionals, onBooked }) {
  const services = allServices.filter((s) => s.active !== false);          // disabled ones are not offered
  const state = { date, service: null, professional: null, time: null, wantedTime: time };
  // Only the manager books, and she may also record what already happened: no minimum date.
  const dateInput = h("input", { id: "f-date", type: "date", value: date, required: true });
  const serviceSelect = h("select", { id: "f-service" },
    h("option", { value: "" }, "Escolha o serviço"),
    services.map((s) => h("option", { value: s.id }, `${s.name} (${durationText(s.duration_min)})`)));
  const professionalSelect = h("select", { id: "f-professional", disabled: true }, h("option", { value: "" }, "Escolha o serviço primeiro"));
  const slotGrid = h("div", { className: "slots" });
  const nameInput = h("input", { id: "f-name", maxLength: 80, autocomplete: "off" });
  const phoneInput = h("input", { id: "f-phone", type: "tel", maxLength: 20, placeholder: "(11) 90000-0000" });
  const saveButton = h("button", { className: "primary", disabled: true }, "Agendar");

  const updateButton = () => { saveButton.disabled = !(state.time && nameInput.value.trim()); };

  function pick(button, time) {
    state.time = time;
    slotGrid.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b === button)));
    updateButton();
  }

  async function loadSlots() {
    state.time = null;
    updateButton();
    if (!state.service || !state.professional || !state.date) return render(slotGrid);
    render(slotGrid, h("span", { className: "muted" }, "Buscando horários…"));
    const asked = { ...state };
    try {
      const times = await api("GET", "/availability", null, { date: state.date, service_id: state.service,
        professional_id: state.professional, ...(recordingThePast(state.date, state.wantedTime) ? { include_past: "true" } : {}) });
      if (asked.date !== state.date || asked.service !== state.service || asked.professional !== state.professional) return;
      const buttons = times.map((t) => h("button", { type: "button", "aria-pressed": "false", onclick: (e) => pick(e.target, t) }, t));
      render(slotGrid, buttons.length ? buttons : h("span", { className: "muted" }, "Sem horários livres neste dia."));
      const wanted = buttons[times.indexOf(state.wantedTime)];
      if (wanted) pick(wanted, state.wantedTime);                  // the slot that was clicked on the calendar
    } catch (error) { render(slotGrid, h("span", { className: "muted" }, error.message)); }
  }

  dateInput.addEventListener("change", () => { state.date = dateInput.value; loadSlots(); });
  serviceSelect.addEventListener("change", () => {
    state.service = serviceSelect.value || null;
    const eligible = professionals.filter((p) => p.services.includes(state.service));
    state.professional = eligible.some((p) => p.id === professionalId) ? professionalId : null;
    professionalSelect.disabled = !state.service;
    render(professionalSelect, h("option", { value: "" }, eligible.length ? "Escolha a profissional" : "Ninguém faz este serviço"),
      eligible.map((p) => h("option", { value: p.id, selected: p.id === state.professional }, p.name)));
    loadSlots();
  });
  professionalSelect.addEventListener("change", () => { state.professional = professionalSelect.value || null; loadSlots(); });
  nameInput.addEventListener("input", updateButton);

  const dialog = openDialog("Novo agendamento",
    services.length === 0 && h("p", { className: "muted" }, "Cadastre (ou ative) os serviços e as profissionais primeiro."),
    h("label", { htmlFor: "f-date" }, "Data"), dateInput,
    h("label", { htmlFor: "f-service" }, "Serviço"), serviceSelect,
    h("label", { htmlFor: "f-professional" }, "Profissional"), professionalSelect,
    h("label", {}, "Horário"), slotGrid,
    h("label", { htmlFor: "f-name" }, "Nome da cliente"), nameInput,
    h("label", { htmlFor: "f-phone" }, "Telefone (opcional)"), phoneInput,
    h("div", { className: "actions" }, saveButton,
      h("button", { className: "secondary", onclick: () => dialog.close() }, "Fechar")));

  saveButton.addEventListener("click", () => whileDisabled(saveButton, async () => {
    try {
      await api("POST", "/appointments", { date: state.date, start: state.time, service_id: state.service,
        professional_id: state.professional, client_name: nameInput.value, client_phone: phoneInput.value });
      notify("Agendado!");
      dialog.close();
      onBooked();
    } catch (error) { notify(error.message, true); state.wantedTime = null; loadSlots(); }   // the slot may have been taken
  }));
}

/** Details of an appointment: cancel it, or give it to another professional who does that service.
 *  `away` = she is absent at that time (the appointment was made before the absence). One that already
 *  passed is read-only for employees. The manager also marks whether the client paid. */
export function openAppointmentDialog(appt, { professionals, away = false, onChanged, manager = false }) {
  const offline = !isOnline();                   // no connection: look, but change nothing
  const readOnly = offline || !manager;          // only the manager changes appointments
  const paymentButton = manager && !offline && h("button", { className: appt.paid ? "secondary" : "primary" },
    appt.paid ? "Desfazer pagamento" : "Marcar como pago");
  const cancelButton = h("button", { className: "danger" }, "Cancelar agendamento");
  const row = (label, value) => value && [h("dt", {}, label), h("dd", {}, value)];
  const others = professionals.filter((p) => p.id !== appt.professional_id && p.services.includes(appt.service_id));
  const otherSelect = h("select", { id: "a-professional" }, h("option", { value: "" }, "Escolha a profissional"),
    others.map((p) => h("option", { value: p.id }, p.name)));
  const moveButton = h("button", { className: "secondary" }, "Trocar");
  const dialog = openDialog(`${appt.start} – ${addMinutes(appt.start, appt.duration_min)}`,
    h("p", { className: "muted" }, prettyDate(appt.date)),
    away && h("p", { className: "warning" }, `⚠ ${appt.professional_name} está ausente nesse horário: troque a profissional ou cancele.`),
    h("dl", { className: "details" },
      row("Cliente", appt.client_name), row("Telefone", appt.client_phone), row("Serviço", appt.service_name),
      row("Profissional", appt.professional_name), row("Valor", formatMoney(appt.price_cents)),
      row("Pagamento", appt.paid ? "Pago" : "A receber")),
    readOnly ? h("p", { className: "muted" }, offline ? "Sem conexão: dá para consultar, mas não alterar."
      : "Só a gerente pode alterar ou cancelar agendamentos.")
      : [h("label", { htmlFor: "a-professional" }, "Trocar profissional"),
        others.length ? h("div", { className: "inline-form" }, otherSelect, moveButton)
          : h("p", { className: "muted" }, "Nenhuma outra profissional faz este serviço.")],
    h("div", { className: "actions" }, paymentButton, !readOnly && cancelButton,
      h("button", { className: "secondary", onclick: () => dialog.close() }, "Fechar")));

  if (paymentButton) {
    paymentButton.addEventListener("click", () => whileDisabled(paymentButton, async () => {
      try {
        const saved = await api("PUT", `/appointments/${appt.id}/payment`, { paid: !appt.paid });
        notify(saved.paid ? "Pagamento registrado." : "Pagamento desfeito.");
        dialog.close();
        onChanged();
      } catch (error) { notify(error.message, true); }
    }));
  }

  moveButton.addEventListener("click", () => {
    if (!otherSelect.value) return notify("Escolha a profissional.", true);
    whileDisabled(moveButton, async () => {
      try {
        const moved = await api("PUT", `/appointments/${appt.id}/professional`, { professional_id: otherSelect.value });
        notify(`Agendamento passado para ${moved.professional_name}.`);
        dialog.close();
        onChanged();
      } catch (error) { notify(error.message, true); }
    });
  });
  cancelButton.addEventListener("click", () => {
    if (!confirm(`Cancelar o horário de ${appt.client_name} às ${appt.start}?`)) return;
    whileDisabled(cancelButton, async () => {
      try {
        await api("DELETE", `/appointments/${appt.id}`);
        notify("Agendamento cancelado.");
        dialog.close();
        onChanged();
      } catch (error) { notify(error.message, true); }
    });
  });
}

/** Kinds of absence, with the label the screens show. "other" has no label of its own ("Ausente"). */
export const TIME_OFF_KINDS = [["vacation", "Férias"], ["sick", "Doença"], ["travel", "Viagem"], ["day_off", "Folga"],
  ["other", "Outro"]];
const KIND_LABEL = Object.fromEntries(TIME_OFF_KINDS.filter(([kind]) => kind !== "other"));

/** "Férias · note", "Doente" (an old absence with only a note), or "" when there is nothing to say. */
export function absenceLabel(t) {
  return [KIND_LABEL[t.kind], t.reason].filter(Boolean).join(" · ");
}

const shortDate = (iso) => iso.slice(8, 10) + "/" + iso.slice(5, 7);

/** "Férias · 05/01 – 20/01" or "Doença · 18/11, 14:00–18:00": one line for lists. */
export function absenceSummary(t) {
  const days = t.first_day === t.last_day ? shortDate(t.first_day) : `${shortDate(t.first_day)} – ${shortDate(t.last_day)}`;
  return `${KIND_LABEL[t.kind] || "Ausente"} · ${days}${t.start ? `, ${t.start}–${t.end}` : ""}`;
}

/** Registers an absence: whole days (sick, travelling...) or only some hours, for one or more days. */
export function openTimeOffDialog({ date, professionalId = "", professionals, onSaved }) {
  const who = h("select", { id: "o-professional" }, h("option", { value: "" }, "Escolha a profissional"),
    professionals.map((p) => h("option", { value: p.id, selected: p.id === professionalId }, p.name)));
  const first = h("input", { id: "o-first", type: "date", value: date });
  const last = h("input", { id: "o-last", type: "date", value: date, min: date });
  const wholeDay = h("input", { id: "o-whole", type: "checkbox", checked: true });
  const start = h("input", { id: "o-start", type: "time", step: 900, value: "09:00", disabled: true, "aria-label": "Ausente das" });
  const end = h("input", { id: "o-end", type: "time", step: 900, value: "12:00", disabled: true, "aria-label": "Ausente até" });
  // One tap for the usual kinds; tapping the chosen one again unselects it. Nothing chosen = "other".
  let kind = null;
  const kindButtons = TIME_OFF_KINDS.map(([value, label]) => h("button", { type: "button", "aria-pressed": "false",
    onclick: () => {
      kind = kind === value ? null : value;
      kindButtons.forEach((b, i) => b.setAttribute("aria-pressed", String(TIME_OFF_KINDS[i][0] === kind)));
    } }, label));
  const reason = h("input", { id: "o-reason", maxLength: 80, placeholder: "Ex.: cirurgia, casamento da irmã" });
  const saveButton = h("button", { className: "primary" }, "Salvar ausência");
  wholeDay.addEventListener("change", () => { start.disabled = end.disabled = wholeDay.checked; });
  first.addEventListener("change", () => { last.min = first.value; if (last.value < first.value) last.value = first.value; });

  const dialog = openDialog("Ausência",
    h("p", { className: "muted" }, "Nesse período ela não recebe novos agendamentos. Os que já existem aparecem com aviso, "
      + "para você trocar a profissional ou cancelar."),
    h("label", { htmlFor: "o-professional" }, "Profissional"), who,
    h("div", { className: "two-columns" },
      h("div", {}, h("label", { htmlFor: "o-first" }, "Do dia"), first),
      h("div", {}, h("label", { htmlFor: "o-last" }, "Até o dia"), last)),
    h("label", { className: "choice" }, wholeDay, "Dia inteiro"),
    h("div", { className: "inline-form" }, start, h("span", { className: "muted" }, "às"), end),
    h("label", {}, "Tipo"), h("div", { className: "chips", role: "group", "aria-label": "Tipo de ausência" }, kindButtons),
    h("label", { htmlFor: "o-reason" }, "Observação (opcional)"), reason,
    h("div", { className: "actions" }, saveButton,
      h("button", { className: "secondary", onclick: () => dialog.close() }, "Fechar")));

  saveButton.addEventListener("click", () => whileDisabled(saveButton, async () => {
    try {
      if (!who.value) throw new Error("Escolha a profissional.");
      const { affected } = await api("POST", "/time-off", { professional_id: who.value, first_day: first.value,
        last_day: last.value || first.value, reason: reason.value, kind: kind || "other",
        ...(wholeDay.checked ? {} : { start: start.value, end: end.value }) });
      notify("Ausência salva.");
      if (affected.length) {
        notify(`${affected.length} agendamento(s) dela caem nesse período. Abra cada um (marcado com ⚠) `
          + "para trocar a profissional ou cancelar.", true);
      }
      dialog.close();
      onSaved();
    } catch (error) { notify(error.message, true); }
  }));
}

/** An existing absence, with the option to remove it. */
export function openTimeOffDetails(timeOff, professionalName, onRemoved, canRemove = true) {
  const removeButton = canRemove && h("button", { className: "danger", disabled: !isOnline(),
    title: isOnline() ? null : "Sem conexão: não dá para alterar agora" }, "Remover ausência");
  const days = timeOff.first_day === timeOff.last_day ? prettyDate(timeOff.first_day)
    : `${prettyDate(timeOff.first_day)} até ${prettyDate(timeOff.last_day)}`;
  const dialog = openDialog(`${professionalName} ausente`,
    h("dl", { className: "details" },
      h("dt", {}, "Quando"), h("dd", {}, days),
      h("dt", {}, "Horário"), h("dd", {}, timeOff.start ? `${timeOff.start} – ${timeOff.end}` : "Dia inteiro"),
      KIND_LABEL[timeOff.kind] && [h("dt", {}, "Tipo"), h("dd", {}, KIND_LABEL[timeOff.kind])],
      timeOff.reason && [h("dt", {}, "Observação"), h("dd", {}, timeOff.reason)]),
    h("div", { className: "actions" }, removeButton,
      h("button", { className: "secondary", onclick: () => dialog.close() }, "Fechar")));
  removeButton?.addEventListener("click", () => {        // only who may remove it gets the button
    if (!confirm("Remover esta ausência? Ela volta a receber agendamentos nesse período.")) return;
    whileDisabled(removeButton, async () => {
      try {
        await api("DELETE", `/time-off/${timeOff.id}`);
        notify("Ausência removida.");
        dialog.close();
        onRemoved();
      } catch (error) { notify(error.message, true); }
    });
  });
}
