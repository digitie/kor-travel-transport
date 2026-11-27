// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TransportError } from "@/lib/journey";

const state = vi.hoisted(() => ({ get: vi.fn(), chart: [] as Record<string, unknown>[] }));
vi.mock("@/lib/public-fuel", () => ({ publicFuelGet: state.get }));
vi.mock("./fuel-price-chart-loader", () => ({ default: (props: Record<string, unknown>) => { state.chart.push(props); return <div data-chart={String(props.label)} />; } }));
vi.mock("next/link", () => ({ default: ({ href, children, ...props }: { href: string; children: React.ReactNode }) => <a href={href} {...props}>{children}</a> }));
import { PublicFuelStatisticsPage } from "./public-fuel-statistics";
import { DEFAULT_VIEW, describeStatisticsError, type PublicFuelStatisticsView } from "@/lib/public-fuel-statistics";

const generated = "2026-11-27T00:31:44Z";
const item = (scope_key: string, label: string, extra: Record<string, unknown> = {}) => ({ scope_key, label, generated_at: generated, product_code: "B027",
  station_count: 10200, average_price: 1853.72, minimum_price: 1736, maximum_price: 2549, cheapest_station_count: 2,
  cheapest_station: { name: "최저가 시험주유소", address: "서울 중구", longitude: 126.98, latitude: 37.56 }, ...extra });
const statistics = (items: unknown[], extra: Record<string, unknown> = {}) => ({ generated_at: generated, update_pending: false, items, ...extra });
const trend = (days: number) => ({ label: "전국", bucket: "day", from_day: "2026-10-29", to_day: "2026-11-27", generated_at: generated,
  points: Array.from({ length: days }, (_, index) => { const day = new Date(Date.UTC(2026, 9, 29 + index)).toISOString().slice(0, 10);
    return { product_code: "B027", day, first_day: day, last_day: day, day_count: 1, generated_at: generated, average_price: 1800 + index, minimum_price: 1700, maximum_price: 1900 + index, station_count: 10000 }; }) });

let root: Root, host: HTMLDivElement;
beforeEach(() => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
  state.get.mockReset(); state.chart = [];
  window.history.replaceState(null, "", "/statistics");
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.useRealTimers(); vi.unstubAllGlobals(); });
async function render(view: Partial<PublicFuelStatisticsView> = {}) {
  await act(async () => root.render(<PublicFuelStatisticsPage initialView={{ ...DEFAULT_VIEW, ...view }} />));
  await act(async () => { await Promise.resolve(); });
}
const paths = () => state.get.mock.calls.map(call => String(call[0]));
const radio = (name: string) => [...host.querySelectorAll<HTMLInputElement>("input[type=radio]")].find(input => input.parentElement?.textContent === name)!;

describe("공개 유가 지역별 통계", () => {
  it("전국 현재 값·최저가 주유소·기준 시각과 30일 추이를 보인다", async () => {
    state.get.mockImplementation((path: string) => Promise.resolve(path.startsWith("fuel/statistics/history") ? trend(30) : statistics([item("all", "전국")])));
    await render();
    expect(paths()[0]).toBe("fuel/statistics?scope=nationwide&product_code=B027");
    expect(paths()[1]).toBe("fuel/statistics/history?scope=nationwide&scope_key=all&product_code=B027&to=2026-11-27&bucket=day&from=2026-10-29");
    expect(host.querySelector("h2")?.textContent).toBe("전국 · 휘발유 현재 가격");
    expect(host.textContent).toContain("1,853.72");
    expect(host.textContent).toContain("최저가 시험주유소 외 1곳");
    expect(host.querySelector<HTMLAnchorElement>('a[href^="/?longitude"]')?.getAttribute("href")).toBe("/?longitude=126.98&latitude=37.56");
    expect(host.querySelector("time")?.textContent).toBe("2026.11.27 09:31 KST");
    expect(host.textContent).toContain("최근 30일 휘발유 평균 가격 추이");
    expect(host.textContent).toContain("+29원");
    expect(state.chart.at(-1)).toMatchObject({ maxGapDays: 1, rangeAsLines: false });
    // 차트 점에는 관리 지도(/fuel)로 가는 최저가 링크를 넣지 않는다.
    expect((state.chart.at(-1)!.series as { points: Record<string, unknown>[] }[])[0].points[0].cheapest).toBeUndefined();
  });

  it("유종·기간·범위를 바꾸면 그 조건으로 다시 읽고 URL에 남긴다", async () => {
    state.get.mockImplementation((path: string) => Promise.resolve(path.startsWith("fuel/statistics/history") ? { ...trend(60), bucket: "week" }
      : path.includes("scope=sido") ? statistics([item('["경기도"]', "경기"), item('["서울특별시"]', "서울")]) : statistics([item("all", "전국")])));
    await render();
    await act(async () => radio("경유").click());
    expect(paths()).toContain("fuel/statistics?scope=nationwide&product_code=D047");
    await act(async () => radio("전체").click());
    expect(paths().at(-1)).toBe("fuel/statistics/history?scope=nationwide&scope_key=all&product_code=D047&to=2026-11-27&bucket=auto");
    expect(state.chart.at(-1)).toMatchObject({ maxGapDays: 7, rangeAsLines: true });
    await act(async () => radio("시도").click());
    expect(paths()).toContain("fuel/statistics?scope=sido&product_code=D047");
    expect(paths().at(-1)).toContain("scope=sido&scope_key=%5B%22%EC%84%9C%EC%9A%B8%ED%8A%B9%EB%B3%84%EC%8B%9C%22%5D");
    expect(window.location.search).toBe("?scope=sido&product=D047&period=all");
    const select = host.querySelector("select")!;
    expect(select.value).toBe('["서울특별시"]');
    await act(async () => { select.value = '["경기도"]'; select.dispatchEvent(new Event("change", { bubbles: true })); });
    expect(new URLSearchParams(window.location.search).get("region")).toBe('["경기도"]');
  });

  it("고속도로 전체 노선은 노선 목록과 전체 범주를 따로 읽고, 없는 유종은 안내한다", async () => {
    state.get.mockImplementation((path: string) => Promise.resolve(path.includes("scope=highways") ? statistics([]) : statistics([])));
    await render({ area: "highway", product: "B034" });
    expect(paths()).toEqual(expect.arrayContaining(["fuel/statistics?scope=highway&product_code=B034", "fuel/statistics?scope=highways&product_code=B034"]));
    expect(host.textContent).toContain("이 범위에는 고급유 통계가 없습니다");
    expect(host.textContent).toContain("휘발유·경유·LPG");
    expect(paths().some(path => path.includes("history"))).toBe(false);
  });

  it("반영 대기·오래된 통계를 알린다", async () => {
    state.get.mockImplementation((path: string) => Promise.resolve(path.startsWith("fuel/statistics/history") ? trend(1)
      : statistics([item("all", "전국", { generated_at: "2026-11-20T00:00:00Z" })], { update_pending: true, generated_at: "2026-11-20T00:00:00Z" })));
    await render();
    expect(host.textContent).toContain("새로 수집한 가격을 통계에 반영하는 중입니다");
    expect(host.textContent).toMatch(/통계가 \d+일 전 기준입니다/);
    expect(host.textContent).toContain("비교할 기록 없음");
  });

  it("혼잡(Retry-After)은 남은 초 동안 다시 조회를 막고, 지나면 다시 읽는다", async () => {
    vi.useFakeTimers();
    state.get.mockRejectedValue(new TransportError("유가 정보를 불러오지 못했습니다. 다시 확인해 주세요.", 429, 30));
    await render();
    const alert = host.querySelector('[role="alert"]')!;
    expect(alert.textContent).toContain("지금 유가 통계 조회가 몰려 있습니다");
    const button = alert.querySelector("button")!;
    expect(button.disabled).toBe(true); expect(button.textContent).toContain("30초 후");
    const before = state.get.mock.calls.length;
    for (let second = 0; second < 30; second++) await act(async () => { vi.advanceTimersByTime(1000); });
    expect(button.disabled).toBe(false);
    state.get.mockImplementation((path: string) => Promise.resolve(path.startsWith("fuel/statistics/history") ? trend(3) : statistics([item("all", "전국")])));
    await act(async () => button.click());
    await act(async () => { await Promise.resolve(); });
    expect(state.get.mock.calls.length).toBeGreaterThan(before);
  });

  it("짧은 혼잡은 한 번 자동으로 다시 조회하며 그동안 알린다", async () => {
    vi.useFakeTimers();
    state.get.mockRejectedValueOnce(new TransportError("혼잡", 503, 2)).mockImplementation((path: string) => Promise.resolve(path.startsWith("fuel/statistics/history") ? trend(3) : statistics([item("all", "전국")])));
    await render();
    expect(host.textContent).toContain("조회가 몰려 잠시 뒤 다시 조회하는 중");
    await act(async () => { vi.advanceTimersByTime(3100); });
    await act(async () => { await Promise.resolve(); });
    expect(host.textContent).toContain("1,853.72");
  });
});

it("형식이 다른 응답은 화면을 깨뜨리지 않고 조회 실패로 보인다", async () => {
  state.get.mockImplementation((path: string) => Promise.resolve(path.startsWith("fuel/statistics/history") ? { points: "x" } : statistics([item("all", "전국")])));
  await render();
  expect(host.querySelector('[role="alert"]')?.textContent).toContain("추이 다시 조회");
  expect(host.textContent).toContain("1,853.72");
});

describe("실패 문구", () => {
  it("서버 한국어 안내는 그대로, 시한 초과는 시한 안내로 바꾼다", () => {
    expect(describeStatisticsError(new TransportError("유가 통계 조회가 혼잡합니다.", 429, 120))).toEqual({ message: "유가 통계 조회가 혼잡합니다.", retryAfter: 60 });
    expect(describeStatisticsError(new TransportError("x", 504, 10)).message).toContain("제시간에");
    expect(describeStatisticsError(new DOMException("t", "TimeoutError")).retryAfter).toBe(0);
    expect(describeStatisticsError(new TypeError("fetch failed")).message).toContain("네트워크");
  });
});
