const WINDOW_MS = 10 * 60 * 1000;
const MAX_ATTEMPTS = 5;
const attempts = new Map<string, { count: number; resetAt: number }>();

export function loginRateLimited(key: string, now = Date.now()) {
  const current = attempts.get(key);
  if (!current || current.resetAt <= now) return false;
  return current.count >= MAX_ATTEMPTS;
}

export function recordFailedLogin(key: string, now = Date.now()) {
  const current = attempts.get(key);
  if (!current || current.resetAt <= now) attempts.set(key, { count: 1, resetAt: now + WINDOW_MS });
  else attempts.set(key, { ...current, count: current.count + 1 });
}

export function clearFailedLogins(key: string) { attempts.delete(key); }

export function loginClientKey(headers: Headers) {
  if (process.env.TRANSPORT_UI_TRUST_PROXY?.trim().toLowerCase() === "true") {
    const forwarded = headers.get("x-forwarded-for")?.split(",").at(-1)?.trim();
    if (forwarded) return forwarded;
  }
  return "untrusted-proxy";
}

export function resetLoginRateLimitForTests() { attempts.clear(); }
