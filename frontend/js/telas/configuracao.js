import { api } from "../api.js";
import { aviso, h, mostrar, travar } from "../util.js";

const DIAS = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"];

export async function montar(container) {
  let config;
  try { config = await api("GET", "/configuracao"); }
  catch (erro) { return mostrar(container, h("p", { className: "aviso" }, erro.message)); }

  const dias = DIAS.map((_, i) => h("input", { type: "checkbox", checked: config.dias_abertos.includes(i) }));
  const abre = h("input", { id: "k-abre", type: "time", step: 900, value: config.abre });
  const fecha = h("input", { id: "k-fecha", type: "time", step: 900, value: config.fecha });
  const salvar = h("button", { className: "primario" }, "Salvar");

  salvar.addEventListener("click", () => travar(salvar, async () => {
    try {
      await api("PUT", "/configuracao", {
        dias_abertos: dias.flatMap((c, i) => (c.checked ? [i] : [])), abre: abre.value, fecha: fecha.value });
      aviso("Horário de funcionamento salvo.");
    } catch (erro) { aviso(erro.message, true); }
  }));

  mostrar(container, h("div", { className: "cartao" },
    h("h1", {}, "Horário de funcionamento"),
    h("label", {}, "Dias em que o salão abre"),
    DIAS.map((nome, i) => h("label", { className: "opcao" }, dias[i], nome)),
    h("label", { htmlFor: "k-abre" }, "Abre às"), abre,
    h("label", { htmlFor: "k-fecha" }, "Fecha às"), fecha,
    h("p", { className: "suave" }, "Os horários livres seguem de 15 em 15 minutos dentro deste intervalo."),
    h("div", { className: "acoes" }, salvar)));
}
