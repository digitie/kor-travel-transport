const WINDOW_MS = 10 * 60 * 1000;
const MAX_ATTEMPTS = 5;
const attempts = new Map<string, { count: number; resetAt: number }>();

export function loginRateLimited(key: string | null, now = Date.now()) {
  if (!key) return false;
  const current = attempts.get(key);
  if (!current || current.resetAt <= now) return false;
  return current.count >= MAX_ATTEMPTS;
}

export function recordFailedLogin(key: string | null, now = Date.now()) {
  if (!key) return;
  const current = attempts.get(key);
  if (!current || current.resetAt <= now) attempts.set(key, { count: 1, resetAt: now + WINDOW_MS });
  else attempts.set(key, { ...current, count: current.count + 1 });
}

export function clearFailedLogins(key: string | null) { if (key) attempts.delete(key); }

export function loginClientKey(headers: Headers) {
  if (process.env.TRANSPORT_UI_TRUST_PROXY?.trim().toLowerCase() === "true") {
    const forwarded = headers.get("x-forwarded-for")?.split(",").at(-1)?.trim();
    if (forwarded) return forwarded;
  }
  // TCP peer 주소가 없는 Next Route Handler에서는 신뢰할 수 없는 header를 IP로
  // 사용하지 않는다. 공용 키로 묶으면 공격자 5회 실패만으로 전체 관리자가 잠긴다.
  return null;
}

export function resetLoginRateLimitForTests() { attempts.clear(); }
