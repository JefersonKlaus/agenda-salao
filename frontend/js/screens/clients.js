// Clientes (manager only). The phone is each client's key: booking registers her, and here she can also
// be registered by hand. Her page has her history: every appointment, what she paid, what is open
// (already happened, not paid) and can be received right there, and what is still ahead.
import { api } from "../api.js";
import { formatMoney, formatPhone, h, notify, openDialog, prettyDate, render, whileDisabled } from "../util.js";
import { pagedList } from "./paged-list.js";

export async function mount(container) {
  // ------------------------------------------------------------------ the list
  async function list() {
    let clients;
    try { clients = await api("GET", "/clients"); }
    catch (error) { return render(container, h("p", { className: "notice" }, error.message)); }
    const row = (c) => h("li", { className: "list-item clickable", tabindex: 0, role: "button",
      onclick: () => detail(c.phone), onkeydown: (e) => { if (e.key === "Enter") detail(c.phone); } },
    h("div", { className: "list-main" }, h("div", { className: "list-title" }, h("strong", {}, c.name),
      h("span", { className: "muted" }, formatPhone(c.phone)))),
    h("span", { className: "chevron", "aria-hidden": "true" }, "›"));
    render(container,
      h("div", { className: "row" }, h("h1", {}, "Clientes", clients.length > 0 && h("span", { className: "count" }, ` (${clients.length})`)),
        h("button", { className: "primary", onclick: () => clientDialog(null, list) }, "Nova cliente")),
      h("p", { className: "muted" }, "O telefone é a chave de cada cliente: ao agendar com ele, ela já fica cadastrada."),
      clients.length === 0 ? h("div", { className: "card empty-state" }, h("h2", {}, "Nenhuma cliente ainda"),
        h("p", { className: "muted" }, "As clientes aparecem aqui assim que forem agendadas, ou cadastre uma agora."),
        h("button", { className: "primary", onclick: () => clientDialog(null, list) }, "Nova cliente"))
        : pagedList(clients, row, { label: "clientes (nome ou telefone)",
          searchText: (c) => `${c.name} ${c.phone} ${formatPhone(c.phone)}` }));
  }

  // ------------------------------------------------------------------ one client
  async function detail(phone) {
    let data;
    try { data = await api("GET", `/clients/${phone}`); }
    catch (error) { return notify(error.message, true); }
    const { client, totals, open, appointments } = data;
    const tile = (label, cents, className) => h("div", {}, h("span", {}, label), h("strong", { className }, cents));
    render(container,
      h("button", { className: "link back", onclick: list }, "‹ Clientes"),
      h("div", { className: "row" }, h("div", {}, h("h1", {}, client.name), h("p", { className: "muted" }, formatPhone(client.phone))),
        h("button", { className: "secondary", onclick: () => clientDialog(client, () => detail(phone)) }, "Editar nome")),
      h("div", { className: "totals four" },
        tile("Atendimentos", String(totals.visits)), tile("Pago", formatMoney(totals.paid)),
        tile("Em aberto", formatMoney(totals.open), totals.open ? "pending" : null), tile("Agendado a receber", formatMoney(totals.upcoming))),
      openCard(open, () => detail(phone)),
      historyCard(appointments, open));
  }

  /** Already happened and not paid: received right here, one by one or all at once. */
  function openCard(open, redraw) {
    if (!open.length) return h("div", { className: "card" }, h("h2", {}, "Em aberto"),
      h("p", { className: "muted" }, "Nada em aberto: tudo o que já aconteceu está pago."));
    const pay = async (appts) => {
      for (const a of appts) await api("PUT", `/appointments/${a.id}/payment`, { paid: true });
      notify(appts.length > 1 ? "Pagamentos registrados." : "Pagamento registrado.");
      redraw();
    };
    const total = open.reduce((sum, a) => sum + a.price_cents, 0);
    const all = h("button", { className: "primary small" }, `Receber tudo (${formatMoney(total)})`);
    all.addEventListener("click", () => whileDisabled(all, () => pay(open).catch((e) => notify(e.message, true))));
    return h("div", { className: "card" },
      h("div", { className: "row" }, h("h2", {}, `Em aberto (${open.length})`), open.length > 1 && all),
      h("ul", { className: "overdue" }, open.map((a) => {
        const button = h("button", { className: "primary small" }, "Marcar como pago");
        button.addEventListener("click", () => whileDisabled(button, () => pay([a]).catch((e) => notify(e.message, true))));
        return h("li", {}, h("div", {}, h("strong", {}, `${prettyDate(a.date)}, ${a.start}`),
          h("div", { className: "muted" }, `${a.service_name} · ${a.professional_name} · ${formatMoney(a.price_cents)}`)), button);
      })));
  }

  /** Every appointment, newest first: paid, open (happened, not paid: the API's `open`), or still ahead. */
  function historyCard(appointments, open) {
    const openIds = new Set(open.map((a) => a.id));
    const status = (a) => (a.paid ? h("span", { className: "pay paid" }, "Pago")
      : openIds.has(a.id) ? h("span", { className: "pay late" }, "Em aberto") : h("span", { className: "pay due" }, "A receber"));
    return h("div", { className: "card" }, h("h2", {}, "Histórico"),
      appointments.length === 0 ? h("p", { className: "muted" }, "Nenhum atendimento ainda.")
        : h("div", { className: "table-scroll" }, h("table", { className: "money history" },
          h("thead", {}, h("tr", {}, ["Data", "Serviço", "Profissional", "Valor", "Pagamento"].map((c) => h("th", {}, c)))),
          h("tbody", {}, appointments.map((a) => h("tr", {},
            h("td", {}, `${a.date.slice(8, 10)}/${a.date.slice(5, 7)}/${a.date.slice(0, 4)} ${a.start}`),
            h("td", {}, a.service_name), h("td", {}, a.professional_name),
            h("td", {}, formatMoney(a.price_cents)), h("td", {}, status(a))))))));
  }

  /** New client (name and phone), or a new name for one (the phone is her key and stays). */
  function clientDialog(client, onSaved) {
    const name = h("input", { id: "k-name", maxLength: 80, value: client?.name || "" });
    const phone = !client && h("input", { id: "k-phone", type: "tel", maxLength: 20, placeholder: "(11) 90000-0000" });
    const save = h("button", { className: "primary" }, "Salvar");
    const dialog = openDialog(client ? `Editar ${client.name}` : "Nova cliente",
      phone && [h("label", { htmlFor: "k-phone" }, "Telefone"), phone],
      h("label", { htmlFor: "k-name" }, "Nome"), name,
      h("div", { className: "actions" }, save, h("button", { className: "secondary", onclick: () => dialog.close() }, "Fechar")));
    save.addEventListener("click", () => whileDisabled(save, async () => {
      try {
        if (client) await api("PUT", `/clients/${client.phone}`, { name: name.value });
        else await api("POST", "/clients", { name: name.value, phone: phone.value });
        notify("Cliente salva.");
        dialog.close();
        onSaved();
      } catch (error) { notify(error.message, true); }
    }));
    (phone || name).focus();
  }

  list();
}
