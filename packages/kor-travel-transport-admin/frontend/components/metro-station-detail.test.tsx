// @vitest-environment jsdom
import {act} from "react";
import {createRoot} from "react-dom/client";
import {afterEach,beforeEach,expect,test,vi} from "vitest";
import {renderToStaticMarkup} from "react-dom/server";
import type {Place} from "@/lib/journey";
import {MetroStationDetail,MetroStationSummary,type MetroTimetableResponse} from "./metro-station-detail";
const api=vi.hoisted(()=>({get:vi.fn()}));
vi.mock("@/lib/journey",async original=>({...await original<typeof import("@/lib/journey")>(),transportGet:api.get}));
const station={id:17,kind:"rail_station",source:"kric_station_codes",provider_id:"S/01/001",name:"성복",subtitle:"공식기관",line_names:["신분당선"],prices:[],facilities:[],longitude:null,latitude:null,updated_at:"2026-10-31T00:00:00Z"} as Place;
const row=(time:string,destination:string)=>({train_number:time,departure_time:time,arrival_time:null,origin_name:"출발역",destination_name:destination});
const data:MetroTimetableResponse={generated_at:"2026-10-31T00:00:00Z",day_code:"7",basis:"calendar",items:[{place_id:null,code_id:17,station_name:"성복",line_name:"신분당선",status:"stored",stale:false,collected_at:"2026-10-31T00:00:00Z",items:[row("090300","신사"),row("090400","광교"),row("091200","광교")]}]};
beforeEach(()=>{Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});api.get.mockReset();});
afterEach(()=>vi.unstubAllGlobals());
test("실제 행선지별 예정 카드를 만들고 실시간·노선순서·출구를 만들어 내지 않는다",()=>{
 const html=renderToStaticMarkup(<MetroStationSummary station={station} data={data} period="" onPeriod={()=>{}} refresh={()=>{}}/>);
 expect(html).toContain("신사행");expect(html).toContain("광교행");expect(html).toContain("3분 후 예정");expect(html).toContain("12분 후 예정");
 expect(html).toContain("실시간 도착 정보가 아닙니다");expect(html).not.toContain("노선도");expect(html).not.toContain("출구정보");expect(html).toContain("확인된 편의시설 정보가 아직 없습니다");
 expect(html.indexOf("전체 시간표")).toBeLessThan(html.indexOf("역 편의정보"));
 for(const props of [{loading:true},{failed:true},{data:{...data,basis:"selected_period" as const}},{data:{...data,items:[{...data.items[0],stale:true}]}}]){
  expect(renderToStaticMarkup(<MetroStationSummary station={station} data={data} period="" onPeriod={()=>{}} refresh={()=>{}} {...props}/>)).not.toContain("분 후 예정");
 }
});
test("코드 ID로 조회하고 전체 시간표·첫차막차를 펼친다",async()=>{
 api.get.mockResolvedValue(data);const container=document.createElement("div");document.body.append(container);const root=createRoot(container);
 try{
  await act(async()=>root.render(<MetroStationDetail station={station}/>));
  expect(api.get.mock.calls[0][0]).toBe("transport/rail/stations/17/timetable?");
  await act(async()=>[...container.querySelectorAll("button")].find(b=>b.textContent?.includes("전체 시간표"))!.click());
  expect(container.querySelector('[aria-label="전체 예정 시간표"]')?.textContent).toContain("09:12");
  await act(async()=>[...container.querySelectorAll("button")].find(b=>b.textContent==="첫차·막차")!.click());
  expect(container.querySelector('[aria-label="저장표 첫차 막차"]')?.textContent).toContain("09:04 ~ 09:12");
 }finally{await act(async()=>root.unmount());container.remove();}
});

test("등록된 편의시설의 상세와 주소·전화만 표시한다",()=>{
 const html=renderToStaticMarkup(<MetroStationSummary station={{...station,facilities:["스크린도어","유실물 취급","환승 가능"],address:"시험시 시험로 1",phone:"02-1234-5678"}} data={data} period="" onPeriod={()=>{}} refresh={()=>{}}/>);
 expect(html).toContain("승강장 스크린도어 설치가 확인");expect(html).toContain("유실물 취급이 등록");expect(html).toContain("시험시 시험로 1");expect(html).toContain('href="tel:0212345678"');
 expect(html).not.toContain("엘리베이터 설치");expect(html).not.toContain("노선도");
});
