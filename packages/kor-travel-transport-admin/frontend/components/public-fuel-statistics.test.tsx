// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TransportError } from "@/lib/journey";

const state = vi.hoisted(() => ({ get: vi.fn(), chart: [] as Record<string, unknown>[], labels: new Map<string, string>() }));
vi.mock("@/lib/public-fuel-statistics-client", () => ({ statisticsGet: state.get, knownRegionLabel: (key: string) => state.labels.get(key) ?? null }));
vi.mock("./fuel-price-chart-loader", () => ({ default: (props: Record<string, unknown>) => { state.chart.push(props); return <div data-chart={String(props.label)} />; } }));
vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams(window.location.search) }));
import { PublicFuelStatisticsPage } from "./public-fuel-statistics";
import { describeStatisticsError, statisticsRetryDelay } from "@/lib/public-fuel-statistics";

const generated = "2026-11-27T00:31:44Z";
const station = { name: "최저가 시험주유소", address: "서울 중구", longitude: 126.98, latitude: 37.56 };
const item = (scope_key: string, label: string, extra: Record<string, unknown> = {}) => ({ scope_key, label, generated_at: generated, product_code: "B027",
  station_count: 10200, average_price: 1853.72, minimum_price: 1736, maximum_price: 2549, cheapest_station_count: 2, cheapest_station: station, ...extra });
const statistics = (scope: string, items: unknown[], extra: Record<string, unknown> = {}) => ({ scope, generated_at: generated, update_pending: false, items, history: [], ...extra });
const trend = (days: number, extra: (index: number) => Record<string, unknown> = () => ({})) => ({ label: "전국", bucket: "day", from_day: "2026-10-29", to_day: "2026-11-27", generated_at: generated,
  points: Array.from({ length: days }, (_, index) => { const day = new Date(Date.UTC(2026, 9, 29 + index)).toISOString().slice(0, 10);
    return { product_code: "B027", day, first_day: day, last_day: day, day_count: 1, generated_at: generated, average_price: 1800 + index, minimum_price: 1700, maximum_price: 1900 + index, station_count: 10000, ...extra(index) }; }) });
const SIDO = [item('["경기도"]', "경기"), item('["서울특별시"]', "서울")];
const SIGUNGU = [item('["서울특별시","강남구"]', "서울 강남구"), item('["서울특별시","마포구"]', "서울 마포구"), item('["부산광역시","중구"]', "부산 중구")];

function respond(overrides: Record<string, unknown> = {}) {
  return (path: string) => {
    const search = new URLSearchParams(path.split("?")[1]);
    if (path.startsWith("fuel/statistics/history")) return Promise.resolve(overrides.history ?? trend(30));
    const scope = search.get("scope")!;
    const items = (overrides[scope] as unknown[] | undefined) ?? (scope === "sido" ? SIDO : scope === "sigungu" ? SIGUNGU : scope === "highway" ? [item('["0010"]', "경부선")] : [item("all", scope === "highways" ? "고속도로 전체" : "전국")]);
    return Promise.resolve(statistics(scope, items));
  };
}

let root: Root, host: HTMLDivElement;
beforeEach(() => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
  state.get.mockReset(); state.chart = []; state.labels.clear();
  window.history.replaceState(null, "", "/statistics");
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });
async function render(query = "") {
  window.history.replaceState(null, "", `/statistics${query}`);
  await act(async () => root.render(<PublicFuelStatisticsPage />));
  for (let index = 0; index < 4; index++) await act(async () => { await Promise.resolve(); });
}
const paths = () => state.get.mock.calls.map(call => String(call[0]));
const radio = (name: string) => [...host.querySelectorAll<HTMLInputElement>("input[type=radio]")].find(input => input.parentElement?.textContent === name)!;
const select = (label: string) => host.querySelector<HTMLSelectElement>(`#${CSS.escape([...host.querySelectorAll("label")].find(node => node.textContent === label)!.htmlFor)}`)!;
async function choose(element: HTMLSelectElement, value: string) {
  await act(async () => { element.value = value; element.dispatchEvent(new Event("change", { bubbles: true })); });
  for (let index = 0; index < 4; index++) await act(async () => { await Promise.resolve(); });
}

describe("공개 유가 지역별 통계", () => {
  it("전국 현재 값·최저가 주유소·기준 시각과 30일 추이를 보인다", async () => {
    state.get.mockImplementation(respond());
    await render();
    expect(paths()[0]).toBe("fuel/statistics?scope=nationwide&product_code=B027&include_history=false");
    expect(paths()[1]).toBe("fuel/statistics/history?scope=nationwide&scope_key=all&product_code=B027&to=2026-11-27&bucket=day&from=2026-10-29");
    expect(host.querySelector("h2")?.textContent).toBe("전국 · 휘발유 현재 가격");
    expect(host.textContent).toContain("1,853.72");
    expect(host.textContent).toContain("최저가 시험주유소 외 같은 가격 1곳");
    // 지도는 첫 렌더에 주소 좌표를 읽으므로 앱 안 이동(next/link)이 아니라 새로 여는 링크다.
    const link = host.querySelector<HTMLAnchorElement>('a[href^="/?longitude"]')!;
    // 보던 유종을 싣는다(지도는 저장한 유종 선택 대신 이 유종 하나로 열린다).
    expect(link.getAttribute("href")).toBe("/?longitude=126.98&latitude=37.56&product=B027");
    expect(host.querySelector("time")?.textContent).toBe("2026.11.27 09:31");
    expect(host.textContent).toContain("최근 30일 휘발유 평균 가격 변화");
    expect(host.textContent).toContain("+29원");
    expect(state.chart.at(-1)).toMatchObject({ maxGapDays: 1, rangeAsLines: false });
    expect((state.chart.at(-1)!.series as { points: Record<string, unknown>[] }[])[0].points[0].cheapest).toBeUndefined();
    expect(host.querySelector('[aria-live="polite"]')?.textContent).toBe("전국 휘발유 평균 1,853.72원");
  });

  it("유종·기간·범위를 바꾸면 그 조건으로 다시 읽고 실제로 보이는 지역을 URL에 남긴다", async () => {
    state.get.mockImplementation(respond({ history: { ...trend(60), bucket: "week" } }));
    await render();
    await act(async () => radio("경유").click());
    expect(paths()).toContain("fuel/statistics?scope=nationwide&product_code=D047&include_history=false");
    await act(async () => radio("전체").click());
    expect(paths().at(-1)).toBe("fuel/statistics/history?scope=nationwide&scope_key=all&product_code=D047&to=2026-11-27&bucket=auto");
    expect(state.chart.at(-1)).toMatchObject({ maxGapDays: 7, rangeAsLines: true });
    await act(async () => radio("시도").click());
    for (let index = 0; index < 4; index++) await act(async () => { await Promise.resolve(); });
    expect(paths()).toContain("fuel/statistics?scope=sido&product_code=D047&include_history=false");
    expect(select("시도 선택").value).toBe('["서울특별시"]');
    expect(new URLSearchParams(window.location.search).get("region")).toBe('["서울특별시"]');
    await choose(select("시도 선택"), '["경기도"]');
    expect(new URLSearchParams(window.location.search).get("region")).toBe('["경기도"]');
    expect(window.location.search).toContain("scope=sido");
  });

  it("고른 지역에 그 유종이 없으면 다른 지역을 보인다고 알리고 URL도 보이는 지역으로 바꾼다", async () => {
    state.get.mockImplementation(respond({ sigungu: [SIGUNGU[0], SIGUNGU[2]] }));
    state.labels.set('["서울특별시","마포구"]', "서울 마포구");
    await render(`?scope=sigungu&region=${encodeURIComponent('["서울특별시","마포구"]')}&product=K015`);
    expect(host.querySelector('[role="status"]')?.textContent).toContain("서울 마포구에는 LPG 통계가 없어 서울 강남구 값을 보여 드립니다");
    expect(new URLSearchParams(window.location.search).get("region")).toBe('["서울특별시","강남구"]');
  });

  it("링크의 지역 이름을 모르면 URL 글자를 넣지 않고 '찾지 못해'로 알린다", async () => {
    state.get.mockImplementation(respond());
    await render(`?scope=sido&region=${encodeURIComponent("<b>가짜시</b>")}`);
    expect(host.textContent).toContain("링크의 지역을 찾지 못해 서울 값을 보여 드립니다");
    expect(host.textContent).not.toContain("가짜시");
  });

  it("고속도로로 바꾸면 없는 유종(등유)을 휘발유로 바꾸고 알린다", async () => {
    state.get.mockImplementation(respond());
    await render("?product=C004");
    await act(async () => radio("고속도로").click());
    for (let index = 0; index < 4; index++) await act(async () => { await Promise.resolve(); });
    expect(radio("휘발유").checked).toBe(true); expect(radio("등유").disabled).toBe(true);
    expect(host.textContent).toContain("고속도로 휴게소에는 등유 가격이 없어 휘발유(으)로 바꿨습니다");
    expect(new URLSearchParams(window.location.search).get("product")).toBeNull();
    expect(paths().some(path => path.includes("product_code=C004") && path.includes("highway"))).toBe(false);
  });

  it("고속도로: 전체 노선은 전체 범주를 먼저, 끝난 뒤 노선 목록을 읽는다", async () => {
    state.get.mockImplementation(respond());
    await render("?scope=highway");
    const statisticsPaths = paths().filter(path => !path.startsWith("fuel/statistics/history"));
    expect(statisticsPaths).toEqual(["fuel/statistics?scope=highways&product_code=B027&include_history=false", "fuel/statistics?scope=highway&product_code=B027&include_history=false"]);
    expect(host.querySelector("h2")?.textContent).toBe("고속도로 전체 · 휘발유 현재 가격");
    // 고급유·등유는 고속도로에서 고를 수 없다.
    expect(radio("고급유").disabled).toBe(true); expect(radio("등유").disabled).toBe(true); expect(radio("LPG").disabled).toBe(false);
  });

  it("고속도로: 고른 노선에 그 유종이 없으면 전체 노선 값을 읽어 보인다(빈 상태로 막히지 않는다)", async () => {
    state.get.mockImplementation(respond({ highway: [item('["0010"]', "경부선")] }));
    state.labels.set('["0140"]', "밀양울산선");
    await render(`?scope=highway&region=${encodeURIComponent('["0140"]')}&product=K015`);
    expect(paths()).toContain("fuel/statistics?scope=highways&product_code=K015&include_history=false");
    expect(host.querySelector("h2")?.textContent).toBe("고속도로 전체 · LPG 현재 가격");
    expect(host.textContent).toContain("밀양울산선에는 LPG 통계가 없어 고속도로 전체 값을 보여 드립니다");
    expect(select("노선 선택").value).toBe("all");
    expect(new URLSearchParams(window.location.search).has("region")).toBe(false);
  });

  it("고속도로 좌표 없는 최저가 휴게소와 같은 최저가 목록·이상값을 안내한다", async () => {
    const tie = (key: string, name: string) => ({ station_key: key, name, address: null, longitude: null, latitude: null, price: 184 });
    state.get.mockImplementation(respond({
      highways: [item("all", "고속도로 전체", { minimum_price: 184, average_price: 1830, cheapest_station: { name: "시험휴게소", address: null, longitude: null, latitude: null }, cheapest_station_count: 2, cheapest_stations: [tie("1", "시험휴게소"), tie("2", "둘째휴게소")] })],
      history: trend(30, index => index === 0 ? { minimum_price: 184 } : {}),
    }));
    await render("?scope=highway");
    expect(host.textContent).toContain("휴게소 위치 좌표가 없어 지도 링크는 없습니다");
    expect(host.textContent).toContain("같은 최저가 2곳 보기");
    expect(host.textContent).toContain("원천 입력 오류일 수 있습니다");
    expect(host.textContent).toContain("평균보다 30% 넘게 낮음 · 입력 오류일 수 있음");
    expect(host.textContent).toContain("최저·최고 1건은 입력 오류로 보고");
    // 기본은 평균 선만(최저·최고 없음). 켜면 믿을 만한 최저·최고만 그린다.
    const pointsOf = () => (state.chart.at(-1)!.series as { points: { minimum: number | null }[] }[])[0].points;
    expect(pointsOf().every(point => point.minimum === null)).toBe(true);
    const toggle = [...host.querySelectorAll<HTMLInputElement>("input[type=checkbox]")].find(input => input.parentElement?.textContent?.includes("최저·최고도 함께"))!;
    await act(async () => toggle.click());
    expect(pointsOf()[0].minimum).toBeNull(); expect(pointsOf()[1].minimum).toBe(1700);
  });

  it("반영 대기·오래된 통계를 알린다", async () => {
    state.get.mockImplementation((path: string) => Promise.resolve(path.startsWith("fuel/statistics/history") ? trend(1)
      : statistics("nationwide", [item("all", "전국", { generated_at: "2026-11-20T00:00:00Z" })], { update_pending: true, generated_at: "2026-11-20T00:00:00Z" })));
    await render();
    expect(host.textContent).toContain("새로 모은 가격을 통계에 반영하는 중입니다");
    expect(host.textContent).toMatch(/통계가 \d+일 전 기준입니다/);
    expect(host.textContent).toContain("비교할 기록 없음");
  });

  it("혼잡(Retry-After)은 남은 초 동안 다시 조회를 막고, 지나면 그 구역만 다시 읽고 제목으로 초점을 옮긴다", async () => {
    vi.useFakeTimers();
    state.get.mockImplementation((path: string) => path.startsWith("fuel/statistics/history")
      ? Promise.reject(new TransportError("유가 정보를 불러오지 못했습니다. 다시 확인해 주세요.", 429, 30)) : respond()(path));
    await render();
    const alert = host.querySelector('[role="alert"]')!;
    expect(alert.textContent).toContain("지금 유가 통계 조회가 몰려 있습니다");
    const button = alert.querySelector("button")!;
    expect(button.disabled).toBe(true); expect(button.textContent).toContain("30초 후");
    for (let second = 0; second < 30; second++) await act(async () => { vi.advanceTimersByTime(1000); });
    expect(button.disabled).toBe(false);
    const listCalls = paths().filter(path => !path.startsWith("fuel/statistics/history")).length;
    state.get.mockImplementation(respond());
    await act(async () => button.click());
    for (let index = 0; index < 4; index++) await act(async () => { await Promise.resolve(); });
    expect(paths().filter(path => !path.startsWith("fuel/statistics/history")).length).toBe(listCalls);
    expect(state.get.mock.calls.at(-1)![2]).toMatchObject({ force: true });
    expect(document.activeElement?.textContent).toBe("최근 30일 휘발유 평균 가격 변화");
    expect(host.textContent).toContain("+29원");
  });

  it("짧은 혼잡은 한 번 자동으로 다시 조회하며 그동안 알린다", async () => {
    vi.useFakeTimers();
    state.get.mockRejectedValueOnce(new TransportError("혼잡", 503, 2)).mockImplementation(respond());
    await render();
    expect(host.textContent).toContain("조회가 몰려 잠시 뒤 다시 조회하는 중");
    await act(async () => { vi.advanceTimersByTime(4100); });
    for (let index = 0; index < 4; index++) await act(async () => { await Promise.resolve(); });
    expect(host.textContent).toContain("1,853.72");
  });

  it("형식이 다른 응답은 화면을 깨뜨리지 않고 조회 실패로 보인다", async () => {
    state.get.mockImplementation(respond({ history: { points: "x" } }));
    await render();
    expect(host.querySelector('[role="alert"]')?.textContent).toContain("추이 다시 조회");
    expect(host.textContent).toContain("1,853.72");
  });

  it("지도에서 왔으면(from=map) '유가 지도'가 뒤로 가고 표시는 주소에서 지운다, 아니면 지도를 새로 연다", async () => {
    state.get.mockImplementation(respond());
    const back = vi.spyOn(window.history, "back").mockImplementation(() => undefined);
    await render();
    const plain = new MouseEvent("click", { bubbles: true, cancelable: true });
    const mapLink = () => [...host.querySelectorAll("a")].find(node => node.textContent === "유가 지도")!;
    // 지도를 새로 열 때는 보던 유종으로 연다.
    expect(mapLink().getAttribute("href")).toBe("/?product=B027");
    mapLink().dispatchEvent(plain);
    expect(plain.defaultPrevented).toBe(false);
    await act(async () => root.unmount()); root = createRoot(host);
    await render("?from=map&product=D047");
    expect(window.location.search).toBe("?product=D047");
    const fromMap = new MouseEvent("click", { bubbles: true, cancelable: true });
    [...host.querySelectorAll("a")].find(node => node.textContent === "유가 지도")!.dispatchEvent(fromMap);
    expect(fromMap.defaultPrevented).toBe(true); expect(back).toHaveBeenCalledOnce();
  });

  it("오래 열어 둔 화면은 다시 읽되, 그동안 직전 값을 지우지 않는다", async () => {
    vi.useFakeTimers();
    state.get.mockImplementation(respond());
    await render();
    const calls = state.get.mock.calls.length;
    let release: (value: unknown) => void = () => undefined;
    state.get.mockImplementation((path: string) => new Promise(resolve => { release = () => resolve(respond()(path)); }));
    await act(async () => { vi.advanceTimersByTime(11 * 60_000); });
    expect(state.get.mock.calls.length).toBeGreaterThan(calls);
    expect(host.textContent).toContain("1,853.72");
    expect(host.querySelector('[aria-busy="true"]')).toBeNull();
    await act(async () => { release(null); });
  });

  it("200인데 JSON이 아닌 응답은 형식 오류로 알린다", () => {
    expect(describeStatisticsError(new SyntaxError("Unexpected token <")).message).toContain("형식");
  });
});

describe("실패 문구·재조회 대기", () => {
  it("서버 한국어 안내는 혼잡·시한에만 쓰고, 개발자용 422 안내는 일반 문구로 바꾼다", () => {
    expect(describeStatisticsError(new TransportError("유가 통계 조회가 혼잡합니다.", 429, 120))).toEqual({ message: "유가 통계 조회가 혼잡합니다.", retryAfter: 60 });
    expect(describeStatisticsError(new TransportError("유가 정보를 불러오지 못했습니다. 다시 확인해 주세요.", 429, 0))).toEqual({ message: "지금 유가 통계 조회가 몰려 있습니다. 잠시 후 다시 조회해 주세요.", retryAfter: 5 });
    expect(describeStatisticsError(new TransportError("이 범위는 scope_key가 필요합니다(통계 페이지의 history_scope_key).", 422, 0)).message).toBe("유가 통계를 불러오지 못했습니다. 다시 조회해 주세요.");
    expect(describeStatisticsError(new TransportError("유가 API에 연결하지 못했습니다.", 502, 0))).toMatchObject({ message: expect.stringContaining("늦거나 연결되지"), retryAfter: 5 });
    expect(describeStatisticsError(new TransportError("x", 504, 10)).message).toContain("제시간에");
    expect(describeStatisticsError(new DOMException("t", "TimeoutError")).retryAfter).toBe(5);
    expect(describeStatisticsError(new TypeError("fetch failed")).message).toContain("네트워크");
  });
  it("Retry-After 없는 혼잡은 3~6초 뒤 한 번, 5초 넘는 Retry-After·504는 자동으로 다시 묻지 않는다", () => {
    expect(statisticsRetryDelay(new TransportError("x", 429, 0), () => 0)).toBe(3000);
    expect(statisticsRetryDelay(new TransportError("x", 429, 0), () => 1)).toBe(6000);
    expect(statisticsRetryDelay(new TransportError("x", 503, 2), () => .5)).toBe(3000);
    expect(statisticsRetryDelay(new TransportError("x", 429, 8))).toBeNull();
    expect(statisticsRetryDelay(new TransportError("x", 504, 1))).toBeNull();
    expect(statisticsRetryDelay(new Error("x"))).toBeNull();
  });
});
