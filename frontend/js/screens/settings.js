// Configurações: the salon's business hours, the window every professional works inside.
import { api } from "../api.js";
import { hoursOutsideSalon } from "../calendar.js";
import { h, notify, render, whileDisabled } from "../util.js";

const DAYS = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"];   // 0 = Monday

export async function mount(container) {
  let settings, professionals;
  try { [settings, professionals] = await Promise.all([api("GET", "/settings"), api("GET", "/professionals")]); }
  catch (error) { return render(container, h("p", { className: "notice" }, error.message)); }

  const dayBoxes = DAYS.map((_, i) => h("input", { type: "checkbox", checked: settings.open_days.includes(i) }));
  const opens = h("input", { id: "s-opens", type: "time", step: 900, value: settings.opens });
  const closes = h("input", { id: "s-closes", type: "time", step: 900, value: settings.closes });
  const saveButton = h("button", { className: "primary" }, "Salvar");

  saveButton.addEventListener("click", () => whileDisabled(saveButton, async () => {
    try {
      const saved = await api("PUT", "/settings", {
        open_days: dayBoxes.flatMap((c, i) => (c.checked ? [i] : [])), opens: opens.value, closes: closes.value });
      notify("Horário de funcionamento salvo.");
      // Hours outside the new window are simply not offered; tell who is affected so it can be fixed.
      const outside = professionals.filter((p) => hoursOutsideSalon(saved, p.work_hours));
      if (outside.length) {
        notify(`O horário de ${outside.map((p) => p.name).join(", ")} fica em parte fora deste funcionamento: `
          + "essa parte não é oferecida na agenda. Ajuste em Profissionais.", true);
      }
    } catch (error) { notify(error.message, true); }
  }));

  render(container, h("h1", {}, "Configurações"), h("div", { className: "card" },
    h("h2", {}, "Horário de funcionamento do salão"),
    h("p", { className: "muted" }, "As profissionais só atendem dentro destes dias e horários. "
      + "O horário de cada uma (em Profissionais) precisa caber aqui."),
    h("label", {}, "Dias em que o salão abre"),
    DAYS.map((name, i) => h("label", { className: "choice" }, dayBoxes[i], name)),
    h("label", { htmlFor: "s-opens" }, "Abre às"), opens,
    h("label", { htmlFor: "s-closes" }, "Fecha às"), closes,
    h("p", { className: "muted" }, "Os horários livres seguem de 15 em 15 minutos dentro deste intervalo."),
    h("div", { className: "actions" }, saveButton)));
}
