// Creating a login to the app (manager only). Two ways in, one dialog:
// - Acessos: e-mail, name, manager or not, and "É prestadora de serviço?", which starts her
//   professional (with no services and no days yet, to configure in Profissionais);
// - Profissionais: e-mail and manager or not, for a professional who has no login yet.
import { api } from "../api.js";
import { h, notify, openDialog, whileDisabled } from "../util.js";

export function openAccessDialog({ professional = null, onCreated }) {
  const email = h("input", { id: "x-email", type: "email", autocomplete: "off", maxLength: 120 });
  const name = !professional && h("input", { id: "x-name", maxLength: 80 });
  const provider = !professional && h("input", { id: "x-provider", type: "checkbox", checked: true });
  const manager = h("input", { id: "x-manager", type: "checkbox" });
  const save = h("button", { className: "primary" }, "Criar acesso");
  const dialog = openDialog(professional ? `Acesso para ${professional.name}` : "Novo acesso",
    h("p", { className: "muted" }, "A pessoa recebe por e-mail uma senha temporária e escolhe a dela no primeiro acesso."),
    h("label", { htmlFor: "x-email" }, "E-mail"), email,
    name && [h("label", { htmlFor: "x-name" }, "Nome"), name],
    provider && [h("label", { className: "choice" }, provider, "É prestadora de serviço (atende clientes)"),
      h("p", { className: "muted" }, "Já cria a profissional, sem serviços nem dias: configure depois em Profissionais.")],
    h("label", { className: "choice" }, manager, "Gerente (acesso a tudo)"),
    h("p", { className: "muted" }, "Sem marcar: vê a agenda e os serviços, e registra as próprias ausências."),
    h("div", { className: "actions" }, save, h("button", { className: "secondary", onclick: () => dialog.close() }, "Fechar")));

  save.addEventListener("click", () => whileDisabled(save, async () => {
    try {
      const body = professional ? { email: email.value, professional_id: professional.id, manager: manager.checked }
        : { email: email.value, name: name.value, provider: provider.checked, manager: manager.checked };
      const access = await api("POST", "/access", body);
      notify(access.professional_id && !professional
        ? `Acesso criado. Configure os serviços e os dias de ${access.name} em Profissionais.` : "Acesso criado.");
      dialog.close();
      onCreated(access);
    } catch (error) { notify(error.message, true); }
  }));
  email.focus();
}
