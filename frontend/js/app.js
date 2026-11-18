import { CONFIG } from "./config.js";
import { definirSenhaNova, entrar, logado, sair } from "./auth.js";
import { aviso, h, mostrar, travar } from "./util.js";
import { montar as agenda } from "./telas/agenda.js";
import { montar as configuracao } from "./telas/configuracao.js";
import { profissionais, servicos } from "./telas/cadastros.js";

const conteudo = document.getElementById("conteudo");
const TELAS = [["Agenda", agenda], ["Serviços", servicos], ["Profissionais", profissionais], ["Horários", configuracao]];

function telaLogin(desafio = null) {
  const email = h("input", { id: "l-email", type: "email", autocomplete: "username", required: true, value: desafio?.email || "" });
  const senha = h("input", { id: "l-senha", type: "password", required: true,
    autocomplete: desafio ? "new-password" : "current-password" });
  const botao = h("button", { className: "primario", type: "submit" }, desafio ? "Definir senha" : "Entrar");
  const form = h("form", { className: "cartao login" },
    h("h1", {}, "Agenda do Salão"),
    desafio && h("p", { className: "suave" }, "Primeiro acesso: escolha a sua senha (10+ caracteres, com maiúscula, minúscula e número)."),
    !desafio && [h("label", { htmlFor: "l-email" }, "E-mail"), email],
    h("label", { htmlFor: "l-senha" }, desafio ? "Nova senha" : "Senha"), senha,
    h("div", { className: "acoes" }, botao));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    travar(botao, async () => {
      try {
        if (desafio) { await definirSenhaNova(desafio, senha.value); return iniciar(); }
        const r = await entrar(email.value.trim(), senha.value);
        if (r.desafio) return telaLogin(r.desafio);
        iniciar();
      } catch (erro) { aviso(erro.message, true); }
    });
  });
  mostrar(conteudo, form);
  (desafio ? senha : email).focus();
}

function iniciar() {
  const topo = document.getElementById("topo");
  const menu = document.getElementById("menu");
  topo.hidden = false;
  const abrir = (indice) => {
    [...menu.children].forEach((b, i) => (i === indice ? b.setAttribute("aria-current", "page") : b.removeAttribute("aria-current")));
    const area = h("div");
    mostrar(conteudo, area);
    TELAS[indice][1](area);
  };
  mostrar(menu, TELAS.map(([nome], i) => h("button", { onclick: () => abrir(i) }, nome)));
  document.getElementById("sair").onclick = () => { sair(); location.reload(); };
  abrir(0);
}

if (!CONFIG.apiUrl || !CONFIG.clienteId) {
  mostrar(conteudo, h("p", { className: "aviso" }, "Sistema ainda não configurado (js/config.js vazio)."));
} else if (logado()) iniciar();
else telaLogin();
