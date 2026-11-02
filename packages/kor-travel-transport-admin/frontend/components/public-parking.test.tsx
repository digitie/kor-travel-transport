// @vitest-environment jsdom
import { act, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { hasCoordinates, type Place } from "@/lib/journey";
import type { PublicParkingItem, PublicParkingPage } from "@/lib/public-parking";

vi.mock("./transport-map", () => ({ TransportMap: ({ places, toolbar, feedback, listContent, details, detailTitle, onSelectPlace }: {
  places: Place[]; toolbar: ReactNode; feedback: ReactNode; listContent: ReactNode;
  details?: ReactNode; detailTitle?: ReactNode; onSelectPlace: (place: Place) => void;
}) => <div>{toolbar}{feedback}<div aria-label="지도 모의">{places.filter(hasCoordinates).map(place => <button key={place.id} type="button" onClick={() => onSelectPlace(place)}>{place.name} 지도</button>)}</div>{listContent}<h2>{detailTitle}</h2>{details}</div> }));
import { PublicParkingDetails } from "./public-parking-details";
import { PublicParkingLots } from "./public-parking-lots";

const lot = (id = 1, change: Partial<PublicParkingItem> = {}): PublicParkingItem => ({
  id, source: "datagokr_parking_lots", provider_id: `P${id}`, name: `저장주차장${id}`,
  category: "공영", parking_type: "노외", road_address: "시험시 중앙로", land_address: "시험 지번",
  longitude: 127, latitude: 37.5, capacity: 20, fee_info: "유료", basic_minutes: 30, basic_fee: 0,
  additional_minutes: null, additional_fee: null, daily_minutes: 1440, daily_fee: 5000,
  monthly_fee: null, operating_days: "평일+토요일", opening_hours: {
    weekday_open: "09:00", weekday_close: "18:00", saturday_open: null,
    saturday_close: null, holiday_open: null, holiday_close: null,
  }, payment_methods: "카드", notes: "관리기관 안내 확인", phone: "031-123-4567",
  institution_name: "시험시청", institution_code: "T1", disabled_parking: "2면",
  reference_date: "2026-10-01", collected_at: "2026-11-03T00:00:00Z", is_current: true, ...change,
});
const page = (items: PublicParkingItem[], change: Partial<PublicParkingPage> = {}): PublicParkingPage => ({
  generated_at: "2026-11-03T00:00:00Z", collection: { source: "datagokr_parking_lots",
    last_success_at: "2026-11-03T00:00:00Z", failed: false, stale: false, last_attempt_failed: false },
  items, has_more: false, next_cursor: null, ...change,
});
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
beforeEach(() => { Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true }); vi.stubGlobal("fetch", vi.fn()); });
afterEach(() => vi.unstubAllGlobals());
async function mount(node: ReactNode) {
  const container = document.createElement("div"); document.body.append(container);
  const root = createRoot(container); await act(async () => root.render(node));
  return { container, root, done: async () => { await act(async () => root.unmount()); container.remove(); } };
}
async function click(container: HTMLElement, label: string) {
  await act(async () => [...container.querySelectorAll<HTMLButtonElement>("button")].find(button => button.textContent === label)!.click());
}

test("좌표 없는 주차장을 목록에 보존하고 cursor 더 보기·정적 상세·미제공을 연결한다", async () => {
  const first = lot(1, { latitude: null, longitude: null, capacity: 0 });
  vi.mocked(fetch).mockImplementation(async input => {
    const url = new URL(String(input), "http://test");
    if (url.pathname.endsWith("/1")) return response({ ...first, raw: { private: "raw-노출금지" } });
    return response(url.searchParams.has("cursor") ? page([first, lot(2)])
      : page([first], { has_more: true, next_cursor: "a/b+=" }));
  });
  const { container, done } = await mount(<PublicParkingLots />);
  try {
    expect(container.querySelector('[aria-label="지도 모의"]')?.textContent).not.toContain(first.name);
    expect(container.querySelector('[aria-label="일반 주차장 목록"]')?.textContent).toContain("좌표 미등록");
    expect(container.textContent).toContain("총 0면");
    await click(container, "주차장 100곳 더 불러오기");
    const url = new URL(String(vi.mocked(fetch).mock.calls.at(-1)![0]), "http://test");
    expect(url.searchParams.get("cursor")).toBe("a/b+=");
    expect(container.querySelectorAll(".place-row")).toHaveLength(2);
    await act(async () => container.querySelector<HTMLButtonElement>(".place-row")!.click());
    expect(String(vi.mocked(fetch).mock.calls.at(-1)![0])).toBe("/api/transport/transport/parking-lots/1");
    expect(container.textContent).toContain("실시간 잔여면·혼잡도는 제공하지 않습니다");
    expect(container.textContent).toContain("30분 / 0원");
    expect(container.textContent).toContain("미제공 / 미제공");
    expect(container.textContent).toContain("09:00 ~ 18:00");
    expect(container.textContent).toContain("2026-10-01");
    expect(container.querySelector('a[href="tel:0311234567"]')).not.toBeNull();
    expect(container.textContent).not.toContain("raw-노출금지");
  } finally { await done(); }
});

test("collection 미완과 오래된 마지막 완료본·실패를 빈 정상 결과로 숨기지 않는다", async () => {
  vi.mocked(fetch).mockResolvedValue(response(page([], { collection: {
    source: "datagokr_parking_lots", last_success_at: null, failed: false, stale: true, last_attempt_failed: true,
  } })));
  const { container, done } = await mount(<PublicParkingLots />);
  try {
    expect(container.textContent).toContain("완료된 주차장 기준정보가 아직 없습니다");
    expect(container.textContent).toContain("최근 수집 시도가 실패");
    vi.mocked(fetch).mockResolvedValue(response(page([lot()], { collection: {
      source: "datagokr_parking_lots", last_success_at: "2026-01-01T00:00:00Z", failed: false, stale: true, last_attempt_failed: false,
    } })));
    await click(container, "첫 페이지 새로고침");
    expect(container.textContent).toContain("마지막 완료 수집이 오래된 기준정보");
    expect(container.querySelectorAll(".place-row")).toHaveLength(1);
  } finally { await done(); }
});

test("cursor 세대 변경 오류는 보존하고 첫 페이지 재조회로 회복한다", async () => {
  vi.mocked(fetch).mockResolvedValueOnce(response(page([lot()], { has_more: true, next_cursor: "old" })))
    .mockResolvedValueOnce(response({ detail: "주차장 기준정보가 갱신됐습니다. 첫 페이지부터 다시 조회해 주세요." }, 409))
    .mockResolvedValueOnce(response(page([lot(2)])));
  const { container, done } = await mount(<PublicParkingLots />);
  try {
    await click(container, "주차장 100곳 더 불러오기");
    expect(container.textContent).toContain("기준정보가 갱신됐습니다");
    expect(container.querySelectorAll(".place-row")).toHaveLength(1);
    await click(container, "첫 페이지부터 조회");
    const url = new URL(String(vi.mocked(fetch).mock.calls.at(-1)![0]), "http://test");
    expect(url.searchParams.has("cursor")).toBe(false);
    expect(container.querySelector(".place-row")?.textContent).toContain("저장주차장2");
    expect(container.textContent).not.toContain("기준정보가 갱신됐습니다");
  } finally { await done(); }
});

test("검색을 바꾸면 이전 cursor와 늦은 목록 응답을 섞지 않는다", async () => {
  let finish: (response: Response) => void = () => {};
  vi.mocked(fetch).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }))
    .mockResolvedValueOnce(response(page([lot(2, { name: "새 검색 결과" })])));
  const { container, done } = await mount(<PublicParkingLots />);
  try {
    const input = container.querySelector<HTMLInputElement>('input[type="search"]')!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, "수지 & 중앙");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => container.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
    const url = new URL(String(vi.mocked(fetch).mock.calls.at(-1)![0]), "http://test");
    expect(url.searchParams.get("q")).toBe("수지 & 중앙");
    expect(url.searchParams.has("cursor")).toBe(false);
    await act(async () => finish(response(page([lot(1, { name: "늦은 이전 목록" })]))));
    expect(container.textContent).toContain("새 검색 결과");
    expect(container.textContent).not.toContain("늦은 이전 목록");
  } finally { await done(); }
});

test("상세 선택을 바꾸면 늦은 이전 응답을 적용하지 않고 오류 재시도를 제공한다", async () => {
  let finish: (response: Response) => void = () => {};
  vi.mocked(fetch).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }))
    .mockResolvedValueOnce(response(lot(2, { is_current: false })))
    .mockRejectedValueOnce(new TypeError("Failed to fetch"))
    .mockResolvedValueOnce(response(lot(3)));
  const { container, root, done } = await mount(<PublicParkingDetails id={1} />);
  try {
    expect(container.textContent).toContain("확인 중");
    await act(async () => root.render(<PublicParkingDetails id={2} />));
    await act(async () => finish(response(lot(1, { notes: "늦은 이전 응답" }))));
    expect(container.textContent).not.toContain("늦은 이전 응답");
    expect(container.textContent).toContain("이전 저장 정보");
    await act(async () => root.render(<PublicParkingDetails id={3} />));
    expect(container.textContent).toContain("잠시 후 다시 조회");
    await click(container, "주차장 정보 다시 조회");
    expect(container.textContent).not.toContain("잠시 후 다시 조회");
    expect(container.textContent).toContain("관리번호 P3");
  } finally { await done(); }
});
