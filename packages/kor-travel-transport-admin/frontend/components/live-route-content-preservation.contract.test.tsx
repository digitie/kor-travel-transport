// @vitest-environment jsdom
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
const api=vi.hoisted(()=>({get:vi.fn()}));
vi.mock("next/navigation",()=>({usePathname:()=>"/rail/timetable"}));
vi.mock("@/lib/journey",async original=>({...await original<typeof import("@/lib/journey")>(),transportGet:api.get}));
vi.mock("@/lib/journey-hooks",()=>({useSeoulToday:()=>"2026-10-31",useNearbyPosition:()=>({position:null,positionError:null,locating:false,locate:()=>{}})}));
vi.mock("./transport-map",()=>({TransportMap:({toolbar,feedback,listContent,details}: {toolbar?:ReactNode;feedback?:ReactNode;listContent?:ReactNode;details?:ReactNode})=><section aria-label="지도 경계 모형">{toolbar}{feedback}{listContent}{details}</section>}));
const station={id:17,kind:"rail_station",source:"kric_station_codes",provider_id:"S/01/001",name:"성복",subtitle:"공식기관",line_names:["신분당선"],prices:[],facilities:[],longitude:null,latitude:null,updated_at:"2026-10-31T00:00:00Z"};
let host:HTMLDivElement,root:Root;
beforeEach(()=>{
 Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});
 vi.stubGlobal("ResizeObserver",class{observe(){}unobserve(){}disconnect(){}});
 vi.stubGlobal("matchMedia",()=>({matches:false,addEventListener(){},removeEventListener(){}}));
 api.get.mockReset().mockImplementation(async(path:string)=>{
  const u=new URL(path,"http://fixture");
  if(u.pathname==="/transport/parking-lots")return {generated_at:"2026-10-31T00:00:00Z",collection:{source:"datagokr_parking_lots",last_success_at:null,failed:false,stale:true,last_attempt_failed:false},items:[],has_more:false,next_cursor:null};
  if(u.pathname==="/transport/rail/stations")return {items:[station]};
  if(u.pathname==="/transport/rail/stations/17/timetable")return {generated_at:"2026-10-31T00:00:00Z",day_code:"7",basis:"calendar",items:[{place_id:null,code_id:17,station_name:"성복",line_name:"신분당선",status:"stored",stale:false,collected_at:"2026-10-31T00:00:00Z",items:[{train_number:"early",departure_time:"090400",arrival_time:null,origin_name:"출발역",destination_name:"광교"},{train_number:"late",departure_time:"231200",arrival_time:null,origin_name:"출발역",destination_name:"광교"}]}]};
  if(u.pathname.endsWith("/catalog"))return {fetched_at:"2026-10-31T00:00:00Z",stale:false,cities:[{code:"11",name:"서울"}],train_classes:[]};
  if(u.pathname.endsWith("/stations"))return {fetched_at:"2026-10-31T00:00:00Z",stale:false,items:[{station_id:"NAT-SEOUL",station_name:"서울",city_name:"서울"}]};
  throw Error("unexpected readonly fixture endpoint");
 });host=document.createElement("div");document.body.append(host);root=createRoot(host);
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.unstubAllGlobals();});
async function page(path:string,params?:Record<string,string>){const routeModule=await import(new URL(path,import.meta.url).pathname);return routeModule.default({searchParams:Promise.resolve(params??{})});}
test("일반 주차장 주소는 공항 화면이 아니라 정적 기준정보와 검색·미완수집 안내를 연다",async()=>{
 const node=await page("../app/parking-lots/page");await act(async()=>root.render(node));
 expect(host.querySelector("h1")?.textContent).toBe("일반 주차장");expect(host.querySelector('form[aria-label="일반 주차장 검색"]')).not.toBeNull();
 expect(host.textContent).toContain("실시간 잔여면은 제공하지 않습니다");expect(host.textContent).toContain("완료된 주차장 기준정보가 아직 없습니다");
 expect(api.get.mock.calls.some(([path])=>String(path).startsWith("transport/parking-lots?"))).toBe(true);
 expect(api.get.mock.calls.some(([path])=>String(path).includes("parking/current"))).toBe(false);
});
test("metro station/view 딥링크는 공식 코드 저장표의 첫막을 곧바로 열고 전체표로 전환된다",async()=>{
 const node=await page("../app/rail/timetable/page",{mode:"metro",station:"17",view:"ends"});await act(async()=>root.render(node));
 expect(host.querySelector("h1")?.textContent).toBe("시간표 조회");expect(host.querySelector('[aria-label="시간표 종류"]')).not.toBeNull();
 expect(host.querySelector('[aria-label="저장표 첫차 막차"]')?.textContent).toContain("09:04 ~ 23:12");
 expect(api.get.mock.calls.some(([path])=>String(path)==="transport/rail/stations/17/timetable?")).toBe(true);
 await act(async()=>[...host.querySelectorAll("button")].find(node=>node.textContent==="전체 시간표")!.click());expect(host.querySelector('[aria-label="전체 예정 시간표"]')?.textContent).toContain("23:12");
});
test.each(["departure","arrival"])("일반철도 guide %s 딥링크는 안내명을 검색의도로만 전달하고 provider ID를 운행 역코드로 확정하지 않는다",async role=>{
 const node=await page("../app/rail/timetable/page",{mode:"general",guide_id:"GUIDE-NOT-A-TIMETABLE-ID",guide_name:"서울",guide_role:role});await act(async()=>root.render(node));
 const label=[...host.querySelectorAll("label")].find(node=>node.textContent===(role==="departure"?"출발역":"도착역"))!;expect(label).toBeDefined();
 const input=document.getElementById(label.htmlFor) as HTMLInputElement;expect(input.value).toBe("서울");
 const submit=[...host.querySelectorAll<HTMLButtonElement>("button")].find(node=>node.textContent?.trim()==="예정 시간표 조회")!;expect(submit.disabled).toBe(true);
 expect(api.get.mock.calls.some(([path])=>String(path).includes("/timetable?"))).toBe(false);
 expect(host.textContent).toContain("후보를 직접 확인해 선택");
});
