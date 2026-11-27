import { TransportError } from "./journey";
import { parseRetryAfter } from "./public-fuel";
import { GENERIC_FUEL_ERROR } from "./public-fuel-statistics";

/**
 * 공개 통계 화면 전용 BFF 읽기. `publicFuelGet`과 같은 경로·오류 규칙에 두 가지를 더한다.
 * - 짧은 메모리 재사용: 같은 경로를 `maxAgeMs` 안에 다시 고르면(시군구 → 시도 → 시군구 등) 다시 받지 않는다.
 *   시군구 목록은 유종당 약 146KB이고 backend 캐시가 없다.
 * - 조건부 재검증: 장기 추이는 backend가 weak ETag를 준다. 저장된 ETag를 `If-None-Match`로 보내고 304면 저장본을 쓴다
 *   (BFF가 304·ETag를 그대로 전달한다). 브라우저 HTTP 캐시는 BFF의 `no-store` 때문에 쓰지 않는다.
 * 다시 조회(`force`)는 메모리 재사용만 건너뛰고 ETag 재검증은 그대로 한다.
 */
type Entry = { data: unknown; etag: string | null; at: number };
const cache = new Map<string, Entry>();
const MAX_ENTRIES = 16;
const PATH = /^fuel\/(statistics|statistics\/history)\?/;

export function clearStatisticsCache() { cache.clear(); }

export async function statisticsGet(path: string, signal: AbortSignal, { maxAgeMs, force = false, now = Date.now }: { maxAgeMs: number; force?: boolean; now?: () => number }): Promise<unknown> {
  if (!PATH.test(path)) throw new TransportError("허용되지 않은 유가 조회입니다.", 404, 0);
  const stored = cache.get(path);
  if (stored && !force && now() - stored.at < maxAgeMs) return stored.data;
  const headers: Record<string, string> = { accept: "application/json" };
  if (stored?.etag) headers["if-none-match"] = stored.etag;
  const response = await fetch(`/api/public/fuel/${path.slice("fuel/".length)}`, { cache: "no-store", credentials: "omit", headers, signal });
  if (response.status === 304 && stored) {
    remember(path, { ...stored, at: now() });
    return stored.data;
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: unknown } | null;
    const detail = typeof body?.detail === "string" && /[가-힣]/.test(body.detail) ? body.detail : GENERIC_FUEL_ERROR;
    throw new TransportError(detail, response.status, parseRetryAfter(response.headers.get("retry-after")));
  }
  const data: unknown = await response.json();
  remember(path, { data, etag: response.headers.get("etag"), at: now() });
  return data;
}

function remember(path: string, entry: Entry) {
  cache.delete(path);
  cache.set(path, entry);
  while (cache.size > MAX_ENTRIES) cache.delete(cache.keys().next().value!);
}
