// The alert shown in Funcionamento and Profissionais: times the salon is open with no professional
// working, so nobody can book them. Shared by both screens, so it lives in neither.
import { DAY_NAMES, uncoveredHours } from "../calendar.js";
import { h } from "../util.js";

/** The alert, or null when every open hour is covered or there are no professionals yet (that screen
 *  already says so). */
export function coverageWarning(settings, professionals) {
  if (!professionals.length) return null;
  const gaps = uncoveredHours(settings, professionals);
  if (!gaps.length) return null;
  const byDay = DAY_NAMES.map((name, day) => [name, gaps.filter((g) => g.day === day)]).filter(([, list]) => list.length);
  return h("div", { className: "card coverage-warning", role: "status" },
    h("strong", {}, "⚠ Horários sem nenhuma profissional atendendo"),
    h("p", { className: "muted" }, "O salão está aberto, mas ninguém trabalha nestes horários: eles não aparecem para agendar."),
    h("ul", {}, byDay.map(([name, list]) =>
      h("li", {}, `${name}: ${list.map((g) => `${g.start}–${g.end}`).join(", ")}`))),
    h("p", { className: "muted" }, "Para cobrir, ajuste o horário das profissionais (em Profissionais) ou o do salão (em Configurações › Funcionamento)."));
}
