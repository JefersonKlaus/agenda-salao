// Financeiro (manager only): the month's money, from the appointments. Previsto = everything booked in
// the month; Recebido = what clients already paid; A receber = the rest. Per professional and per
// service, plus the appointments that already happened and are still unpaid, to mark them paid here.
import { api } from "../api.js";
import { h, formatMoney, notify, prettyDate, render, today, whileDisabled } from "../util.js";

const monthName = (month) => {
  const [year, number] = month.split("-").map(Number);
  const text = new Date(year, number - 1, 1).toLocaleDateString("pt-BR", { month: "long", year: "numeric" });
  return text.charAt(0).toUpperCase() + text.slice(1);
};
const shiftMonth = (month, step) => {
  const [year, number] = month.split("-").map(Number);
  const d = new Date(year, number - 1 + step, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
};

export async function mount(container) {
  let month = today().slice(0, 7);

  async function draw() {
    const nav = h("div", { className: "month-nav" },
      h("button", { className: "secondary small", "aria-label": "Mês anterior", onclick: () => { month = shiftMonth(month, -1); draw(); } }, "‹"),
      h("strong", {}, monthName(month)),
      h("button", { className: "secondary small", "aria-label": "Próximo mês", onclick: () => { month = shiftMonth(month, 1); draw(); } }, "›"));
    const header = h("div", { className: "row" }, h("h1", {}, "Financeiro"), nav);
    let data;
    try { data = await api("GET", "/finance", null, { month }); }
    catch (error) { return render(container, header, h("p", { className: "notice" }, error.message)); }

    const { totals } = data;
    render(container, header,
      h("div", { className: "totals" },
        h("div", {}, h("span", {}, "Previsto no mês"), h("strong", {}, formatMoney(totals.expected))),
        h("div", {}, h("span", {}, "Recebido"), h("strong", {}, formatMoney(totals.paid))),
        h("div", {}, h("span", {}, "A receber"), h("strong", { className: "pending" }, formatMoney(totals.pending)))),
      totals.count === 0 ? h("p", { className: "notice" }, "Nenhum agendamento neste mês.") : [
        overdueCard(data.overdue),
        table("Por profissional", "Profissional", data.by_professional, totals, true),
        table("Por serviço", "Serviço", data.by_service, totals),
      ]);
  }

  /** Appointments that already happened and nobody marked as paid: the ones to chase. */
  function overdueCard(overdue) {
    if (!overdue.length) return h("div", { className: "card" }, h("h2", {}, "Atendimentos sem pagamento"),
      h("p", { className: "muted" }, "Todos os atendimentos que já aconteceram neste mês estão pagos."));
    const total = overdue.reduce((sum, a) => sum + a.price_cents, 0);
    return h("div", { className: "card" },
      h("h2", {}, `Atendimentos sem pagamento (${overdue.length})`),
      h("p", { className: "muted" }, `Já aconteceram e ainda não foram marcados como pagos: ${formatMoney(total)}.`),
      h("ul", { className: "overdue" }, overdue.map((a) => {
        const button = h("button", { className: "primary small" }, "Marcar como pago");
        button.addEventListener("click", () => whileDisabled(button, async () => {
          try {
            await api("PUT", `/appointments/${a.id}/payment`, { paid: true });
            notify(`Pagamento de ${a.client_name} registrado.`);
            draw();
          } catch (error) { notify(error.message, true); }
        }));
        return h("li", {},
          h("div", {}, h("strong", {}, `${prettyDate(a.date)}, ${a.start} · ${a.client_name}`),
            h("div", { className: "muted" }, `${a.service_name} · ${a.professional_name} · ${formatMoney(a.price_cents)}`)),
          button);
      })));
  }

  /** `commission`: also what each professional earns for the month's appointments. */
  function table(title, firstColumn, rows, totals, commission = false) {
    const money = (cents, className) => h("td", { className }, formatMoney(cents));
    const columns = [firstColumn, "Atend.", "Previsto", "Recebido", "A receber", commission && "Comissão"].filter(Boolean);
    const cells = (r, pendingClass) => [h("td", {}, String(r.count)), money(r.expected), money(r.paid),
      money(r.pending, pendingClass), commission && money(r.commission)];
    return h("div", { className: "card" }, h("h2", {}, title),
      h("div", { className: "table-scroll" }, h("table", { className: "money" },
        h("thead", {}, h("tr", {}, columns.map((c) => h("th", {}, c)))),
        h("tbody", {}, rows.map((r) => h("tr", {}, h("td", {}, r.name), cells(r, r.pending ? "pending" : null)))),
        h("tfoot", {}, h("tr", {}, h("td", {}, "Total"), cells(totals, "pending"))))));
  }

  draw();
}
