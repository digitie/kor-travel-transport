import { describe, expect, it } from "vitest";
import { railMarkerLabel, type RailSummaries, type RailSummary } from "./rail-markers";

const now = Date.parse("2026-09-28T03:00:00Z");
const row: RailSummary = { place_id: 1, status: "stored", stale: false, collected_at: new Date(now - 3600_000).toISOString(), departure_count: 2, next_departure: { departure_time: "121000", destination_name: "오금" } };
const data: RailSummaries = { generated_at: new Date(now).toISOString(), basis: "calendar", items: [row] };
describe("저장 다음 열차 마커", () => {
  it("예정임을 명시하고 시각·행선지를 제공한다", () => expect(railMarkerLabel(data, row, now)).toBe("예정 12:10 · 오금행"));
  it.each(["240000", "000030", "235960", "121099", "foo"])("확정할 수 없는 시각 %s를 숨긴다", (value) => {
    expect(railMarkerLabel(data, { ...row, next_departure: { departure_time: value, destination_name: null } }, now)).toBe("예정 시각 확인 필요");
  });
  it("미연결을 운행 없음으로 오인하지 않는다", () => expect(railMarkerLabel(data, { ...row, status: "unlinked" }, now)).toBe("시간표 연결 전"));
  it("미수집을 구분한다", () => expect(railMarkerLabel(data, { ...row, status: "not_collected" }, now)).toBe("시간표 수집 대기"));
  it.each(["calendar_unavailable", "overnight_unresolved", "selected_period"])("운행일 %s는 시각을 추정하지 않는다", (basis) => expect(railMarkerLabel({ ...data, basis }, row, now)).toBe("운행일 확인 필요"));
  it("노후 저장본을 숨긴다", () => expect(railMarkerLabel(data, { ...row, stale: true }, now)).toBe("시간표 갱신 필요"));
  it("서버의 stale 플래그와 무관하게 저장본 나이를 검증한다", () => expect(railMarkerLabel(data, { ...row, collected_at: new Date(now - 49 * 3600_000).toISOString() }, now)).toBe("시간표 갱신 필요"));
  it("갱신 지연 응답에서 다음 예정 시각을 숨긴다", () => expect(railMarkerLabel(data, row, now + 70_001)).toBe("예정 시각 재확인 중"));
  it("방금 지난 출발 시각을 숨긴다", () => expect(railMarkerLabel(data, { ...row, next_departure: { departure_time: "115959", destination_name: null } }, now)).toBe("예정 시각 재확인 중"));
  it("자정 경계에서 전일 응답을 숨긴다", () => expect(railMarkerLabel({ ...data, generated_at: "2026-09-28T14:59:59Z" }, row, Date.parse("2026-09-28T15:00:01Z"))).toBe("예정 시각 재확인 중"));
  it("응답을 아직 받지 않았다", () => expect(railMarkerLabel(undefined, undefined, now)).toBe("예정 시각 확인 중"));
  it.each([0, 2])("빈 시간표와 다음 편 미확인을 구분한다 (%s)", (count) => expect(railMarkerLabel(data, { ...row, departure_count: count, next_departure: null }, now)).toBe(count ? "다음 예정 확인 필요" : "저장 운행편 없음"));
});
