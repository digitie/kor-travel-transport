// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { MultiSearch, PlaceDetails } from "./journey-controls";
import type { Place } from "@/lib/journey";

beforeEach(() => { Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true }); });
afterEach(() => vi.unstubAllGlobals());

test("비교 최대 5곳에 도달해도 여섯째 상세는 선택 변경 없이 열 수 있다", async () => {
  const options = Array.from({ length: 6 }, (_, index) => ({ id: String(index), name: `항구${index + 1}` }));
  const select = vi.fn(), inspect = vi.fn();
  const container = document.createElement("div"); document.body.append(container); const root = createRoot(container);
  try {
    await act(async () => root.render(<MultiSearch label="항구 검색" query="" onQuery={() => {}} options={options} selected={options.slice(0, 5)} onSelect={select} onInspect={inspect} />));
    const choices = container.querySelectorAll('[role="checkbox"]');
    expect(choices).toHaveLength(6);
    expect(choices[5].getAttribute("aria-disabled")).toBe("true");
    const button = container.querySelector<HTMLButtonElement>('[aria-label="항구6 상세 보기"]')!;
    expect(button.disabled).toBe(false);
    await act(async () => button.click());
    expect(inspect).toHaveBeenCalledWith("5"); expect(select).not.toHaveBeenCalled();
    expect(container.textContent).toContain("5/5곳 선택");
  } finally { await act(async () => root.unmount()); container.remove(); }
});

test("주유소 이력은 가격 카드 위에 있고 유효 가격·실관측 시각·오래된 관측을 구분한다", () => {
  vi.useFakeTimers(); vi.setSystemTime(new Date("2026-10-28T03:00:00Z"));
  try {
    const place: Place = { id: 1, kind: "fuel_station", source: "opinet_browser", brand_code: "SOL", name: "시험 주유소", address: "서울시 시험로 123", subtitle: "서울시 시험로 123", longitude: 127, latitude: 37, line_names: [], facilities: [], updated_at: "2026-10-28T03:00:00Z", prices: [
      { product_code: "B027", price: 1700, observed_at: "2026-10-20T03:00:00Z", provider_updated_at: "2026-10-19T03:00:00Z" },
      { product_code: "D047", price: 0, observed_at: "2026-10-28T03:00:00Z" },
    ] };
    const node = document.createElement("div"); node.innerHTML = renderToStaticMarkup(<PlaceDetails place={place} />);
    expect(node.querySelector("img")?.alt).toBe("S-OIL");
    expect(node.querySelector('[aria-label="주소 안내"]')).not.toBeNull();
    expect([...node.querySelectorAll(".place-details > p")].some((item) => item.textContent?.includes(place.address!))).toBe(false);
    expect(node.querySelectorAll(".price-grid > div")).toHaveLength(1);
    expect(node.querySelector(".price-grid time")?.getAttribute("datetime")).toBe("2026-10-20T03:00:00Z");
    expect(node.querySelector(".fuel-price-old")?.textContent).toBe("7일 이전 관측");
    expect(node.innerHTML.indexOf("fuel-station-history")).toBeLessThan(node.innerHTML.indexOf("price-grid"));
  } finally { vi.useRealTimers(); }
});
