// Serviços e profissionais: a mesma lista com formulário, mudando só os campos.
import { api } from "../api.js";
import { aviso, duracaoTexto, h, moeda, mostrar, paraCentavos, travar } from "../util.js";

const DURACOES = Array.from({ length: 32 }, (_, i) => (i + 1) * 15);

function camposServico(item = {}) {
  const nome = h("input", { id: "c-nome", value: item.nome || "", maxLength: 80 });
  const duracao = h("select", { id: "c-dur" }, DURACOES.map((m) =>
    h("option", { value: m, selected: m === (item.duracao_min || 60) }, duracaoTexto(m))));
  const preco = h("input", { id: "c-preco", inputMode: "decimal", placeholder: "80,00",
    value: item.preco_centavos != null ? (item.preco_centavos / 100).toFixed(2).replace(".", ",") : "" });
  return {
    nos: [h("label", { htmlFor: "c-nome" }, "Nome"), nome, h("label", { htmlFor: "c-dur" }, "Duração"), duracao,
      h("label", { htmlFor: "c-preco" }, "Preço (R$)"), preco],
    ler() {
      const centavos = paraCentavos(preco.value);
      if (centavos === null) throw new Error("Preço inválido. Use algo como 80,00.");
      return { nome: nome.value, duracao_min: Number(duracao.value), preco_centavos: centavos };
    },
  };
}

function camposProfissional(item = {}, servicos = []) {
  const nome = h("input", { id: "c-nome", value: item.nome || "", maxLength: 80 });
  const caixas = servicos.map((s) => h("input", { type: "checkbox", value: s.id,
    checked: (item.servicos || []).includes(s.id) }));
  return {
    nos: [h("label", { htmlFor: "c-nome" }, "Nome"), nome, h("label", {}, "Serviços que ela faz"),
      servicos.length === 0 && h("p", { className: "suave" }, "Cadastre os serviços primeiro."),
      servicos.map((s, i) => h("label", { className: "opcao" }, caixas[i], s.nome))],
    ler: () => ({ nome: nome.value, servicos: caixas.filter((c) => c.checked).map((c) => c.value) }),
  };
}

export function criarTela({ rota, titulo, vazio, resumo }) {
  return async function montar(container) {
    let editando = null;                       // null = lista, {} = novo, objeto = editar

    async function desenhar() {
      let itens, servicos = [];
      try {
        itens = await api("GET", `/${rota}`);
        if (rota === "profissionais") servicos = await api("GET", "/servicos");
      } catch (erro) { return mostrar(container, h("p", { className: "aviso" }, erro.message)); }
      mostrar(container, editando ? formulario(servicos) : lista(itens, servicos));
    }

    function lista(itens, servicos) {
      const nomes = Object.fromEntries(servicos.map((s) => [s.id, s.nome]));
      return [
        h("div", { className: "linha" }, h("h1", {}, titulo),
          h("button", { className: "primario", onclick: () => { editando = {}; desenhar(); } }, "Adicionar")),
        itens.length === 0 && h("p", { className: "aviso" }, vazio),
        itens.map((item) => h("div", { className: "cartao" },
          h("div", { className: "linha" }, h("strong", {}, item.nome),
            h("span", { className: "suave" }, resumo(item, nomes))),
          h("div", { className: "acoes" },
            h("button", { className: "secundario", onclick: () => { editando = item; desenhar(); } }, "Editar"),
            h("button", { className: "perigo", onclick: (e) => remover(e.target, item) }, "Excluir")))),
      ];
    }

    function formulario(servicos) {
      const campos = rota === "servicos" ? camposServico(editando) : camposProfissional(editando, servicos);
      const salvar = h("button", { className: "primario" }, "Salvar");
      salvar.addEventListener("click", () => travar(salvar, async () => {
        try {
          const corpo = campos.ler();
          if (editando.id) await api("PUT", `/${rota}/${editando.id}`, corpo);
          else await api("POST", `/${rota}`, corpo);
          aviso("Salvo!");
          editando = null;
          desenhar();
        } catch (erro) { aviso(erro.message, true); }
      }));
      return h("div", { className: "cartao" }, h("h1", {}, editando.id ? "Editar" : "Novo"), campos.nos,
        h("div", { className: "acoes" }, salvar,
          h("button", { className: "secundario", onclick: () => { editando = null; desenhar(); } }, "Voltar")));
    }

    function remover(botao, item) {
      if (!confirm(`Excluir "${item.nome}"? Os agendamentos já feitos continuam na agenda.`)) return;
      travar(botao, async () => {
        try { await api("DELETE", `/${rota}/${item.id}`); aviso("Excluído."); desenhar(); }
        catch (erro) { aviso(erro.message, true); }
      });
    }

    desenhar();
  };
}

export const servicos = criarTela({ rota: "servicos", titulo: "Serviços", vazio: "Nenhum serviço ainda.",
  resumo: (s) => `${duracaoTexto(s.duracao_min)} · ${moeda(s.preco_centavos)}` });

export const profissionais = criarTela({ rota: "profissionais", titulo: "Profissionais", vazio: "Nenhuma profissional ainda.",
  resumo: (p, nomes) => p.servicos.map((id) => nomes[id]).filter(Boolean).join(", ") || "sem serviços" });
