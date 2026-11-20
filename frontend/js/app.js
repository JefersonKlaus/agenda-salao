import { CONFIG } from "./config.js";
import { isManager, isSignedIn, setMe, setNewPassword, signIn, signOut } from "./auth.js";
import { api } from "./api.js";
import { h, notify, render, whileDisabled } from "./util.js";
import { isOnline, onConnectionChange } from "./offline.js";
import { mount as agenda } from "./screens/agenda.js";
import { mount as settings } from "./screens/settings.js";
import { mount as finance } from "./screens/finance.js";
import { mount as accesses } from "./screens/access.js";
import { professionals, services } from "./screens/catalog.js";

const content = document.getElementById("content");
// [name, mount, in the "Configurações" group at the bottom of the sidebar]
const SCREENS = [["Agenda", agenda], ["Serviços", services], ["Profissionais", professionals], ["Financeiro", finance],
  ["Funcionamento", settings, true], ["Acessos", accesses, true]];
const EMPLOYEE_SCREENS = new Set(["Agenda", "Serviços"]);        // the rest is the manager's (the API agrees)

function loginScreen(challenge = null) {
  const email = h("input", { id: "l-email", type: "email", autocomplete: "username", required: true, value: challenge?.email || "" });
  const password = h("input", { id: "l-password", type: "password", required: true,
    autocomplete: challenge ? "new-password" : "current-password" });
  const button = h("button", { className: "primary", type: "submit" }, challenge ? "Definir senha" : "Entrar");
  const form = h("form", { className: "card login" },
    h("h1", {}, "Agenda do Salão"),
    challenge && h("p", { className: "muted" }, "Primeiro acesso: escolha a sua senha (10+ caracteres, com maiúscula, minúscula e número)."),
    !challenge && [h("label", { htmlFor: "l-email" }, "E-mail"), email],
    h("label", { htmlFor: "l-password" }, challenge ? "Nova senha" : "Senha"), password,
    h("div", { className: "actions" }, button));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    whileDisabled(button, async () => {
      try {
        if (challenge) { await setNewPassword(challenge, password.value); return start(); }
        const r = await signIn(email.value.trim(), password.value);
        if (r.challenge) return loginScreen(r.challenge);
        start();
      } catch (error) { notify(error.message, true); }
    });
  });
  render(content, form);
  (challenge ? password : email).focus();
}

async function start() {
  // Who is logged in decides the menu. Unknown (no connection, nothing saved yet): the most restricted.
  try { setMe(await api("GET", "/me")); } catch { setMe({ manager: false, professional_id: null }); }
  const topBar = document.getElementById("top-bar");
  const sidebar = document.getElementById("sidebar");
  const backdrop = document.getElementById("backdrop");
  const toggle = document.getElementById("menu-toggle");
  const menu = document.getElementById("menu");
  const settingsMenu = document.getElementById("settings-menu");
  topBar.hidden = sidebar.hidden = false;
  document.body.classList.add("signed-in");

  // On phones the sidebar is a drawer: ☰ opens it; choosing a page, the backdrop or Esc closes it.
  const setDrawer = (open) => {
    sidebar.classList.toggle("open", open);
    backdrop.hidden = !open;
    toggle.setAttribute("aria-expanded", String(open));
    toggle.setAttribute("aria-label", open ? "Fechar menu" : "Abrir menu");
    if (open) sidebar.querySelector("nav [aria-current]")?.focus();
  };
  toggle.onclick = () => setDrawer(!sidebar.classList.contains("open"));
  backdrop.onclick = () => setDrawer(false);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && sidebar.classList.contains("open")) { setDrawer(false); toggle.focus(); }
  });

  // An employee sees the agenda and the services; everything else is the manager's.
  const screens = SCREENS.filter(([name]) => isManager() || EMPLOYEE_SCREENS.has(name));
  let current = 0;
  const buttons = screens.map(([name], i) => h("button", { onclick: () => open(i) }, name));
  const open = (index) => {
    current = index;
    buttons.forEach((b, i) => (i === index ? b.setAttribute("aria-current", "page") : b.removeAttribute("aria-current")));
    setDrawer(false);
    const area = h("div");
    render(content, area);
    screens[index][1](area);
  };
  render(menu, buttons.filter((_, i) => !screens[i][2]));
  render(settingsMenu, buttons.filter((_, i) => screens[i][2]));
  document.getElementById("settings-group").hidden = settingsMenu.children.length === 0;

  // No connection: only the agenda works, with what was already downloaded; every other page is
  // blocked until it comes back (the agenda blocks its own changes). A banner says so.
  const banner = h("div", { id: "offline-banner", role: "status", hidden: true },
    "Sem conexão com a internet. A agenda mostra o que já foi baixado; nada pode ser alterado até a conexão voltar.");
  document.querySelector(".layout").before(banner);       // above the sidebar and the page, full width
  const showConnection = (online) => {
    banner.hidden = online;
    buttons.forEach((button, i) => { button.disabled = !online && i !== 0; });
  };
  onConnectionChange((online) => {
    showConnection(online);
    if (!online && current !== 0) open(0);
    if (online) { notify("Conexão de volta."); open(current); }   // reloads the page with fresh data
  });
  showConnection(isOnline());      // opened already offline: /me above had failed before anyone listened
  const logout = document.getElementById("logout");
  if (CONFIG.skipLogin) {                        // local server: there is nobody to log out
    logout.replaceWith(h("span", { id: "local-mode", className: "muted" },
      `Modo local, sem login (${isManager() ? "gerente" : "funcionária"})`));
  } else logout.onclick = () => { signOut(); location.reload(); };
  open(0);
}

if (!CONFIG.apiUrl || (!CONFIG.clientId && !CONFIG.skipLogin)) {
  render(content, h("p", { className: "notice" }, "Sistema ainda não configurado (js/config.js vazio)."));
} else if (isSignedIn()) start();
else loginScreen();
