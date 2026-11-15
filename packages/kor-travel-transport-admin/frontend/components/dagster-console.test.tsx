// @vitest-environment jsdom
import {act} from "react";
import {createRoot,type Root} from "react-dom/client";
import {afterEach,beforeEach,describe,expect,it,vi} from "vitest";
import {DagsterCollectionWarnings,DagsterConsoleControls,DagsterRunInspector} from "./dagster-console";
import {getConsoleCatalog,getConsoleRequestStatus,getConsoleRun,performConsoleAction} from "@/lib/dagster-console-client";
import {handleConsoleRequest} from "@/lib/dagster-console-server";
import {DAGSTER_LOCATION_NAME,DAGSTER_LOCATION_TAG_KEY} from "@/lib/dagster-scope";
import type {ConsoleActionResult,ConsoleCatalog,ConsoleRunDetail} from "@/lib/dagster-console-model";
vi.mock("@/lib/dagster-console-client",async original=>({...await original<typeof import("@/lib/dagster-console-client")>(),getConsoleCatalog:vi.fn(),getConsoleRequestStatus:vi.fn(),getConsoleRun:vi.fn(),performConsoleAction:vi.fn()}));
const id="11111111-1111-4111-8111-111111111111",other="22222222-2222-4222-8222-222222222222",jobLabel=(name:string)=>name;
const detail=(runId=id):ConsoleRunDetail=>({runId,jobName:"fixture_job",status:"SUCCESS",creationTime:1,startTime:2,endTime:3,queuedTime:1,canCancel:false,canRetry:false,steps:[],events:[],stepsSucceeded:0,stepsFailed:0,materializations:0,cursor:null,hasMore:false,stepsTruncated:false,checkedAt:"2026-11-15T00:00:00Z"});
const catalog:ConsoleCatalog={jobs:["fixture_job"],schedules:[],sensors:[],capabilities:{launch:true,cancel:true,retry:true,schedule:true,sensor:true},checkedAt:"2026-11-15T00:00:00Z"};
function deferred<T>(){let resolve!:(v:T)=>void;return {promise:new Promise<T>(done=>resolve=done),resolve:(v:T)=>resolve(v)};}
let host:HTMLDivElement,root:Root;
beforeEach(()=>{Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});host=document.createElement("div");document.body.append(host);root=createRoot(host);vi.mocked(getConsoleRun).mockReset();vi.mocked(getConsoleCatalog).mockReset();vi.mocked(performConsoleAction).mockReset();vi.mocked(getConsoleRequestStatus).mockReset();});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();});
const click=async(name:string)=>{const button=[...host.querySelectorAll("button")].find(v=>v.textContent===name);expect(button).toBeTruthy();await act(async()=>button!.click());};
describe("실행 콘솔 조회·액션 경합",()=>{
 it("선택 변경 뒤 늦은 이전 응답을 표시하지 않고 이전 조회를 취소한다",async()=>{
  const first=deferred<ConsoleRunDetail>();vi.mocked(getConsoleRun).mockReturnValueOnce(first.promise).mockResolvedValue(detail(other));
  await act(async()=>root.render(<DagsterRunInspector key={id} runId={id} jobLabel={jobLabel}/>));const signal=vi.mocked(getConsoleRun).mock.calls[0][2];
  await act(async()=>root.render(<DagsterRunInspector key={other} runId={other} jobLabel={jobLabel}/>));expect(signal?.aborted).toBe(true);
  await act(async()=>first.resolve({...detail(),status:"FAILURE"}));expect(host.textContent).toContain("실행 완료");expect(host.textContent).not.toContain("실행 실패");
 });
 it("상세 해제 시 해당 조회만 취소한다",async()=>{vi.mocked(getConsoleRun).mockReturnValue(new Promise(()=>undefined));await act(async()=>root.render(<DagsterRunInspector runId={id} jobLabel={jobLabel}/>));const signal=vi.mocked(getConsoleRun).mock.calls[0][2];await act(async()=>root.render(null));expect(signal?.aborted).toBe(true);});
 it("경고 목록은 로그 선조회 없이 부분 완료를 별도 표시한다",async()=>{const onSelect=vi.fn();await act(async()=>root.render(<DagsterCollectionWarnings runs={[{runId:id,jobName:"fixture_job",tags:[{key:"kortravel/collection-outcome",value:"partial"}]}]} jobLabel={jobLabel} onSelectRun={onSelect}/>));expect(host.textContent).toContain("자료 확인 필요 실행 1건");expect(host.textContent).toContain("모든 자료의 최신화를 보장하지 않습니다");expect(getConsoleRun).not.toHaveBeenCalled();await act(async()=>host.querySelector("button")!.click());expect(onSelect).toHaveBeenCalledWith(id);});
 it("정상 취소는 확인 뒤 한번만 요청한다",async()=>{vi.mocked(getConsoleRun).mockResolvedValue({...detail(),status:"STARTED",canCancel:true});vi.mocked(performConsoleAction).mockResolvedValue({state:"accepted",message:"정상 취소 요청"});await act(async()=>root.render(<DagsterRunInspector runId={id} jobLabel={jobLabel}/>));await click("실행 취소");expect(performConsoleAction).not.toHaveBeenCalled();await click("취소 요청 보내기");expect(performConsoleAction).toHaveBeenCalledTimes(1);expect(vi.mocked(performConsoleAction).mock.calls[0][0]).toMatchObject({action:"cancel",runId:id});});
 it("UNKNOWN은 새 실행을 막고 명시적 확인·복구만 같은 요청을 재사용한다",async()=>{vi.mocked(getConsoleCatalog).mockResolvedValue(catalog);vi.mocked(performConsoleAction).mockResolvedValueOnce({state:"unknown",message:"예약 미확인"}).mockResolvedValue({state:"accepted",message:"같은 요청 확인"});vi.mocked(getConsoleRequestStatus).mockResolvedValue({state:"unknown",message:"예약 미확인"});await act(async()=>root.render(<DagsterConsoleControls jobLabel={jobLabel}/>));await click("지금 실행");expect(performConsoleAction).toHaveBeenCalledTimes(1);const launch=[...host.querySelectorAll("button")].find(v=>v.textContent==="지금 실행");expect(launch?.disabled).toBe(true);await click("요청 상태 확인");expect(performConsoleAction).toHaveBeenCalledTimes(1);await click("같은 요청 예약 확인·복구");expect(performConsoleAction).toHaveBeenCalledTimes(2);expect(vi.mocked(performConsoleAction).mock.calls[0][0]).toEqual(vi.mocked(performConsoleAction).mock.calls[1][0]);expect(getConsoleRequestStatus).toHaveBeenCalledTimes(2);});

 it("실패 실행은 현재 기본 설정으로 같은 작업의 재실행 명령을 보낸다",async()=>{vi.mocked(getConsoleRun).mockResolvedValue({...detail(),status:"FAILURE",canRetry:true});vi.mocked(performConsoleAction).mockResolvedValue({state:"accepted",message:"재실행 예약"});await act(async()=>root.render(<DagsterRunInspector runId={id} jobLabel={jobLabel}/>));expect(host.textContent).toContain("현재 기본 설정");await click("같은 작업 다시 실행");expect(vi.mocked(performConsoleAction).mock.calls[0][0]).toMatchObject({action:"retry",runId:id});expect(vi.mocked(performConsoleAction).mock.calls[0][0]).not.toHaveProperty("runConfigData");});

 it("화면 표시 구독을 재등록하지 않고 최신 선택 실행을 다시 조회한다",async()=>{
  const add=vi.spyOn(document,"addEventListener"),remove=vi.spyOn(document,"removeEventListener"),visibility=vi.spyOn(document,"visibilityState","get").mockReturnValue("visible");
  vi.mocked(getConsoleRun).mockImplementation(async runId=>({...detail(runId),status:"STARTED"}));
  try{
   await act(async()=>root.render(<DagsterRunInspector runId={id} jobLabel={jobLabel}/>));
   await act(async()=>root.render(<DagsterRunInspector runId={other} jobLabel={jobLabel}/>));
   expect(add.mock.calls.filter(([name])=>name==="visibilitychange")).toHaveLength(1);expect(remove.mock.calls.filter(([name])=>name==="visibilitychange")).toHaveLength(0);
   await act(async()=>document.dispatchEvent(new Event("visibilitychange")));
   expect(vi.mocked(getConsoleRun).mock.calls.at(-1)?.[0]).toBe(other);
   await act(async()=>root.render(null));expect(remove.mock.calls.filter(([name])=>name==="visibilitychange")).toHaveLength(1);
  }finally{add.mockRestore();remove.mockRestore();visibility.mockRestore();}
 });

 it.each(["launch","retry"] as const)("%s의 실제 NOT_STARTED 예약은 경쟁 실행·권한 변경 뒤에도 같은 ID로 복구한다",async mode=>{
  let exists=false,competing=false,reexecuteAllowed=true;
  const reserved={runId:id,jobName:"fixture_job",status:"NOT_STARTED"},nativeCommands:Array<Record<string,unknown>>=[];
  const rows=(values:unknown[])=>({runsOrError:{__typename:"Runs",results:values}});
  const graphql=vi.fn(async(query:string,variables:Record<string,unknown>):Promise<Record<string,unknown>>=>{
   if(query.includes("AdminDagsterCatalog"))return {repositoryOrError:{__typename:"Repository",jobs:[{name:"fixture_job",hasLaunchExecutionPermission:true}],schedules:[],sensors:[]},__schema:{mutationType:{fields:[{name:"launchIdempotentRun"}]}}};
   if(query.includes("AdminDagsterOwnedRun"))return rows([{runId:other,jobName:"fixture_job",status:"FAILURE",hasReExecutePermission:reexecuteAllowed}]);
   if(query.includes("AdminDagsterRequest"))return rows(exists?[reserved]:[]);
   if(query.includes("AdminDagsterActive"))return rows([...(exists?[reserved]:[]),...(competing?[{runId:other,jobName:"fixture_job",status:"STARTED"}]:[])]);
   if(query.includes("AdminDagsterLaunch")){nativeCommands.push(structuredClone(variables));exists=true;reserved.status=nativeCommands.length===1?"NOT_STARTED":"QUEUED";return {result:{__typename:"IdempotentLaunchRunSuccess",replayed:nativeCommands.length>1,run:{...reserved,tags:[{key:DAGSTER_LOCATION_TAG_KEY,value:DAGSTER_LOCATION_NAME}]}}};}
   throw new Error("예상하지 않은 고정 연산");
  });
  vi.mocked(getConsoleCatalog).mockResolvedValue(catalog);vi.mocked(getConsoleRun).mockResolvedValue({...detail(other),status:"FAILURE",canRetry:true});
  vi.mocked(performConsoleAction).mockImplementation(async command=>await handleConsoleRequest(command,graphql) as ConsoleActionResult);
  vi.mocked(getConsoleRequestStatus).mockImplementation(async requestId=>await handleConsoleRequest({operation:"requestStatus",requestId},graphql) as ConsoleActionResult);
  const uuid=vi.spyOn(crypto,"randomUUID").mockReturnValue("33333333-3333-4333-8333-333333333333");
  try{
   await act(async()=>root.render(mode==="launch"?<DagsterConsoleControls jobLabel={jobLabel}/>:<DagsterRunInspector runId={other} jobLabel={jobLabel}/>));
   await click(mode==="launch"?"지금 실행":"같은 작업 다시 실행");expect(nativeCommands).toHaveLength(1);const original=vi.mocked(performConsoleAction).mock.calls[0][0];
   if(mode==="launch")competing=true;else reexecuteAllowed=false;
   await click("같은 요청 예약 확인·복구");expect(nativeCommands).toHaveLength(1);expect([...host.querySelectorAll("button")].some(button=>button.textContent==="같은 요청 예약 확인·복구")).toBe(true);
   expect([...host.querySelectorAll("button")].find(button=>button.textContent===(mode==="launch"?"지금 실행":"같은 작업 다시 실행"))?.disabled).toBe(true);
   await click("요청 상태 확인");expect(nativeCommands).toHaveLength(1);competing=false;reexecuteAllowed=true;
   await click("같은 요청 예약 확인·복구");expect(nativeCommands).toHaveLength(2);expect(nativeCommands[1]).toEqual(nativeCommands[0]);
   for(const [command]of vi.mocked(performConsoleAction).mock.calls)expect(command).toEqual(original);
   expect(uuid).toHaveBeenCalledTimes(1);expect([...host.querySelectorAll("button")].some(button=>button.textContent==="같은 요청 예약 확인·복구")).toBe(false);
  }finally{uuid.mockRestore();}
 });
});
