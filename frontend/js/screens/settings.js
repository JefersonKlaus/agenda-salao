// Configurações › Funcionamento (manager only): the salon's business hours, each day with its own opening and closing.
// They are the window every professional works inside.
import { api } from "../api.js";
import { DAY_NAMES as DAYS, hoursOutsideSalon, salonShift } from "../calendar.js";
import { h, notify, render, whileDisabled } from "../util.js";
import { coverageWarning } from "./coverage.js";

export async function mount(container) {
  let settings, professionals;
  try { [settings, professionals] = await Promise.all([api("GET", "/settings"), api("GET", "/professionals")]); }
  catch (error) { return render(container, h("p", { className: "notice" }, error.message)); }

  // One row per weekday: open or closed, and from/to what time. A closed day keeps the times typed in
  // the row, so opening it again does not start from blank.
  const rows = DAYS.map((name, day) => {
    const shift = salonShift(settings, day);
    const open = h("input", { type: "checkbox", checked: Boolean(shift), "aria-label": `${name}: aberto` });
    const opens = h("input", { type: "time", step: 900, value: shift?.start || "09:00", disabled: !shift,
      "aria-label": `${name}: abre às` });
    const closes = h("input", { type: "time", step: 900, value: shift?.end || "19:00", disabled: !shift,
      "aria-label": `${name}: fecha às` });
    open.addEventListener("change", () => { opens.disabled = closes.disabled = !open.checked; });
    return { day, name, open, opens, closes,
      node: h("div", { className: "work-row" },
        h("label", { className: "choice" }, open, name), opens, h("span", { className: "muted" }, "às"), closes) };
  });

  const saveButton = h("button", { className: "primary" }, "Salvar");
  saveButton.addEventListener("click", () => whileDisabled(saveButton, async () => {
    try {
      const chosen = rows.filter((r) => r.open.checked);
      if (!chosen.length) throw new Error("Marque pelo menos um dia em que o salão abre.");
      const empty = chosen.find((r) => !r.opens.value || !r.closes.value);
      if (empty) throw new Error(`${empty.name}: informe a abertura e o fechamento.`);
      const saved = await api("PUT", "/settings", {
        hours: chosen.map((r) => ({ day: r.day, start: r.opens.value, end: r.closes.value })) });
      notify("Horário de funcionamento salvo.");
      render(coverage, coverageWarning(saved, professionals));
      // Hours outside the new window are simply not offered; tell who is affected so it can be fixed.
      const outside = professionals.filter((p) => hoursOutsideSalon(saved, p.work_hours));
      if (outside.length) {
        notify(`O horário de ${outside.map((p) => p.name).join(", ")} fica em parte fora deste funcionamento: `
          + "essa parte não é oferecida na agenda. Ajuste em Profissionais.", true);
      }
    } catch (error) { notify(error.message, true); }
  }));

  const coverage = h("div");
  render(coverage, coverageWarning(settings, professionals));

  render(container, h("h1", {}, "Funcionamento do salão"), coverage, h("div", { className: "card" },
    h("h2", {}, "Horário de funcionamento do salão"),
    h("p", { className: "muted" }, "Marque os dias em que o salão abre e o horário de cada um. "
      + "As profissionais só atendem dentro destes horários."),
    rows.map((r) => r.node),
    h("p", { className: "muted" }, "Os horários livres seguem de 15 em 15 minutos."),
    h("div", { className: "actions" }, saveButton)));
}
