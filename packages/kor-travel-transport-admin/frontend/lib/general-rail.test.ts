import {expect,test} from "vitest";
import {uniqueStationByName} from "./general-rail";

test("제공기관의 역명이 유일할 때만 지도 출발역을 연결한다",()=>{
  const seoul={station_id:"NAT010000",station_name:"서울"};
  expect(uniqueStationByName([seoul],"서울역")).toBe(seoul);
  expect(uniqueStationByName([seoul,{station_id:"OTHER",station_name:"서울역"}],"서울")).toBeNull();
  expect(uniqueStationByName([seoul],"미제공역")).toBeNull();
});
