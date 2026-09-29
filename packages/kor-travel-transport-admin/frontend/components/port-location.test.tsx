import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { PlaceDetails } from "./journey-controls";
import type { Place } from "@/lib/journey";

const port: Place = { id: 1, kind: "ferry_port", source: "data_go_kr_maritime", provider_id: "SEA10100", name: "인천",
  latitude: 37.4557, longitude: 126.598, location_source: "komsa_port_call", prices: [], line_names: [], facilities: [], updated_at: "2026-09-28T00:00:00Z" };

describe("항구 위치 출처 안내", () => {
  it("공식 기항지 위치를 항로 안내 점이라고 표시하지 않는다", () => {
    const html = renderToStaticMarkup(<PlaceDetails place={port} />);
    expect(html).toContain("한국해양교통안전공단 기항지 위치");
    expect(html).not.toContain("항만 안내 지점입니다");
    expect(html).toContain("승선 부두·탑승구는 운항사에 확인");
    expect(html).toContain("항구 코드 SEA10100");
  });
  it("좌표 없는 항구도 운항 목록 이용을 안내한다", () => {
    const html = renderToStaticMarkup(<PlaceDetails place={{ ...port, latitude: null, longitude: null }} />);
    expect(html).toContain("좌표 미등록");
    expect(html).not.toContain("한국해양교통안전공단 기항지 위치");
  });
  it("항구 코드가 없는 경우 이름으로 코드를 추정하지 않는다", () => {
    const html = renderToStaticMarkup(<PlaceDetails place={{ ...port, provider_id: null }} />);
    expect(html).toContain("항구 코드 미제공");
  });
  it("지도 검색 좌표는 공식 기항지와 구분하고 승선 위치 확정을 피한다", () => {
    const html = renderToStaticMarkup(<PlaceDetails place={{ ...port, location_source: "vworld_place" }} />);
    expect(html).toContain("지도 검색에서 확인한 항만 시설");
    expect(html).toContain("실제 승선 장소는 운항사에 확인");
  });
  it("버스 터미널 코드와 좌표 검증 상태를 표시한다", () => {
    const html = renderToStaticMarkup(<PlaceDetails place={{ ...port, kind: "bus_terminal", provider_id: "NAI2551901", location_source: "vworld_place" }} />);
    expect(html).toContain("터미널 코드 NAI2551901");
    expect(html).toContain("VWorld 시설 검색으로 확인한 터미널 위치");
    expect(html).toContain("실제 승차 홈은 운송사에 확인");
  });
});
