// Configurações › Acessos (manager only): the logins to the app the manager created, creating a new
// one and removing one (someone who left the salon).
import { api } from "../api.js";
import { actionsMenu, h, notify, render } from "../util.js";
import { openAccessDialog } from "./access-dialog.js";
import { pagedList } from "./paged-list.js";

export async function mount(container) {
  async function draw() {
    let accesses, professionals;
    try { [accesses, professionals] = await Promise.all([api("GET", "/access"), api("GET", "/professionals")]); }
    catch (error) { return render(container, h("p", { className: "notice" }, error.message)); }
    const nameOf = Object.fromEntries(professionals.map((p) => [p.id, p.name]));
    const add = () => openAccessDialog({ onCreated: draw });
    const row = (a) => h("li", { className: "list-item" },
      h("div", { className: "list-main" },
        h("div", { className: "list-title" }, h("strong", {}, a.name, h("span", { className: "badge" }, a.manager ? "Gerente" : "Funcionária")),
          h("span", { className: "muted" }, a.email)),
        h("div", { className: "muted" }, a.professional_id ? `Atende clientes como ${nameOf[a.professional_id] || a.name}`
          : "Não atende clientes")),
      actionsMenu(a.name, [{ text: "Remover acesso", danger: true, onclick: () => remove(a) }]));
    render(container,
      h("div", { className: "row" }, h("h1", {}, "Acessos", accesses.length > 0 && h("span", { className: "count" }, ` (${accesses.length})`)),
        h("button", { className: "primary", onclick: add }, "Novo acesso")),
      h("p", { className: "muted" }, "Quem entra no sistema além da conta do salão. A gerente vê tudo; quem não é gerente vê a agenda "
        + "e os serviços e registra as próprias ausências (se atende clientes)."),
      accesses.length === 0 ? h("div", { className: "card empty-state" }, h("h2", {}, "Nenhum acesso criado"),
        h("p", { className: "muted" }, "Crie um acesso para cada profissional ou pessoa da equipe que vai usar o sistema."),
        h("button", { className: "primary", onclick: add }, "Novo acesso"))
        : pagedList(accesses, row, { label: "acessos" }));
  }

  /** Someone who left: the login stops working right away; her professional and appointments stay. */
  async function remove(access) {
    if (!confirm(`Remover o acesso de ${access.name} (${access.email})? Ela não consegue mais entrar no sistema. `
      + "A profissional e os agendamentos continuam.")) return;
    try {
      await api("DELETE", `/access/${access.id}`);
      notify("Acesso removido.");
      draw();
    } catch (error) { notify(error.message, true); }
  }

  draw();
}
