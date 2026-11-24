import { afterEach, describe, expect, it, vi } from "vitest";

import { TransportError } from "./journey";
import { loadWithTransientRetry, retryNotice, transientRetryDelay } from "./place-retry";

afterEach(() => { vi.useRealTimers(); });

describe("장소 지도 일시 실패 재조회 규칙", () => {
  it("429·503은 Retry-After 5초 이하(없으면 약 1초)만, 504는 Retry-After가 5초 이하로 있을 때만 다시 묻는다", () => {
    const half = () => 0.5;
    // 서버가 준 최소 대기를 지키고 그 절반까지 비례해 흩뜨린다.
    expect(transientRetryDelay(new TransportError("혼잡", 429, 2), half)).toBe(2500);
    expect(transientRetryDelay(new TransportError("혼잡", 429, 2), () => 0)).toBe(2000);
    expect(transientRetryDelay(new TransportError("혼잡", 429, 2), () => 0.999)).toBeLessThan(3000);
    expect(transientRetryDelay(new TransportError("gateway", 503, 5), half)).toBe(6250);
    expect(transientRetryDelay(new TransportError("gateway", 503, 0), half)).toBe(1250);
    expect(transientRetryDelay(new TransportError("짧은 시한", 504, 3), half)).toBe(3750);
    // Retry-After 없는 504는 BFF·gateway가 30초를 기다린 끝의 시한 초과다. 곧바로 되풀이하지 않는다.
    expect(transientRetryDelay(new TransportError("gateway 시한", 504, 0), half)).toBeNull();
    // backend 시한 초과(504, Retry-After 10초)는 25초를 쓴 계산이라 곧바로 되풀이하지 않는다.
    expect(transientRetryDelay(new TransportError("시한", 504, 10), half)).toBeNull();
    for (const status of [400, 401, 404, 422, 500, 502]) expect(transientRetryDelay(new TransportError("x", status, 0), half)).toBeNull();
    expect(transientRetryDelay(new Error("network"), half)).toBeNull();
    expect(transientRetryDelay(new DOMException("aborted", "AbortError"), half)).toBeNull();
  });

  it("같은 signal로 Retry-After가 지난 뒤 한 번만 다시 묻고 두 번째 실패는 그대로 던진다", async () => {
    vi.useFakeTimers();
    const second = new TransportError("다시 혼잡", 429, 2);
    const load = vi.fn().mockRejectedValueOnce(new TransportError("혼잡", 429, 2)).mockRejectedValueOnce(second);
    const controller = new AbortController();
    const result = loadWithTransientRetry(load, "transport/features/places?kinds=rail_station", controller.signal, () => 0);
    const settled = result.catch((reason: unknown) => reason);
    await vi.advanceTimersByTimeAsync(1999);
    expect(load).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(await settled).toBe(second);
    expect(load).toHaveBeenCalledTimes(2);
    expect(load.mock.calls.every(call => call[0] === "transport/features/places?kinds=rail_station" && call[1] === controller.signal)).toBe(true);
  });

  it("재조회 성공 값을 돌려준다", async () => {
    vi.useFakeTimers();
    const load = vi.fn().mockRejectedValueOnce(new TransportError("gateway", 503, 0)).mockResolvedValueOnce({ items: [] });
    const result = loadWithTransientRetry(load, "transport/features/places", new AbortController().signal, () => 0);
    await vi.advanceTimersByTimeAsync(1000);
    await expect(result).resolves.toEqual({ items: [] });
  });

  it("기다리는 중 범위·필터가 바뀌어 취소되면 다시 묻지 않는다", async () => {
    vi.useFakeTimers();
    const load = vi.fn().mockRejectedValueOnce(new TransportError("혼잡", 429, 2));
    const controller = new AbortController();
    const settled = loadWithTransientRetry(load, "transport/features/places", controller.signal, () => 0).catch((reason: unknown) => reason);
    await vi.advanceTimersByTimeAsync(500);
    controller.abort();
    await vi.advanceTimersByTimeAsync(5000);
    expect(await settled).toBe(controller.signal.reason);
    expect(load).toHaveBeenCalledTimes(1);
  });

  it("재조회 대상이 아니면 즉시 원래 오류를 던진다", async () => {
    const failure = new TransportError("시한", 504, 10);
    const load = vi.fn().mockRejectedValue(failure);
    await expect(loadWithTransientRetry(load, "transport/features/places", new AbortController().signal)).rejects.toBe(failure);
    expect(load).toHaveBeenCalledTimes(1);
  });

  it("혼잡·시한 실패만 서버 안내와 다시 조회 허락 시각을 낸다", () => {
    expect(retryNotice(new TransportError("장소 지도 조회가 혼잡합니다.", 429, 2), 1_000)).toEqual({ message: "장소 지도 조회가 혼잡합니다.", retryAt: 3_000 });
    expect(retryNotice(new TransportError("시간이 초과되었습니다.", 504, 10), 1_000)).toEqual({ message: "시간이 초과되었습니다.", retryAt: 11_000 });
    expect(retryNotice(new TransportError("검색 조건을 다시 확인해 주세요.", 422, 0), 1_000)).toBeNull();
    expect(retryNotice(new Error("network"), 1_000)).toBeNull();
  });
});
