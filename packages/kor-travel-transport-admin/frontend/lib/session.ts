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
  if (!value || !loginIsConfigured()) return false;
  const [encodedPayload, encodedSignature, ...extra] = value.split(".");
  if (!encodedPayload || !encodedSignature || extra.length) return false;
  try {
    const valid = await crypto.subtle.verify("HMAC", await signingKey(sessionSecret()), base64UrlDecode(encodedSignature), encoder.encode(encodedPayload));
    if (!valid) return false;
    const payload = JSON.parse(decoder.decode(base64UrlDecode(encodedPayload))) as SessionPayload;
    return payload.user === adminUsername() && Number.isFinite(payload.exp) && payload.exp > Math.floor(Date.now() / 1000);
  } catch {
    return false;
  }
}
