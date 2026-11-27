import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { clearStatisticsCache, statisticsGet } from "./public-fuel-statistics-client";
import { parseRetryAfter } from "./public-fuel";

const signal = new AbortController().signal;
beforeEach(() => clearStatisticsCache());
afterEach(() => vi.unstubAllGlobals());

it("공개 BFF 두 경로만 읽고 1분 안의 같은 경로는 다시 받지 않는다(다시 조회는 받는다)", async () => {
  let now = 1_000;
  const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(new Response('{"items":[]}')));
  vi.stubGlobal("fetch", fetchMock);
  const path = "fuel/statistics?scope=sigungu&product_code=B027&include_history=false";
  await statisticsGet(path, signal, { maxAgeMs: 60_000, now: () => now });
  expect(fetchMock.mock.calls[0][0]).toBe("/api/public/fuel/statistics?scope=sigungu&product_code=B027&include_history=false");
  expect(fetchMock.mock.calls[0][1]).toMatchObject({ credentials: "omit", cache: "no-store", signal });
  now += 30_000; await statisticsGet(path, signal, { maxAgeMs: 60_000, now: () => now });
  expect(fetchMock).toHaveBeenCalledTimes(1);
  await statisticsGet(path, signal, { maxAgeMs: 60_000, force: true, now: () => now });
  expect(fetchMock).toHaveBeenCalledTimes(2);
  now += 61_000; await statisticsGet(path, signal, { maxAgeMs: 60_000, now: () => now });
  expect(fetchMock).toHaveBeenCalledTimes(3);
  await expect(statisticsGet("fuel/places?x=1", signal, { maxAgeMs: 0 })).rejects.toMatchObject({ status: 404 });
});

it("장기 추이는 ETag로 재검증하고 304면 저장본을 쓴다", async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(new Response('{"points":[1]}', { headers: { etag: 'W/"a"' } }))
    .mockResolvedValueOnce(new Response(null, { status: 304, headers: { etag: 'W/"a"' } }));
  vi.stubGlobal("fetch", fetchMock);
  const path = "fuel/statistics/history?scope=nationwide&bucket=auto";
  expect(await statisticsGet(path, signal, { maxAgeMs: 0 })).toEqual({ points: [1] });
  expect(await statisticsGet(path, signal, { maxAgeMs: 0 })).toEqual({ points: [1] });
  expect(fetchMock.mock.calls[1][1].headers).toMatchObject({ "if-none-match": 'W/"a"' });
});

it("실패는 한국어 안내와 Retry-After(초·HTTP-date)를 담는다", async () => {
  const date = new Date(Date.now() + 9_000).toUTCString();
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(new Response('{"detail":"혼잡합니다"}', { status: 429, headers: { "retry-after": "4" } }))
    .mockResolvedValueOnce(new Response("<html>busy</html>", { status: 429, headers: { "retry-after": date } }));
  vi.stubGlobal("fetch", fetchMock);
  await expect(statisticsGet("fuel/statistics?a=1", signal, { maxAgeMs: 0 })).rejects.toMatchObject({ status: 429, retryAfter: 4, message: "혼잡합니다" });
  const error = await statisticsGet("fuel/statistics?a=2", signal, { maxAgeMs: 0 }).catch((reason: unknown) => reason) as { retryAfter: number; message: string };
  expect(error.retryAfter).toBeGreaterThanOrEqual(8); expect(error.retryAfter).toBeLessThanOrEqual(10);
  expect(error.message).toBe("유가 정보를 불러오지 못했습니다. 다시 확인해 주세요.");
});

it("Retry-After는 정수 초 또는 HTTP-date만 읽는다", () => {
  const now = Date.parse("2026-11-27T00:00:00Z");
  expect(parseRetryAfter("7", now)).toBe(7);
  expect(parseRetryAfter("Fri, 27 Nov 2026 00:00:30 GMT", now)).toBe(30);
  expect(parseRetryAfter("Thu, 26 Nov 2026 00:00:00 GMT", now)).toBe(0);
  expect(parseRetryAfter("-3", now)).toBe(0);
  expect(parseRetryAfter("soon", now)).toBe(0);
  expect(parseRetryAfter(null, now)).toBe(0);
});
