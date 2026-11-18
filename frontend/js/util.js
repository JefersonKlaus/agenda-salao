// Ajudantes pequenos. O texto vindo do usuário SEMPRE entra como texto (nunca como HTML).

export function h(tag, props = {}, ...filhos) {
  const el = document.createElement(tag);
  for (const [chave, valor] of Object.entries(props)) {
    if (valor === false || valor == null) continue;
    if (chave.startsWith("on")) el.addEventListener(chave.slice(2), valor);
    else if (chave in el && chave !== "list") el[chave] = valor;
    else el.setAttribute(chave, valor === true ? "" : valor);
  }
  for (const filho of filhos.flat(Infinity)) {
    if (filho == null || filho === false) continue;
    el.append(filho instanceof Node ? filho : document.createTextNode(String(filho)));
  }
  return el;
}

export function mostrar(container, ...filhos) {
  container.replaceChildren(...filhos.flat(Infinity).filter(Boolean));
}

export function aviso(texto, erro = false) {
  const el = h("div", { className: "toast" + (erro ? " erro" : "") }, texto);
  document.getElementById("avisos").append(el);
  setTimeout(() => el.remove(), erro ? 6000 : 3000);
}

export const moeda = (centavos) =>
  (centavos / 100).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });

/** "80,50" ou "1.200" -> centavos inteiros. Devolve null se não for um valor. */
export function paraCentavos(texto) {
  const limpo = String(texto).trim().replace(/\s/g, "").replace("R$", "");
  if (!/^\d{1,3}(\.\d{3})*(,\d{1,2})?$|^\d+(,\d{1,2})?$/.test(limpo)) return null;
  const [reais, centavos = ""] = limpo.replace(/\./g, "").split(",");
  return Number(reais) * 100 + Number(centavos.padEnd(2, "0"));
}

export function hoje() {
  const d = new Date();
  return [d.getFullYear(), String(d.getMonth() + 1).padStart(2, "0"), String(d.getDate()).padStart(2, "0")].join("-");
}

export function somarDias(iso, dias) {
  const [a, m, d] = iso.split("-").map(Number);
  const nova = new Date(a, m - 1, d + dias);
  return [nova.getFullYear(), String(nova.getMonth() + 1).padStart(2, "0"), String(nova.getDate()).padStart(2, "0")].join("-");
}

export function dataBonita(iso) {
  const [a, m, d] = iso.split("-").map(Number);
  const texto = new Date(a, m - 1, d).toLocaleDateString("pt-BR", { weekday: "long", day: "2-digit", month: "long" });
  return texto.charAt(0).toUpperCase() + texto.slice(1);
}

export function somarMinutos(hora, minutos) {
  const [h_, m] = hora.split(":").map(Number);
  const total = h_ * 60 + m + minutos;
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

export const duracaoTexto = (min) => (min >= 60 ? `${Math.floor(min / 60)} h` : "") + (min % 60 ? ` ${min % 60} min` : "");

/** Roda uma ação com o botão travado, para não enviar duas vezes com cliques repetidos. */
export async function travar(botao, acao) {
  botao.disabled = true;
  try { return await acao(); } finally { botao.disabled = false; }
}
