import { CONFIG } from "./config.js";
import { signOut, token } from "./auth.js";
import { isOnline, recall, remember, setOnline } from "./offline.js";

const RETRY_MS = 5_000;                // offline: how often to check whether the connection is back

/** Calls the API with the login token. Throws an Error with the server's message (in Portuguese).
 *  Every GET answer is kept (offline.js): with no connection, a GET answers with what was already
 *  downloaded, and anything that changes data fails, since the screens block it anyway. */
export async function api(method, path, body, params) {
  const jwt = await token();
  if (!jwt) { location.reload(); throw new Error("Sessão expirada."); }
  let response;
  try {
    response = await fetch(urlOf(path, params), {
      method,
      headers: { Authorization: `Bearer ${jwt}`, ...(body ? { "Content-Type": "application/json" } : {}) },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    goneOffline();
    const kept = method === "GET" ? recall(path, params) : undefined;
    if (kept !== undefined) return kept;
    throw new Error(method === "GET" ? "Sem conexão com o servidor, e estes dados ainda não foram baixados."
      : "Sem conexão com o servidor.");
  }
  backOnline();
  if (response.status === 401 && !CONFIG.skipLogin) { signOut(); location.reload(); throw new Error("Sessão expirada."); }
  if (response.status === 204) return null;
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || "Algo deu errado. Tente de novo.");
  if (method === "GET") remember(path, params, data);
  return data;
}

function urlOf(path, params) {
  const url = new URL(CONFIG.apiUrl.replace(/\/$/, "") + path);
  for (const [k, v] of Object.entries(params || {})) url.searchParams.set(k, v);
  return url;
}

// ------------------------------------------------------------------ noticing the connection
// It drops when a request fails (or the browser says so); while it is down, a light request every few
// seconds checks whether it is back. Any answer from the server, even an error, means it is.
let retry = null;

function goneOffline() {
  setOnline(false);
  if (!retry) retry = setInterval(probe, RETRY_MS);
}

function backOnline() {
  clearInterval(retry);
  retry = null;
  setOnline(true);
}

async function probe() {
  try {
    const jwt = await token();
    await fetch(urlOf("/settings"), { headers: { Authorization: `Bearer ${jwt}` } });
    backOnline();
  } catch { /* still offline */ }
}

window.addEventListener("offline", goneOffline);
window.addEventListener("online", () => { if (!isOnline()) probe(); });
