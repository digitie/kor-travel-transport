import { TransportError } from "./journey";

/** 장소 지도 조회의 일시적 실패 한 번 자동 재조회 규칙.
 *
 * backend 장소 지도는 혼잡(입장 거절)에 429 + Retry-After 2초, 25초 시한 초과에 504 + Retry-After 10초를 준다.
 * 같은 조건(지도 범위·필터)에서 Retry-After가 5초 이하이거나 없을 때만 한 번 더 묻는다. 25초를 쓰고 실패한
 * 계산(Retry-After 10초)은 곧바로 되풀이하지 않고 기존 "다시 조회" 안내로 넘긴다. 기다리는 동안 화면의 마지막
 * 정상 결과는 그대로 두고, 범위·필터가 바뀌면(signal 취소) 재조회도 하지 않는다. */
const RETRYABLE_STATUSES = new Set([429, 503, 504]);
export const PLACE_RETRY_MAX_SECONDS = 5;

export function transientRetryDelay(reason: unknown, random: () => number = Math.random): number | null {
  if (!(reason instanceof TransportError) || !RETRYABLE_STATUSES.has(reason.status)) return null;
  if (reason.retryAfter > PLACE_RETRY_MAX_SECONDS) return null;
  // Retry-After가 없으면(0) 약 1초 뒤. 같은 화면을 연 여러 사용자가 한 시각에 다시 몰리지 않게 조금 흩뜨린다.
  return reason.retryAfter > 0 ? reason.retryAfter * 1000 + random() * 250 : 750 + random() * 500;
}

function waitUnlessAborted(ms: number, signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    if (signal.aborted) { reject(signal.reason); return; }
    const stop = () => { clearTimeout(timer); reject(signal.reason); };
    const timer = setTimeout(() => { signal.removeEventListener("abort", stop); resolve(); }, ms);
    signal.addEventListener("abort", stop, { once: true });
  });
}

export async function loadWithTransientRetry<T>(
  load: <R>(path: string, signal?: AbortSignal) => Promise<R>, path: string, signal: AbortSignal,
  random: () => number = Math.random,
): Promise<T> {
  try {
    return await load<T>(path, signal);
  } catch (reason) {
    const delay = signal.aborted ? null : transientRetryDelay(reason, random);
    if (delay === null) throw reason;
    await waitUnlessAborted(delay, signal);
    return load<T>(path, signal);
  }
}
