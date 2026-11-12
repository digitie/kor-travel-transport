// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, expect, test, vi } from "vitest";
import type { Place } from "@/lib/journey";
vi.mock("./general-rail-journey", () => ({ GeneralRailJourney: () => <p>새 예정 시간표 유지</p> }));
import { GeneralRailStationDetail } from "./general-rail-station-detail";
const station: Place = {id:1,kind:"rail_station",source:"korail_public_guide",provider_id:"역/1 &?=",name:"시험역",address:"시험시 역길 1",phone:"+82 (2) 123-4567",longitude:127.1,latitude:37.3,line_names:["시험선"],facilities:[],prices:[],updated_at:"2026-11-12T00:00:00Z"};
beforeEach(() => Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true}));

test("새 시간표 상세와 코레일 공식 안내·정제된 전화 연결을 함께 보존한다", () => {
 const html=renderToStaticMarkup(<GeneralRailStationDetail station={station}/>);
 const doc=new DOMParser().parseFromString(html,"text/html");
 const official=[...doc.querySelectorAll("a")].find(a=>a.textContent?.includes("공식 역 안내"));
 expect(official?.getAttribute("href")).toBe("https://www.korail.com/ticket/train/stationGuide/station/view?stationSeq="+encodeURIComponent(station.provider_id!));
 expect(official?.getAttribute("target")).toBe("_blank");expect(official?.getAttribute("rel")).toContain("noreferrer");
 expect(doc.querySelector('a[href="tel:+8221234567"]')?.textContent).toBe(station.phone);
 expect(doc.body.textContent).toContain("새 예정 시간표 유지");
});
test("좌표가 있는 주소의 지도 이동을 보존하고 좌표 없는 주소 이동은 막는다", async () => {
 const show=vi.fn();const host=document.createElement("div");document.body.append(host);const root=createRoot(host);
 try{
  await act(async()=>root.render(<GeneralRailStationDetail station={station} onShowMap={show}/>));
  const button=()=>host.querySelector<HTMLButtonElement>(".station-address")!;
  expect(button()).not.toBeNull();expect(button().disabled).toBe(false);
  await act(async()=>button().click());expect(show).toHaveBeenCalledTimes(1);
  await act(async()=>root.render(<GeneralRailStationDetail station={{...station,longitude:null,latitude:null}} onShowMap={show}/>));
  expect(button().disabled).toBe(true);await act(async()=>button().click());expect(show).toHaveBeenCalledTimes(1);
 }finally{await act(async()=>root.unmount());host.remove();}
});
test("없는 provider와 연락처를 가짜 외부 링크로 만들지 않는다",()=>{
 const doc=new DOMParser().parseFromString(renderToStaticMarkup(<GeneralRailStationDetail station={{...station,provider_id:null,phone:null}}/>),"text/html");
 expect(doc.querySelector('a[href^="tel:"]')).toBeNull();expect(doc.querySelector('a[href*="stationSeq="]')).toBeNull();
});
