import { act } from "react";
import { render } from "@testing-library/react";
import { hydrateRoot, type Root } from "react-dom/client";
import { renderToString } from "react-dom/server";
import { ParkingAvailabilityCharts } from "@/components/parking-availability-charts";

vi.mock("next/dynamic", () => ({ default: () => () => null }));
const items = [{ parking_lot_id: 1, parking_lot_name: "시험 주차장", available_spaces: 20, total_spaces: 100, occupied_spaces: 80, observed_at: "2026-11-13T00:00:00Z" }];

beforeEach(() => vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] }));
afterEach(() => vi.useRealTimers());

test("SSR 뒤 15분 경계를 넘어도 첫 hydration snapshot은 같고 실제 시각은 구독 후 반영한다", async () => {
  vi.setSystemTime(new Date("2026-11-13T00:14:59Z"));
  const element = <ParkingAvailabilityCharts items={items} />;
  const host = document.createElement("div"); host.innerHTML = renderToString(element); document.body.append(host);
  expect(host.textContent).toContain("관측 시각 확인 중");
  vi.setSystemTime(new Date("2026-11-13T00:15:01Z"));
  const errors: unknown[] = []; let root!: Root;
  try {
    await act(async () => { root = hydrateRoot(host, element, { onRecoverableError: (error) => errors.push(error) }); });
    expect(errors).toEqual([]);
    expect(host.textContent).toContain("갱신 지연");
  } finally { await act(async () => root?.unmount()); host.remove(); }
  expect(vi.getTimerCount()).toBe(0);
});

test("새 자료가 없어도 15초 시계가 갱신 지연을 반영하고 unmount 뒤 타이머를 남기지 않는다", async () => {
  vi.setSystemTime(new Date("2026-11-13T00:14:59Z"));
  const view = render(<ParkingAvailabilityCharts items={items} />);
  expect(view.container.textContent).not.toContain("갱신 지연");
  await act(async () => { vi.advanceTimersByTime(15_000); });
  expect(view.container.textContent).toContain("갱신 지연");
  view.unmount(); expect(vi.getTimerCount()).toBe(0);
});
