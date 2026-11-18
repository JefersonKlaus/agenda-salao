import { api } from "../api.js";
import { aviso, dataBonita, duracaoTexto, h, hoje, moeda, mostrar, somarDias, somarMinutos, travar } from "../util.js";

export async function montar(container) {
  let data = hoje();
  let formAberto = false;

  async function desenhar() {
    mostrar(container, h("p", { className: "aviso" }, "Carregando…"));
    let agendamentos, servicos, profissionais;
    try {
      [agendamentos, servicos, profissionais] = await Promise.all([
        api("GET", "/agendamentos", null, { data }), api("GET", "/servicos"), api("GET", "/profissionais")]);
    } catch (erro) { return mostrar(container, h("p", { className: "aviso" }, erro.message)); }

    const navegar = (dias) => () => { data = somarDias(data, dias); formAberto = false; desenhar(); };
    mostrar(container,
      h("div", { className: "linha" },
        h("button", { className: "secundario", onclick: navegar(-1), "aria-label": "Dia anterior" }, "◀"),
        h("h1", { style: "margin:0" }, dataBonita(data)),
        h("button", { className: "secundario", onclick: navegar(1), "aria-label": "Próximo dia" }, "▶")),
      h("div", { className: "acoes" },
        h("button", { className: "primario", onclick: () => { formAberto = !formAberto; desenhar(); } },
          formAberto ? "Fechar" : "Novo agendamento"),
        data !== hoje() && h("button", { className: "secundario", onclick: () => { data = hoje(); desenhar(); } }, "Hoje")),
      formAberto && formulario(servicos, profissionais),
      h("h2", { style: "margin-top:20px" }, `${agendamentos.length} agendamento(s)`),
      agendamentos.length === 0 && h("p", { className: "aviso" }, "Nenhum agendamento neste dia."),
      agendamentos.map(cartao));
  }

  function cartao(ag) {
    const cancelar = (evento) => {
      if (!confirm(`Cancelar o horário de ${ag.cliente_nome} às ${ag.inicio}?`)) return;
      travar(evento.target, async () => {
        try { await api("DELETE", `/agendamentos/${ag.id}`); aviso("Agendamento cancelado."); desenhar(); }
        catch (erro) { aviso(erro.message, true); }
      });
    };
    return h("div", { className: "cartao" },
      h("div", { className: "linha" },
        h("strong", {}, `${ag.inicio} – ${somarMinutos(ag.inicio, ag.duracao_min)}`),
        h("span", { className: "suave" }, moeda(ag.preco_centavos))),
      h("div", {}, `${ag.cliente_nome} · ${ag.servico_nome} com ${ag.profissional_nome}`),
      ag.cliente_telefone && h("div", { className: "suave" }, ag.cliente_telefone),
      h("div", { className: "acoes" }, h("button", { className: "perigo", onclick: cancelar }, "Cancelar")));
  }

  function formulario(servicos, profissionais) {
    const estado = { servico: null, profissional: null, hora: null };
    const selServico = h("select", { id: "f-servico" },
      h("option", { value: "" }, "Escolha o serviço"),
      servicos.map((s) => h("option", { value: s.id }, `${s.nome} (${duracaoTexto(s.duracao_min)})`)));
    const selProf = h("select", { id: "f-prof", disabled: true }, h("option", { value: "" }, "Escolha o serviço primeiro"));
    const grade = h("div", { className: "horarios" });
    const nome = h("input", { id: "f-nome", maxLength: 80, autocomplete: "off" });
    const telefone = h("input", { id: "f-tel", type: "tel", maxLength: 20, placeholder: "(11) 90000-0000" });
    const salvar = h("button", { className: "primario", disabled: true }, "Agendar");

    const atualizarBotao = () => { salvar.disabled = !(estado.hora && nome.value.trim()); };

    async function carregarHorarios() {
      estado.hora = null;
      atualizarBotao();
      if (!estado.servico || !estado.profissional) return mostrar(grade);
      mostrar(grade, h("span", { className: "suave" }, "Buscando horários…"));
      try {
        const horas = await api("GET", "/disponibilidade", null,
          { data, servico_id: estado.servico, profissional_id: estado.profissional });
        mostrar(grade, horas.length ? horas.map((hora) => h("button", {
          type: "button", "aria-pressed": "false",
          onclick: (e) => {
            estado.hora = hora;
            grade.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b === e.target)));
            atualizarBotao();
          } }, hora)) : h("span", { className: "suave" }, "Sem horários livres neste dia."));
      } catch (erro) { mostrar(grade, h("span", { className: "suave" }, erro.message)); }
    }

    selServico.addEventListener("change", () => {
      estado.servico = selServico.value || null;
      estado.profissional = null;
      const quem = profissionais.filter((p) => p.servicos.includes(estado.servico));
      selProf.disabled = !estado.servico;
      mostrar(selProf, h("option", { value: "" }, quem.length ? "Escolha a profissional" : "Ninguém faz este serviço"),
        quem.map((p) => h("option", { value: p.id }, p.nome)));
      carregarHorarios();
    });
    selProf.addEventListener("change", () => { estado.profissional = selProf.value || null; carregarHorarios(); });
    nome.addEventListener("input", atualizarBotao);

    salvar.addEventListener("click", () => travar(salvar, async () => {
      try {
        await api("POST", "/agendamentos", { data, inicio: estado.hora, servico_id: estado.servico,
          profissional_id: estado.profissional, cliente_nome: nome.value, cliente_telefone: telefone.value });
        aviso("Agendado!");
        formAberto = false;
        desenhar();
      } catch (erro) { aviso(erro.message, true); carregarHorarios(); }   // outro horário pode ter sido tomado
    }));

    return h("div", { className: "cartao", style: "margin-top:12px" },
      h("label", { htmlFor: "f-servico" }, "Serviço"), selServico,
      h("label", { htmlFor: "f-prof" }, "Profissional"), selProf,
      h("label", {}, "Horário"), grade,
      h("label", { htmlFor: "f-nome" }, "Nome da cliente"), nome,
      h("label", { htmlFor: "f-tel" }, "Telefone (opcional)"), telefone,
      h("div", { className: "acoes" }, salvar));
  }

  desenhar();
}
