// Cognito login straight through its public API (no library). Tokens live only in the tab's session.
// CONFIG.skipLogin is only ever set by local/server.py: there is no login and the local server
// answers every request as the same salon. The deployed API still requires a valid token for everything.
import { CONFIG } from "./config.js";
import { forgetDownloads } from "./offline.js";

const STORAGE_KEY = "agenda.tokens";
const MESSAGES = {
  NotAuthorizedException: "E-mail ou senha incorretos.",
  UserNotFoundException: "E-mail ou senha incorretos.",
  InvalidPasswordException: "A senha precisa ter 10 caracteres, com maiúscula, minúscula e número.",
  TooManyRequestsException: "Muitas tentativas. Espere um pouco.",
  LimitExceededException: "Muitas tentativas. Espere um pouco.",
};

async function cognito(target, body) {
  const response = await fetch(`https://cognito-idp.${CONFIG.region}.amazonaws.com/`, {
    method: "POST",
    headers: { "Content-Type": "application/x-amz-json-1.1", "X-Amz-Target": `AWSCognitoIdentityProviderService.${target}` },
    body: JSON.stringify({ ClientId: CONFIG.clientId, ...body }),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const type = String(data.__type || "").split("#").pop();
    throw new Error(MESSAGES[type] || "Não foi possível entrar. Tente de novo.");
  }
  return data;
}

function store(result, previous = {}) {
  const t = { ...previous, idToken: result.IdToken, expiresAt: Date.now() + result.ExpiresIn * 1000 };
  if (result.RefreshToken) t.refresh = result.RefreshToken;
  try { sessionStorage.setItem(STORAGE_KEY, JSON.stringify(t)); } catch { /* private mode: kept in memory only */ }
  cached = t;
}

let cached = null;
function load() {
  if (cached) return cached;
  try { cached = JSON.parse(sessionStorage.getItem(STORAGE_KEY)); } catch { cached = null; }
  return cached;
}

/** Returns {challenge} if Cognito asks for a new password (first access), otherwise stores the tokens. */
export async function signIn(email, password) {
  const r = await cognito("InitiateAuth", {
    AuthFlow: "USER_PASSWORD_AUTH", AuthParameters: { USERNAME: email, PASSWORD: password } });
  if (r.ChallengeName === "NEW_PASSWORD_REQUIRED") return { challenge: { session: r.Session, email } };
  store(r.AuthenticationResult);
  return {};
}

export async function setNewPassword({ session, email }, password) {
  const r = await cognito("RespondToAuthChallenge", {
    ChallengeName: "NEW_PASSWORD_REQUIRED", Session: session,
    ChallengeResponses: { USERNAME: email, NEW_PASSWORD: password } });
  store(r.AuthenticationResult);
}

export const isSignedIn = () => Boolean(CONFIG.skipLogin || load()?.idToken);

// Who is logged in, as the API says (GET /me, set by app.js when it starts). It only decides what the
// screen shows: the API checks the token again on every request. Until then (or if unknown), the most
// restricted: not the manager, no professional.
let me = { manager: false, professional_id: null };
export const setMe = (answer) => { me = answer; };
export const isManager = () => me.manager;
/** Her professional's id when the login is a service provider; null otherwise. */
export const myProfessionalId = () => me.professional_id;

export function signOut() {
  cached = null;
  forgetDownloads();                             // the salon's data does not stay on the device
  try { sessionStorage.removeItem(STORAGE_KEY); } catch { /* no storage */ }
}

/** A valid token for the API. Refreshes it automatically when less than 1 minute is left. */
export async function token() {
  if (CONFIG.skipLogin) return "local";          // ignored by the local server
  const t = load();
  if (!t) return null;
  if (Date.now() < t.expiresAt - 60_000) return t.idToken;
  if (!t.refresh) { signOut(); return null; }
  try {
    const r = await cognito("InitiateAuth", { AuthFlow: "REFRESH_TOKEN_AUTH", AuthParameters: { REFRESH_TOKEN: t.refresh } });
    store(r.AuthenticationResult, t);
    return load().idToken;
  } catch (error) {
    // No connection (fetch fails with a TypeError): keep the login, the agenda shows what was downloaded
    // and the token is renewed once the connection is back. Any other failure: the login is over.
    if (error instanceof TypeError) return t.idToken;
    signOut();
    return null;
  }
}
