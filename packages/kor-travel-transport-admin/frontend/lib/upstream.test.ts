import { describe, expect, it } from "vitest";

import { transportUpstreamUrl } from "./upstream";

describe("transport upstream URL", () => {
  it("허용한 transport read endpoint와 반복 query를 그대로 만든다", () => {
    const url = transportUpstreamUrl(["transport", "highways", "traffic"], new URLSearchParams([["route_no", "1"], ["route_no", "10"]]));
    expect(url?.toString()).toContain("/v1/transport/highways/traffic?route_no=1&route_no=10");
  });
  it("admin write endpoint는 upstream URL을 만들지 않는다", () => {
    expect(transportUpstreamUrl(["admin", "collect"], new URLSearchParams())).toBeNull();
  });
});

describe("새 지역 유가와 공식 코드 역 조회의 운영 중계",()=>{
 it.each(["transport/fuel/regions","transport/rail/stations","transport/rail/stations/274/timetable"])("%s를 내부 읽기 API에 연결한다",path=>{
  expect(transportUpstreamUrl(path.split("/"),new URLSearchParams("day_code=7"))?.pathname).toBe(`/v1/${path}`);
 });
 it.each(["transport/rail/stations/0/timetable","transport/rail/stations/274/delete","transport/rail/stations/admin/timetable"])("%s는 허용하지 않는다",path=>{
  expect(transportUpstreamUrl(path.split("/"),new URLSearchParams())).toBeNull();
 });
});
