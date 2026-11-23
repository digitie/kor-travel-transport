const encoder = new TextEncoder();
const decoder = new TextDecoder();

export const SESSION_COOKIE = "kor_travel_transport_admin_session";
export const SESSION_MAX_AGE = 60 * 60 * 8;

type SessionPayload = { exp: number; user: string };

function base64UrlEncode(bytes: Uint8Array) {
  return btoa(String.fromCharCode(...bytes)).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}

function base64UrlDecode(value: string) {
  const padded = value.replaceAll("-", "+").replaceAll("_", "/") + "=".repeat((4 - (value.length % 4)) % 4);
  return Uint8Array.from(atob(padded), (character) => character.charCodeAt(0));
}

async function signingKey(secret: string) {
  return crypto.subtle.importKey("raw", encoder.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign", "verify"]);
}

export function adminUsername() {
  return process.env.TRANSPORT_UI_USER?.trim() || "admin";
}

export function configuredPassword() {
  return process.env.TRANSPORT_UI_PASSWORD ?? "";
}

export function sessionSecret() {
  return process.env.TRANSPORT_UI_SESSION_SECRET ?? "";
}

export function loginIsConfigured() {
  const secret = sessionSecret();
  return Boolean(configuredPassword()) && (process.env.NODE_ENV !== "production" || secret.length >= 32);
}

export async function createSessionValue(user: string) {
  const payload: SessionPayload = { user, exp: Math.floor(Date.now() / 1000) + SESSION_MAX_AGE };
  const encodedPayload = base64UrlEncode(encoder.encode(JSON.stringify(payload)));
  const signature = await crypto.subtle.sign("HMAC", await signingKey(sessionSecret()), encoder.encode(encodedPayload));
  return `${encodedPayload}.${base64UrlEncode(new Uint8Array(signature))}`;
}

export async function verifySessionValue(value: string | undefined) {
  return (await verifiedSessionUser(value)) !== null;
}

/** 서명·만료를 검증한 세션의 사용자 이름. 감사 기록(요청자)에만 쓰며 검증 실패는 null이다. */
export async function verifiedSessionUser(value: string | undefined): Promise<string | null> {
  if (!value || !loginIsConfigured()) return null;
  const [encodedPayload, encodedSignature, ...extra] = value.split(".");
  if (!encodedPayload || !encodedSignature || extra.length) return null;
  try {
    const valid = await crypto.subtle.verify("HMAC", await signingKey(sessionSecret()), base64UrlDecode(encodedSignature), encoder.encode(encodedPayload));
    if (!valid) return null;
    const payload = JSON.parse(decoder.decode(base64UrlDecode(encodedPayload))) as SessionPayload;
    const current = payload.user === adminUsername() && Number.isFinite(payload.exp) && payload.exp > Math.floor(Date.now() / 1000);
    return current ? payload.user : null;
  } catch {
    return null;
  }
}
