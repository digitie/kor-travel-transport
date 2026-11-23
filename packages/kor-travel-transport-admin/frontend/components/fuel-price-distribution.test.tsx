// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, expect, test, vi } from "vitest";
import { FuelRegionStats, FuelStationPricePosition } from "./fuel-price-distribution";
import { distributionOption } from "./fuel-distribution-chart-option";
import { FuelViewportSummary } from "./fuel-statistics";
import { PlaceDetails } from "./journey-controls";
import { sampleDistribution } from "@/lib/fuel-price-distribution.fixture";
import type { Place } from "@/lib/journey";

// 캔버스 ECharts 대신 받은 props를 그대로 보여 주는 대역(차트 옵션은 아래 distributionOption 테스트가 본다).
vi.mock("./fuel-distribution-chart", () => ({
  default: (props: { percent: boolean; compare: boolean; pinnedPrice?: number | null; label: string }) =>
    <div data-testid="chart" role="img" aria-label={props.label} data-percent={String(props.percent)}
      data-compare={String(props.compare)} data-pinned={String(props.pinnedPrice ?? "")} />,
}));

const regions = Array.from({ length: 8 }, (_, index) => ({
  sido_value: "15", sido_name: "충북", sigungu_value: `150${index}`, sigungu_name: index === 0 ? "옥천군" : `시군${index}`, station_count: 29 - index,
}));
const station = {
  station_id: 7, name: "옥천주유소", price: 1819, sells_product: true, products: ["B027", "D047"],
  comparisons: [
    { scope: "sigungu", label: "옥천군", station_count: 29, minimum_price: 1819, average_price: 1883, maximum_price: 1998, price: 1819, difference: -64, percentile: 1.7, grade: "A+", grade_label: "제일싸요", sufficient: true },
    { scope: "sido", label: "충북", station_count: 500, minimum_price: 1700, average_price: 1870, maximum_price: 2300, price: 1819, difference: -51, percentile: 45, grade: "B", grade_label: "평범해요", sufficient: true },
    { scope: "nationwide", label: "전국", station_count: 11000, minimum_price: 1765, average_price: 1854, maximum_price: 2549, price: 1819, difference: -35, percentile: 30, grade: "B+", grade_label: "조금 싸요", sufficient: true },
  ],
};

let cleanup: (() => Promise<void>) | undefined;
afterEach(async () => { await cleanup?.(); cleanup = undefined; document.body.innerHTML = ""; });
async function mount(node: React.ReactNode) {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const container = document.createElement("div"); document.body.append(container);
  const root = createRoot(container);
  await act(async () => root.render(node));
  cleanup = async () => { await act(async () => root.unmount()); container.remove(); };
  return container;
}
const settle = () => act(async () => { for (let i = 0; i < 5; i++) await Promise.resolve(); await new Promise(resolve => setTimeout(resolve, 0)); });
const button = (name: string) => [...document.querySelectorAll("button")].find(node => (node.getAttribute("aria-label") ?? node.textContent ?? "").includes(name))!;
const checkbox = (name: string) => [...document.querySelectorAll("label")].find(node => node.textContent?.includes(name))!.querySelector("input")!;

const okcheon = { sido_value: "15", sigungu_value: "1500", label: "옥천군", station_count: 29, selected: false, basis: "viewport" as const };

test("지역 칩은 하나만 보이고, 누르면 그 시군구 통계 대화상자를 연다", async () => {
  const load = vi.fn().mockResolvedValue(sampleDistribution);
  const container = await mount(<FuelRegionStats region={okcheon} product="B027" load={load} />);
  expect(container.querySelector('[role="group"]')?.getAttribute("aria-label")).toBe("지도 대표 지역 가격 통계");
  expect(container.querySelectorAll(".fuel-sigungu-chip")).toHaveLength(1);
  // 자동으로 보이는 지역은 해제할 것이 없다.
  expect(container.querySelector(".fuel-sigungu-clear")).toBeNull();
  expect(button("옥천군 휘발유 가격 통계").getAttribute("aria-label")).toBe("옥천군 휘발유 가격 통계 · 지도 안 29개 주유소");
  await act(async () => button("옥천군 휘발유 가격 통계").click());
  await settle();
  expect(load).toHaveBeenCalledWith("transport/fuel/price-distribution?product_code=B027&sido_value=15&sigungu_value=1500", expect.anything());
  const dialog = document.querySelector('[role="dialog"]')!;
  expect(dialog.querySelector("h2")?.textContent).toBe("옥천군 29개 휘발유 값 통계");
  expect(dialog.textContent).toContain("최저 1,819원, 평균 1,883원, 최고 1,998원");
  expect(dialog.querySelector("time")?.textContent).toMatch(/2026년 11월 22일 일요일 오전 7시 기준/);
  expect(dialog.querySelector('[role="img"]')?.getAttribute("aria-label")).toContain("옥천군 휘발유 가격 분포 그래프");
  expect(dialog.textContent).toContain("가장 많은 가격 구간은 1,840원~ 1,860원 미만으로 14개");
  // 분포(%) 토글: 막대·표·요약이 백분율로 바뀐다.
  await act(async () => checkbox("분포(%)").click());
  expect(dialog.querySelector('[data-testid="chart"]')?.getAttribute("data-percent")).toBe("true");
  expect(dialog.querySelector('[aria-label="옥천군 휘발유 가격 구간별 주유소"]')?.textContent).toContain("48.3%");
  // 전국 대비 토글: 전국 최저·평균·최고 범례와 요약이 붙는다.
  expect(dialog.textContent).not.toContain("전국 최저(1,765원)");
  await act(async () => checkbox("전국 대비").click());
  expect(dialog.querySelector('[data-testid="chart"]')?.getAttribute("data-compare")).toBe("true");
  for (const text of ["전국 최저(1,765원)", "전국 평균(1,854원)", "전국 최고(2,549원)"]) expect(dialog.textContent).toContain(text);
  // 유종을 바꾸면 같은 시군구를 다시 읽는다.
  const select = dialog.querySelector("select")!;
  await act(async () => { select.value = "D047"; select.dispatchEvent(new Event("change", { bubbles: true })); });
  await settle();
  expect(load).toHaveBeenLastCalledWith("transport/fuel/price-distribution?product_code=D047&sido_value=15&sigungu_value=1500", expect.anything());
});

test("지도 중심 시군구 칩은 그룹 이름으로 근거를 알리고 해제 버튼이 없다", async () => {
  const load = vi.fn().mockResolvedValue(sampleDistribution);
  const container = await mount(<FuelRegionStats region={{ ...okcheon, basis: "center", station_count: null }} product="B027" load={load} onClear={vi.fn()} />);
  expect(container.querySelector('[role="group"]')?.getAttribute("aria-label")).toBe("지도 중심 지역 가격 통계");
  expect(container.querySelector(".fuel-sigungu-clear")).toBeNull();
  // 화면 안 상위 목록에 없는 중심 시군구는 주유소 수 없이 이름만.
  expect(button("옥천군 휘발유 가격 통계").getAttribute("aria-label")).toBe("옥천군 휘발유 가격 통계");
  expect(container.querySelector(".fuel-sigungu-chip small")).toBeNull();
});

test("고른 지역은 칩 하나와 해제 버튼, 화면 밖이면 주유소 수 없이 이름만, 해제하면 초점을 남는 칩으로", async () => {
  const load = vi.fn().mockResolvedValue(sampleDistribution);
  const onClear = vi.fn();
  const fallback = { current: document.createElement("button") };
  document.body.append(fallback.current);
  const selected = { sido_value: "26", sigungu_value: "2601", label: "부산 중구", station_count: null, selected: true, basis: "selected" as const };
  const container = await mount(<FuelRegionStats region={selected} product="D047" load={load} onClear={onClear} focusFallback={fallback} />);
  expect(container.querySelector('[role="group"]')?.getAttribute("aria-label")).toBe("선택한 지역 가격 통계");
  expect(container.querySelectorAll(".fuel-sigungu-chip:not(.fuel-sigungu-clear)")).toHaveLength(1);
  expect(button("부산 중구 경유 가격 통계").getAttribute("aria-label")).toBe("부산 중구 경유 가격 통계");
  expect(container.querySelector(".fuel-sigungu-chip small")).toBeNull();
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => { callback(0); return 0; });
  await act(async () => button("부산 중구 선택 해제").click());
  expect(onClear).toHaveBeenCalledTimes(1);
  // 부모가 아직 다시 그리지 않았으면 칩이 남아 있으므로 칩으로 초점이 간다.
  expect(document.activeElement).toBe(button("부산 중구 경유 가격 통계"));
  vi.unstubAllGlobals();
});

test("표본이 3곳 미만이면 그래프 대신 안내 문구, 해당 유종이 없으면 없음 안내", async () => {
  const small = { ...sampleDistribution, sigungu: { ...sampleDistribution.sigungu, station_count: 2, sufficient: false } };
  const load = vi.fn().mockResolvedValueOnce(small).mockResolvedValueOnce({ ...sampleDistribution, sigungu: null });
  await mount(<FuelRegionStats region={okcheon} product="B027" load={load} />);
  await act(async () => button("옥천군 휘발유 가격 통계").click());
  await settle();
  const dialog = document.querySelector('[role="dialog"]')!;
  expect(dialog.textContent).toContain("주유소가 2곳뿐이라 분포 그래프를 그리지 않습니다(최소 3곳)");
  expect(dialog.querySelector('[data-testid="chart"]')).toBeNull();
  const select = dialog.querySelector("select")!;
  await act(async () => { select.value = "K015"; select.dispatchEvent(new Event("change", { bubbles: true })); });
  await settle();
  expect(dialog.textContent).toContain("이 시군구에는 이번 통계에 LPG 가격이 없습니다.");
});

test("주유소 상세는 시군구·시도·전국 등급과 평균 대비 차이, 핀이 꽂힌 분포를 보인다", async () => {
  const load = vi.fn().mockResolvedValue({ ...sampleDistribution, station });
  await mount(<FuelStationPricePosition stationId={7} productCodes={["D047", "B027"]} selectedProducts={[]} load={load} />);
  await settle();
  expect(load).toHaveBeenCalledWith("transport/fuel/price-distribution?product_code=B027&station_id=7", expect.anything());
  const row = document.querySelector(".fuel-grade-row")!;
  const grades = [...row.querySelectorAll(".fuel-grade[data-scope]")].map(node => [
    node.getAttribute("data-scope"), node.querySelector(".fuel-grade-circle")!.textContent, node.querySelector(".fuel-grade-caption")!.textContent,
    node.querySelector(".fuel-grade-diff")!.textContent]);
  expect(grades).toEqual([
    ["sigungu", "A+옥천군", "제일싸요", "평균 −64원"],
    ["sido", "B충북", "평범해요", "평균 −51원"],
    ["nationwide", "B+전국", "조금 싸요", "평균 −35원"],
  ]);
  expect(row.textContent).toContain("옥천군 29곳 중 A+ 제일싸요. 평균 1,883원 대비 −64원, 낮은 가격부터 1.7%.");
  await act(async () => button("옥천군 가격 분포").click());
  await settle();
  const dialog = document.querySelector('[role="dialog"]')!;
  expect(dialog.querySelector('[data-testid="chart"]')?.getAttribute("data-pinned")).toBe("1819");
  expect(dialog.textContent).toContain("이 주유소 1,819원");
  expect([...dialog.querySelectorAll("option")].map(node => node.textContent)).toEqual(["휘발유", "경유"]);
});

test("팔지 않는 유종·선택 유종 우선·불러오기 실패", async () => {
  const load = vi.fn().mockResolvedValueOnce({ ...sampleDistribution, station: { ...station, price: null, sells_product: false, comparisons: [] } })
    .mockRejectedValueOnce(new Error("boom"));
  await mount(<FuelStationPricePosition stationId={7} productCodes={["B027", "D047"]} selectedProducts={["D047"]} load={load} />);
  await settle();
  expect(load.mock.calls[0][0]).toContain("product_code=D047");
  expect(document.body.textContent).toContain("이번 통계에 이 주유소의 경유 가격이 없어 비교하지 않습니다.");
  await cleanup?.(); cleanup = undefined;
  await mount(<FuelStationPricePosition stationId={7} productCodes={["B027"]} selectedProducts={[]} load={load} />);
  await settle();
  expect(document.querySelector('[role="alert"]')?.textContent).toContain("주변 대비 가격을 불러오지 못했습니다.");
});

test("차트 옵션: 전국 비교선은 점선 3개, 핀은 곡선 위 같은 가격 위치, 막대는 오른쪽 축", () => {
  const palette = Object.fromEntries(["--warning", "--text-secondary", "--brand", "--success", "--danger", "--card", "--text-primary", "--control-line"]
    .map(token => [token, "rgba(1, 2, 3, 1.000)"])) as Parameters<typeof distributionOption>[0]["palette"];
  const base = { distribution: sampleDistribution.sigungu, nationwide: sampleDistribution.nationwide, productLabel: "휘발유", palette };
  const plain = distributionOption({ ...base, percent: false, compare: false });
  expect(plain.series[0]).toMatchObject({ type: "bar", yAxisIndex: 1, data: [1, 4, 14, 0, 8, 2] });
  expect(plain.series[1]).toMatchObject({ type: "line", xAxisIndex: 1, yAxisIndex: 0 });
  expect(plain.series[1].markLine).toBeUndefined();
  expect(plain.series[1].markPoint).toBeUndefined();
  const compared = distributionOption({ ...base, percent: true, compare: true, pinnedPrice: 1819 });
  expect(compared.series[0].data[0]).toBe(3.4);
  expect(compared.series[1].markLine?.data.map(row => [row.name, row.yAxis, row.lineStyle.type])).toEqual([
    ["전국 최저", 1765, "dashed"], ["전국 평균", 1854, "dashed"], ["전국 최고", 2549, "dashed"]]);
  expect(compared.series[1].markPoint?.data[0].coord).toEqual([0, 1819]);
  expect(compared.yAxis[0].min).toBeLessThanOrEqual(1765);
  expect(compared.yAxis[0].max).toBeGreaterThanOrEqual(2549);
});

test("관리(transport) 화면에는 시군구 칩·주변 대비 가격이 나오지 않는다", () => {
  const items = [{ product_code: "B027", station_count: 3, average_price: 1700, minimum_price: 1600, maximum_price: 1800, price_spread: 200,
    standard_deviation: 10, saving_50l: 5000, cheapest_station_count: 1, cheapest_station: null, generated_at: "2026-11-21T22:00:00Z" }];
  const admin = renderToStaticMarkup(<FuelViewportSummary items={items} pending={false} />);
  expect(admin).not.toContain("fuel-sigungu-chips");
  const place = { id: 7, kind: "fuel_station", source: "opinet_browser", name: "옥천주유소", longitude: 127.6, latitude: 36.3,
    prices: [{ product_code: "B027", price: 1819, observed_at: "2026-11-21T22:00:00Z" }], line_names: [], facilities: [],
    updated_at: "2026-11-21T22:00:00Z" } as unknown as Place;
  const load = vi.fn();
  const detail = renderToStaticMarkup(<PlaceDetails place={place} load={load} />);
  expect(detail).not.toContain("주변 대비 가격");
  expect(load).not.toHaveBeenCalled();
  // 공개 유가 화면에서만 칩과 비교가 나온다.
  const publicSummary = renderToStaticMarkup(<FuelViewportSummary items={items} pending={false}
    publicFuel={{ products: [], onProductsChange: () => {}, sigungu: regions.slice(0, 1), load }} />);
  expect(publicSummary).toContain("fuel-sigungu-chips");
  expect(renderToStaticMarkup(<PlaceDetails place={place} load={load} publicFuel={{ refreshing: false }} />)).toContain("주변 대비 가격");
});

test("고른 지역(파란 칩)의 통계 대화상자에는 '해제'가 있어 누르면 선택을 풀고 닫힌다. 자동 칩에는 없다", async () => {
  const load = vi.fn().mockResolvedValue(sampleDistribution);
  const onClear = vi.fn();
  const selected = { sido_value: "26", sigungu_value: "2601", label: "부산 중구", station_count: 3, selected: true, basis: "selected" as const };
  const container = await mount(<FuelRegionStats region={selected} product="B027" load={load} onClear={onClear} />);
  const chip = container.querySelector<HTMLButtonElement>(".fuel-sigungu-chip:not(.fuel-sigungu-clear)")!;
  expect(chip.dataset.basis).toBe("selected");
  expect(chip.hasAttribute("data-selected")).toBe(true);
  await act(async () => chip.click());
  await settle();
  const release = document.querySelector<HTMLButtonElement>('[role="dialog"] .fuel-distribution-release')!;
  expect(release.textContent).toBe("해제");
  await act(async () => release.click());
  expect(onClear).toHaveBeenCalledTimes(1);
  expect(document.querySelector('[role="dialog"]')).toBeNull();
  await cleanup?.(); cleanup = undefined;
  // 자동(지도 중심) 칩: 파란 칩이 아니고 대화상자에 해제가 없다.
  const auto = await mount(<FuelRegionStats region={{ ...okcheon, basis: "center" }} product="B027" load={load} onClear={onClear} />);
  const autoChip = auto.querySelector<HTMLButtonElement>(".fuel-sigungu-chip")!;
  expect(autoChip.dataset.basis).toBe("center");
  expect(autoChip.hasAttribute("data-selected")).toBe(false);
  await act(async () => autoChip.click());
  await settle();
  expect(document.querySelector('[role="dialog"]')).not.toBeNull();
  expect(document.querySelector(".fuel-distribution-release")).toBeNull();
});

const grades = [
  { product_code: "B027", scope: "sigungu", label: "옥천군", station_count: 29, minimum_price: 1819, average_price: 1883, maximum_price: 1998, price: 1819, difference: -64, percentile: 1.7, grade: "A+", grade_label: "제일싸요", sufficient: true },
  { product_code: "D047", scope: "sigungu", label: "옥천군", station_count: 28, minimum_price: 1600, average_price: 1680, maximum_price: 1800, price: 1720, difference: 40, percentile: 72, grade: "C+", grade_label: "조금 비싸요", sufficient: true },
  { product_code: "K015", scope: "sigungu", label: "옥천군", station_count: 2, minimum_price: 1000, average_price: 1050, maximum_price: 1100, price: 1100, difference: 50, percentile: 75, grade: null, grade_label: null, sufficient: false },
];

test("주유소 상세: 여러 유종을 팔면 유종마다 가격 옆에 시군구 등급 안내, 한 번의 요청(product_grades)", async () => {
  const load = vi.fn().mockResolvedValue({ ...sampleDistribution, station: { ...station, products: ["B027", "D047", "K015"], product_grades: grades } });
  const place = { id: 7, kind: "fuel_station", source: "opinet_browser", name: "옥천주유소", longitude: 127.6, latitude: 36.3,
    prices: [{ product_code: "B027", price: 1819, observed_at: new Date().toISOString() }, { product_code: "D047", price: 1720, observed_at: new Date().toISOString() },
      { product_code: "K015", price: 1100, observed_at: new Date().toISOString() }], line_names: [], facilities: [], updated_at: "2026-11-21T22:00:00Z" } as unknown as Place;
  await mount(<PlaceDetails place={place} load={load} publicFuel={{ refreshing: false, products: [] }} showHeading={false} />);
  await settle();
  // 유종별 등급 때문에 요청을 늘리지 않는다(가격 분포 한 번 — 주유소 이력은 따로).
  expect(load.mock.calls.filter(([path]) => String(path).includes("price-distribution"))).toHaveLength(1);
  const rows = [...document.querySelectorAll(".public-fuel-current-prices > div")].map(row => [
    row.querySelector("dt")!.textContent, row.querySelector(".fuel-product-grade [aria-hidden]")?.textContent ?? null]);
  expect(rows).toEqual([["휘발유", "A+ 제일싸요"], ["경유", "C+ 조금 비싸요"], ["LPG", "비교 부족"]]);
  expect(document.querySelector('.fuel-product-grade[data-tone="pricey"] .sr-only')?.textContent).toBe("경유 옥천군 28곳 중 C+ 조금 비싸요, 평균 대비 +40원");
  // 선택 유종(첫 유종)의 시군구·시도·전국 상세 등급 원은 그대로다.
  expect(document.querySelectorAll(".fuel-grade-row .fuel-grade[data-scope]")).toHaveLength(3);
});

test("옛 API(product_grades 없음)도 읽고, 한 유종만 파는 주유소에는 유종별 안내를 덧붙이지 않는다", async () => {
  const load = vi.fn().mockResolvedValue({ ...sampleDistribution, station });
  const place = { id: 7, kind: "fuel_station", source: "opinet_browser", name: "옥천주유소", longitude: 127.6, latitude: 36.3,
    prices: [{ product_code: "B027", price: 1819, observed_at: new Date().toISOString() }], line_names: [], facilities: [], updated_at: "2026-11-21T22:00:00Z" } as unknown as Place;
  await mount(<PlaceDetails place={place} load={load} publicFuel={{ refreshing: false, products: [] }} showHeading={false} />);
  await settle();
  expect(document.querySelector(".fuel-product-grade")).toBeNull();
  expect(document.querySelectorAll(".fuel-grade-row .fuel-grade[data-scope]")).toHaveLength(3);
});
