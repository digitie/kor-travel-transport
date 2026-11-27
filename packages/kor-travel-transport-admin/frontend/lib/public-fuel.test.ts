import { afterEach, expect, it, vi } from "vitest";
import { publicFuelGet } from "./public-fuel";
afterEach(() => vi.unstubAllGlobals());
it("지도·주유소 이력을 공개 연산으로만 요청하고 취소 신호를 전달한다", async () => {
  const mock = vi.fn().mockImplementation(() => Promise.resolve(new Response('{"items":[]}'))); vi.stubGlobal("fetch", mock);
  const signal = new AbortController().signal;
  await publicFuelGet("features/places?kind=fuel_station&zoom=10", signal);
  await publicFuelGet("fuel/stations/42/price-history?product_code=B027", signal);
  expect(mock.mock.calls[0][0]).toBe("/api/public/fuel/places?kind=fuel_station&zoom=10");
  expect(mock.mock.calls[1][0]).toBe("/api/public/fuel/stations/42/price-history?product_code=B027");
  expect(mock.mock.calls[0][1]).toMatchObject({ credentials: "omit", signal });
  await expect(publicFuelGet("admin/collect")).rejects.toMatchObject({ status: 404 });
  expect(mock).toHaveBeenCalledTimes(2);
});
it("장기 유가 추이는 공개 연산으로 읽고 Retry-After를 실패에 담는다", async () => {
  const mock = vi.fn().mockResolvedValueOnce(new Response("{}")).mockResolvedValueOnce(new Response('{"detail":"혼잡합니다"}', { status: 429, headers: { "retry-after": "7" } }));
  vi.stubGlobal("fetch", mock);
  await publicFuelGet("fuel/statistics/history?scope=nationwide&bucket=auto");
  expect(mock.mock.calls[0][0]).toBe("/api/public/fuel/statistics/history?scope=nationwide&bucket=auto");
  await expect(publicFuelGet("fuel/statistics/history?scope=nationwide")).rejects.toMatchObject({ status: 429, retryAfter: 7, message: "혼잡합니다" });
  await expect(publicFuelGet("fuel/statistics/history/x")).rejects.toMatchObject({ status: 404 });
});
