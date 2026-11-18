// Login no Cognito direto pela API pública (sem biblioteca). Os tokens ficam só na sessão da aba.
import { CONFIG } from "./config.js";

const CHAVE = "agenda.tokens";
const MENSAGENS = {
  NotAuthorizedException: "E-mail ou senha incorretos.",
  UserNotFoundException: "E-mail ou senha incorretos.",
  InvalidPasswordException: "A senha precisa ter 10 caracteres, com maiúscula, minúscula e número.",
  TooManyRequestsException: "Muitas tentativas. Espere um pouco.",
  LimitExceededException: "Muitas tentativas. Espere um pouco.",
};

// `cognitoUrl` só existe no servidor de teste local (e2e/servidor_local.py); na AWS usa o endereço real.
const URL_COGNITO = CONFIG.cognitoUrl || `https://cognito-idp.${CONFIG.regiao}.amazonaws.com/`;

async function cognito(alvo, corpo) {
  const resposta = await fetch(URL_COGNITO, {
    method: "POST",
    headers: { "Content-Type": "application/x-amz-json-1.1", "X-Amz-Target": `AWSCognitoIdentityProviderService.${alvo}` },
    body: JSON.stringify({ ClientId: CONFIG.clienteId, ...corpo }),
  });
  const dados = await resposta.json().catch(() => ({}));
  if (!resposta.ok) {
    const tipo = String(dados.__type || "").split("#").pop();
    throw new Error(MENSAGENS[tipo] || "Não foi possível entrar. Tente de novo.");
  }
  return dados;
}

function guardar(resultado, anterior = {}) {
  const t = { ...anterior, idToken: resultado.IdToken, expira: Date.now() + resultado.ExpiresIn * 1000 };
  if (resultado.RefreshToken) t.refresh = resultado.RefreshToken;
  try { sessionStorage.setItem(CHAVE, JSON.stringify(t)); } catch { /* modo privado: fica só em memória */ }
  memoria = t;
}

let memoria = null;
function ler() {
  if (memoria) return memoria;
  try { memoria = JSON.parse(sessionStorage.getItem(CHAVE)); } catch { memoria = null; }
  return memoria;
}

/** Devolve {desafio} se o Cognito pedir senha nova (primeiro acesso), senão guarda os tokens. */
export async function entrar(email, senha) {
  const r = await cognito("InitiateAuth", {
    AuthFlow: "USER_PASSWORD_AUTH", AuthParameters: { USERNAME: email, PASSWORD: senha } });
  if (r.ChallengeName === "NEW_PASSWORD_REQUIRED") return { desafio: { sessao: r.Session, email } };
  guardar(r.AuthenticationResult);
  return {};
}

export async function definirSenhaNova({ sessao, email }, senha) {
  const r = await cognito("RespondToAuthChallenge", {
    ChallengeName: "NEW_PASSWORD_REQUIRED", Session: sessao,
    ChallengeResponses: { USERNAME: email, NEW_PASSWORD: senha } });
  guardar(r.AuthenticationResult);
}

export const logado = () => Boolean(ler()?.idToken);

export function sair() {
  memoria = null;
  try { sessionStorage.removeItem(CHAVE); } catch { /* sem armazenamento */ }
}

/** Token válido para a API. Renova sozinho quando falta menos de 1 minuto. */
export async function token() {
  const t = ler();
  if (!t) return null;
  if (Date.now() < t.expira - 60_000) return t.idToken;
  if (!t.refresh) { sair(); return null; }
  try {
    const r = await cognito("InitiateAuth", { AuthFlow: "REFRESH_TOKEN_AUTH", AuthParameters: { REFRESH_TOKEN: t.refresh } });
    guardar(r.AuthenticationResult, t);
    return ler().idToken;
  } catch { sair(); return null; }
}
