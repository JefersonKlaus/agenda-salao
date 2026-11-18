import { CONFIG } from "./config.js";
import { sair, token } from "./auth.js";

/** Chama a API com o token de login. Lança Error com a mensagem do servidor em português. */
export async function api(metodo, caminho, corpo, parametros) {
  const jwt = await token();
  if (!jwt) { location.reload(); throw new Error("Sessão expirada."); }
  const url = new URL(CONFIG.apiUrl.replace(/\/$/, "") + caminho);
  for (const [k, v] of Object.entries(parametros || {})) url.searchParams.set(k, v);
  let resposta;
  try {
    resposta = await fetch(url, {
      method: metodo,
      headers: { Authorization: `Bearer ${jwt}`, ...(corpo ? { "Content-Type": "application/json" } : {}) },
      body: corpo ? JSON.stringify(corpo) : undefined,
    });
  } catch { throw new Error("Sem conexão com o servidor."); }
  if (resposta.status === 401) { sair(); location.reload(); throw new Error("Sessão expirada."); }
  if (resposta.status === 204) return null;
  const dados = await resposta.json().catch(() => ({}));
  if (!resposta.ok) throw new Error(dados.erro || "Algo deu errado. Tente de novo.");
  return dados;
}
