import { CONFIG } from "./config.js";
import { signOut, token } from "./auth.js";

/** Calls the API with the login token. Throws an Error with the server's message (in Portuguese). */
export async function api(method, path, body, params) {
  const jwt = await token();
  if (!jwt) { location.reload(); throw new Error("Sessão expirada."); }
  const url = new URL(CONFIG.apiUrl.replace(/\/$/, "") + path);
  for (const [k, v] of Object.entries(params || {})) url.searchParams.set(k, v);
  let response;
  try {
    response = await fetch(url, {
      method,
      headers: { Authorization: `Bearer ${jwt}`, ...(body ? { "Content-Type": "application/json" } : {}) },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch { throw new Error("Sem conexão com o servidor."); }
  if (response.status === 401 && !CONFIG.skipLogin) { signOut(); location.reload(); throw new Error("Sessão expirada."); }
  if (response.status === 204) return null;
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || "Algo deu errado. Tente de novo.");
  return data;
}
