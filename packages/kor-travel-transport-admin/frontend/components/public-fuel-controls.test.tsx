// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, expect, test, vi } from "vitest";
import { FuelRegionPicker, PublicFuelFilterMenu } from "./public-fuel-controls";
import { FuelViewportSummary } from "./fuel-statistics";
import { DEFAULT_PUBLIC_FUEL_FILTERS } from "@/lib/public-fuel-filters";

const catalog = { items: [
  { sido_value: "01", sido_name: "서울", sigungu: [{ sigungu_value: "0101", sigungu_name: "종로구", station_count: 20, bounds: [126.9, 37.5, 127.0, 37.6] }] },
  { sido_value: "15", sido_name: "충북", sigungu: [
    { sigungu_value: "1501", sigungu_name: "영동군", station_count: 30, bounds: [127.6, 36.0, 128.0, 36.3] },
    { sigungu_value: "1502", sigungu_name: "옥천군", station_count: 29, bounds: [127.5, 36.2, 127.8, 36.4] },
  ] },
] };

let cleanup: (() => Promise<void>) | undefined;
afterEach(async () => { await cleanup?.(); cleanup = undefined; document.body.innerHTML = ""; });
async function mount(node: React.ReactNode) {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const container = document.createElement("div"); document.body.append(container);
  const root = createRoot(container);
  await act(async () => root.render(node));
  cleanup = async () => { await act(async () => root.unmount()); container.remove(); };
  return { container, rerender: (next: React.ReactNode) => act(async () => root.render(next)) };
}
const settle = () => act(async () => { await new Promise(resolve => setTimeout(resolve, 0)); });
const labelInput = (text: string) => [...document.querySelectorAll("label")].find(node => node.textContent?.trim().startsWith(text))!.querySelector("input, select") as HTMLInputElement;
const button = (text: string) => [...document.querySelectorAll("button")].find(node => node.textContent?.includes(text))!;

test("지역 이동: 현재 시군구가 체크되고, 시/도→구/군/시를 고르면 확인 버튼이 그 지역 이름이 되어 범위를 넘긴다", async () => {
  const load = vi.fn().mockResolvedValue(catalog);
  const onConfirm = vi.fn(); const onOpenChange = vi.fn();
  await mount(<FuelRegionPicker open onOpenChange={onOpenChange} load={load} current={{ sido_value: "15", sigungu_value: "1502" }} onConfirm={onConfirm} />);
  await settle();
  expect(load).toHaveBeenCalledWith("transport/fuel/area-catalog", expect.anything());
  const dialog = document.querySelector('[role="dialog"]')!;
  expect(dialog.querySelector("h2")?.textContent).toBe("지역 이동");
  expect(dialog.textContent).not.toContain("이동하세요");
  expect(labelInput("충북").checked).toBe(true);
  expect(labelInput("옥천군").checked).toBe(true);
  expect(button("충북 옥천군")).toBeTruthy();
  await act(async () => labelInput("서울").click());
  expect(button("구/군/시 선택").disabled).toBe(true);
  await act(async () => labelInput("종로구").click());
  await act(async () => button("서울 종로구").click());
  expect(onConfirm).toHaveBeenCalledWith([126.9, 37.5, 127.0, 37.6], { sido_value: "01", sigungu_value: "0101", label: "서울 종로구" });
  expect(onOpenChange).toHaveBeenCalledWith(false);
});

test("지역 칩이 없으면(places 실패·대기) 첫 시/도(서울)가 아니라 지금 지도 중심의 시/도·구/군/시를 고른 채 연다", async () => {
  const load = vi.fn().mockResolvedValue(catalog);
  // 127.7, 36.25는 영동군(127.6~128.0, 36.0~36.3)과 옥천군(127.5~127.8, 36.2~36.4) 범위에 모두 들고, 옥천군 범위가 더 작다.
  await mount(<FuelRegionPicker open onOpenChange={() => {}} load={load} center={[127.7, 36.25]} onConfirm={() => {}} />);
  await settle();
  expect(labelInput("서울").checked).toBe(false);
  expect(labelInput("충북").checked).toBe(true);
  expect(labelInput("옥천군").checked).toBe(true);
  expect(button("충북 옥천군").disabled).toBe(false);
  // 고른 뒤에는 사용자의 선택을 따른다.
  await act(async () => labelInput("영동군").click());
  expect(labelInput("영동군").checked).toBe(true);
  await act(async () => labelInput("서울").click());
  expect(button("구/군/시 선택").disabled).toBe(true);
});

test("지역 이동 '해제'는 사용자가 고른 지역이 있을 때만 확인 버튼 옆에 있고, 누르면 선택을 풀고 닫힌다", async () => {
  const load = vi.fn().mockResolvedValue(catalog);
  const onRelease = vi.fn(); const onOpenChange = vi.fn(); const onConfirm = vi.fn();
  const view = (release?: () => void) => <FuelRegionPicker open onOpenChange={onOpenChange} load={load} current={{ sido_value: "01", sigungu_value: "0101" }}
    onConfirm={onConfirm} onRelease={release} />;
  const { rerender } = await mount(view());
  await settle();
  expect(document.querySelector(".fuel-region-release")).toBeNull();
  await rerender(view(onRelease));
  const actions = [...document.querySelectorAll(".fuel-region-actions > button")].map(node => node.textContent);
  // 취소 · 해제 · (확인 = 고른 지역 이름) 순서로 확인 버튼 바로 옆이다.
  expect(actions).toEqual(["취소", "해제", "서울 종로구"]);
  await act(async () => button("해제").click());
  expect(onRelease).toHaveBeenCalledTimes(1);
  expect(onOpenChange).toHaveBeenCalledWith(false);
  expect(onConfirm).not.toHaveBeenCalled();
});

test("지역 칩이 있으면 지도 중심보다 칩을 먼저 고른다", async () => {
  const load = vi.fn().mockResolvedValue(catalog);
  await mount(<FuelRegionPicker open onOpenChange={() => {}} load={load} current={{ sido_value: "01", sigungu_value: "0101" }} center={[127.7, 36.25]} onConfirm={() => {}} />);
  await settle();
  expect(labelInput("서울").checked).toBe(true);
  expect(labelInput("종로구").checked).toBe(true);
});

test("지역 목록을 못 읽으면 다시 시도", async () => {
  const load = vi.fn().mockRejectedValueOnce(new Error("x")).mockResolvedValueOnce(catalog);
  await mount(<FuelRegionPicker open onOpenChange={() => {}} load={load} onConfirm={() => {}} />);
  await settle();
  expect(document.querySelector('[role="alert"]')?.textContent).toContain("지역 목록을 불러오지 못했습니다.");
  await act(async () => button("다시 시도").click());
  await settle();
  expect(labelInput("서울").checked).toBe(true);
});

test("맨 위 유종·필터 선택: 유종(여럿)·최저가·조건·품질인증·상표·전체 선택·초기화가 한 팝오버에서 값을 바꾼다", async () => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  const onFiltersChange = vi.fn(); const onProductsChange = vi.fn();
  const view = (filters = DEFAULT_PUBLIC_FUEL_FILTERS, products: string[] = []) =>
    <PublicFuelFilterMenu filters={filters} onFiltersChange={onFiltersChange} products={products} onProductsChange={onProductsChange} />;
  const { container, rerender } = await mount(view());
  const trigger = container.querySelector<HTMLButtonElement>(".public-fuel-filter-trigger")!;
  expect(trigger.getAttribute("aria-label")).toBe("유종·필터: 전체 유종");
  expect(trigger.textContent).toContain("전체 유종");
  // 필터 버튼·서랍은 따로 없다.
  expect(document.querySelector(".public-fuel-tools, .fuel-filter-drawer")).toBeNull();
  await act(async () => trigger.click());
  const menu = document.querySelector('[role="dialog"]')!;
  expect(menu.getAttribute("aria-label")).toBe("유종·필터");
  expect([...menu.querySelectorAll("legend")].map(node => node.textContent)).toEqual(["유종", "주유소 조건", "브랜드"]);
  // 유종 전체에서는 최저가 범위를 쓸 수 없다.
  expect(labelInput("지도 최저가").disabled).toBe(true);
  expect(menu.textContent).toContain("유종을 하나 고르면 사용할 수 있습니다.");
  expect(labelInput("전체 유종").checked).toBe(true);
  await act(async () => labelInput("경유").click());
  expect(onProductsChange).toHaveBeenLastCalledWith(["D047"]);
  // 여러 유종을 함께 고를 수 있다(지도 표시 순서로 정렬).
  await rerender(view(DEFAULT_PUBLIC_FUEL_FILTERS, ["D047"]));
  await act(async () => labelInput("휘발유").click());
  expect(onProductsChange).toHaveBeenLastCalledWith(["B027", "D047"]);
  await rerender(view(DEFAULT_PUBLIC_FUEL_FILTERS, ["B027"]));
  expect(trigger.getAttribute("aria-label")).toBe("유종·필터: 휘발유");
  const near = labelInput("지도 최저가") as unknown as HTMLSelectElement;
  expect(near.disabled).toBe(false);
  await act(async () => { near.value = "70"; near.dispatchEvent(new Event("change", { bubbles: true })); });
  expect(onFiltersChange).toHaveBeenLastCalledWith({ ...DEFAULT_PUBLIC_FUEL_FILTERS, near_min: 70 });
  for (const [label, key] of [["'24시' 만", "open_24h"], ["'셀프주유' 만", "self_only"], ["'자동세차' 만", "carwash"], ["'경정비' 만", "maintenance"], ["'편의점' 만", "cvs"], ["'품질인증주유소' 만", "kpetro"]] as const) {
    const input = labelInput(label);
    expect(input.type).toBe("checkbox");
    await act(async () => input.click());
    expect(onFiltersChange).toHaveBeenLastCalledWith({ ...DEFAULT_PUBLIC_FUEL_FILTERS, [key]: true });
  }
  // 휘발유만 고르면 LPG 전용 상표는 비활성
  expect(labelInput("SK가스").disabled).toBe(true);
  expect(labelInput("E1").disabled).toBe(true);
  await act(async () => labelInput("알뜰주유소").click());
  expect(onFiltersChange.mock.lastCall![0].brands).not.toContain("ALT");
  expect(menu.textContent).not.toMatch(/믿음|직영|스마트|면세유|화물차|테마|LIGHT|DARK/);
  // 로고가 없는 "기타" 행도 이름 글자는 한 번만이다(아이콘이 sr-only 이름·title로 다시 싣지 않는다).
  const etc = labelInput("기타").closest("label")!;
  expect(etc.textContent).toBe("기타");
  expect(etc.querySelector("[title], .sr-only")).toBeNull();
  for (const row of menu.querySelectorAll<HTMLLabelElement>(".fuel-filter-brand")) {
    const name = row.querySelector(".fuel-filter-brand-mark + span")!.textContent!.split(" · ")[0];
    expect(row.textContent!.split(name).length - 1).toBe(1);
  }
  const narrowed = { ...DEFAULT_PUBLIC_FUEL_FILTERS, brands: ["SKE"], self_only: true, near_min: 70 };
  await rerender(view(narrowed, ["B027"]));
  // 트리거는 실제로 서버에 보내는 조건 수(셀프·상표·최저가 = 3)를 알린다.
  expect(trigger.getAttribute("aria-label")).toBe("유종·필터: 휘발유, 조건 3개 적용 중");
  expect(trigger.querySelector(".public-fuel-filter-count")?.textContent).toBe("3");
  expect(labelInput("브랜드 전체 선택").checked).toBe(false);
  await act(async () => labelInput("브랜드 전체 선택").click());
  expect(onFiltersChange).toHaveBeenLastCalledWith({ ...narrowed, brands: [] });
  // 초기화는 유종과 필터를 함께 처음으로 돌린다.
  await act(async () => button("초기화").click());
  expect(onFiltersChange).toHaveBeenLastCalledWith(DEFAULT_PUBLIC_FUEL_FILTERS);
  expect(onProductsChange).toHaveBeenLastCalledWith([]);
  await act(async () => button("닫기").click());
  expect(document.querySelector('[role="dialog"]')).toBeNull();
  vi.unstubAllGlobals();
});

test("관리 화면 범위 요약에는 지역·유종·필터 선택이 없고, 공개 요약은 맨 위에 지역 아이콘과 유종·필터 하나만 둔다", () => {
  const items = [{ product_code: "B027", station_count: 3, average_price: 1700, minimum_price: 1600, maximum_price: 1800, price_spread: 200,
    standard_deviation: 10, saving_50l: 5000, cheapest_station_count: 1, cheapest_station: null, generated_at: "2026-11-21T22:00:00Z" }];
  const admin = renderToStaticMarkup(<FuelViewportSummary items={items} pending={false} />);
  for (const name of ["public-fuel-filter-trigger", "public-fuel-region-button", "fuel-sigungu-chips", "public-fuel-tools"]) expect(admin).not.toContain(name);
  const markup = renderToStaticMarkup(<FuelViewportSummary items={items} pending={false}
    publicFuel={{ products: [], onProductsChange: () => {}, filters: { ...DEFAULT_PUBLIC_FUEL_FILTERS, cvs: true }, onFiltersChange: () => {}, onOpenRegion: () => {} }} />);
  expect(markup).toContain('aria-label="유종·필터: 전체 유종, 조건 1개 적용 중"');
  expect(markup).toContain('aria-label="지역 이동"');
  // "지도 범위" 글씨는 화면에 없다(영역 이름은 aria-label에만).
  expect(markup.replace(/aria-label="[^"]*"/g, "")).not.toContain("지도 범위");
  expect(markup).not.toContain("<h2");
  // 지역 아이콘이 유종·필터보다 앞(맨 위 줄 첫 칸)에 온다.
  expect(markup.indexOf("public-fuel-region-button")).toBeLessThan(markup.indexOf("public-fuel-filter-trigger"));
});

test("통계 링크로 연 유종은 트리거에 '링크'로 표시하고, 팝오버가 저장 안내와 '저장한 유종으로 보기'를 보인다", async () => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  const onUseSaved = vi.fn(); const onProductsChange = vi.fn();
  const { container } = await mount(<PublicFuelFilterMenu products={["K015"]} onProductsChange={onProductsChange}
    linked={{ code: "K015", saved: ["B027", "D047"], onUseSaved }} />);
  const trigger = container.querySelector<HTMLButtonElement>(".public-fuel-filter-trigger")!;
  expect(trigger.getAttribute("aria-label")).toBe("유종·필터: LPG (통계 링크로 연 유종)");
  expect(trigger.querySelector(".public-fuel-filter-linked-mark")?.textContent).toBe("링크");
  await act(async () => trigger.click());
  const menu = document.querySelector('[role="dialog"]')!;
  expect(menu.textContent).toContain("통계 화면에서 고른 LPG(으)로 열었습니다. 저장한 유종(휘발유, 경유)은 그대로이며");
  expect(menu.textContent).toContain("유종을 바꾸면 그 선택을 저장합니다");
  await act(async () => button("저장한 유종으로 보기").click());
  expect(onUseSaved).toHaveBeenCalledOnce();
  expect(onProductsChange).not.toHaveBeenCalled();
  // 누른 단추가 사라지므로 팝오버를 닫아 초점을 트리거로 돌린다.
  expect(document.querySelector('[role="dialog"]')).toBeNull();
});
