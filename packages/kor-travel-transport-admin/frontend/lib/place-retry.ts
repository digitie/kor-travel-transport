import { useEffect, useState } from "react";

import { TransportError } from "./journey";

/** 장소 지도 조회의 일시적 실패 한 번 자동 재조회 규칙.
 *
 * backend 장소 지도는 혼잡(입장 거절)에 429 + Retry-After 2초, 25초 시한 초과에 504 + Retry-After 10초를 준다.
 * 같은 조건(지도 범위·필터)에서 Retry-After가 5초 이하일 때만 한 번 더 묻는다. Retry-After가 없는 429·503은
 * 약 1초 뒤에 묻는다. Retry-After가 없는 504는 gateway·BFF가 30초를 기다린 끝의 시한 초과라 자동으로 되풀이하지
 * 않는다. 25초를 쓰고 실패한 계산(Retry-After 10초)도 곧바로 되풀이하지 않고 "다시 조회" 안내로 넘긴다.
 * 범위·필터가 바뀌거나 화면을 떠나면(signal 취소) 재조회도 하지 않는다. */
const RETRYABLE_STATUSES = new Set([429, 503, 504]);
export const PLACE_RETRY_MAX_SECONDS = 5;
const DEFAULT_RETRY_MS = 1000;

export function transientRetryDelay(reason: unknown, random: () => number = Math.random): number | null {
  if (!(reason instanceof TransportError) || !RETRYABLE_STATUSES.has(reason.status)) return null;
  if (reason.retryAfter > PLACE_RETRY_MAX_SECONDS) return null;
  if (reason.status === 504 && reason.retryAfter <= 0) return null;
  // 서버가 준 최소 대기는 지키고 그 절반까지 비례해 흩뜨린다. 같은 화면을 연 여러 사용자가 한 시각에 다시 몰리지 않는다.
  const base = reason.retryAfter > 0 ? reason.retryAfter * 1000 : DEFAULT_RETRY_MS;
  return base + random() * base / 2;
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

/** 실패 안내에 보일 서버 안내와 "다시 조회"를 허락할 시각. 혼잡·시한(429·503·504)만 서버 안내를 쓴다. */
export type RetryNotice = { message: string; retryAt: number };

export function retryNotice(reason: unknown, now: number = Date.now()): RetryNotice | null {
  if (!(reason instanceof TransportError) || !RETRYABLE_STATUSES.has(reason.status)) return null;
  return { message: reason.message, retryAt: now + reason.retryAfter * 1000 };
}

/** `retryAt`(ms epoch)이 지났는지. 지나는 순간 한 번 다시 그린다. */
export function useRetryReady(retryAt: number | undefined): boolean {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (retryAt === undefined) return;
    const timer = setTimeout(() => setNow(Date.now()), Math.max(0, retryAt - Date.now()));
    return () => clearTimeout(timer);
  }, [retryAt]);
  return retryAt === undefined || now >= retryAt;
}
