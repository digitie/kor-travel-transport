import {NextRequest} from "next/server";
import {afterEach,beforeEach,describe,expect,it,vi} from "vitest";
const auth=vi.hoisted(()=>({allowed:true,origin:true}));
vi.mock("@/lib/auth",()=>({adminSessionUser:async()=>auth.allowed?"admin":null}));
vi.mock("@/lib/origin",()=>({isAllowedOrigin:()=>auth.origin}));
import {POST} from "./route";
const request=(body:unknown,origin="https://admin.fixture")=>new NextRequest(origin+"/api/dagster/console",{method:"POST",headers:{origin,"content-type":"application/json",cookie:"fixture=value"},body:typeof body==="string"?body:JSON.stringify(body)});
beforeEach(()=>{auth.allowed=true;auth.origin=true;});afterEach(()=>vi.unstubAllGlobals());
describe("관리자 콘솔 감사 기록",()=>{
 it("재시도는 요청자·원본 실행을 run 태그와 서버 로그에 남기고 세션 값은 남기지 않는다",async()=>{
  const runId="11111111-1111-4111-8111-111111111111",requestId="33333333-3333-4333-8333-333333333333";
  const tag={key:"dagster/code_location",value:"kor-travel-transport"};
  const calls:{query:string;variables:Record<string,unknown>}[]=[];
  vi.stubGlobal("fetch",vi.fn(async(_url:unknown,init:RequestInit)=>{
   const {query,variables}=JSON.parse(String(init.body));calls.push({query,variables});
   if(query.includes("AdminDagsterCatalog"))return Response.json({data:{repositoryOrError:{__typename:"Repository",jobs:[{name:"fuel_collection_job",hasLaunchExecutionPermission:true}],schedules:[],sensors:[]},__schema:{mutationType:{fields:[{name:"launchIdempotentRun"}]}}}});
   if(query.includes("AdminDagsterOwnedRun"))return Response.json({data:{runsOrError:{__typename:"Runs",results:[{runId,jobName:"fuel_collection_job",status:"FAILURE",hasReExecutePermission:true,tags:[tag]}]}}});
   if(query.includes("AdminDagsterRequest")||query.includes("AdminDagsterActive"))return Response.json({data:{runsOrError:{__typename:"Runs",results:[]}}});
   if(query.includes("AdminDagsterLaunch"))return Response.json({data:{result:{__typename:"IdempotentLaunchRunSuccess",replayed:false,run:{runId:"22222222-2222-4222-8222-222222222222",status:"QUEUED",tags:[tag]}}}});
   throw new Error("unexpected");
  }));
  const log=vi.spyOn(console,"info").mockImplementation(()=>undefined);
  try {
   const res=await POST(request({operation:"action",action:"retry",runId,requestId}));
   expect(res.status).toBe(200);expect(await res.json()).toMatchObject({state:"accepted"});
   const launch=calls.find(call=>call.query.includes("AdminDagsterLaunch"))!;
   const tags=(launch.variables.executionParams as {executionMetadata:{tags:{key:string;value:string}[]}}).executionMetadata.tags;
   expect(tags).toEqual(expect.arrayContaining([{key:"kortravel/admin-retry-of",value:runId},{key:"kortravel/admin-actor",value:"admin"}]));
   expect(tags.some(item=>item.key==="kortravel/admin-requested-at")).toBe(false);
   const entries=log.mock.calls.map(([line])=>JSON.parse(String(line)));
   expect(entries).toEqual([expect.objectContaining({event:"transport_admin_dagster_action",actor:"admin",action:"retry",runId,requestId,state:"accepted",resultRunId:"22222222-2222-4222-8222-222222222222"})]);
   expect(JSON.stringify(entries)).not.toContain("fixture=value");
  } finally { log.mockRestore(); }
 });
 it("조회 요청은 감사 로그를 남기지 않는다",async()=>{
  vi.stubGlobal("fetch",vi.fn().mockResolvedValue(Response.json({errors:[{message:"x"}]})));
  const log=vi.spyOn(console,"info").mockImplementation(()=>undefined);
  try { expect((await POST(request({operation:"catalog"}))).status).toBe(502);expect(log).not.toHaveBeenCalled(); } finally { log.mockRestore(); }
 });
});
describe("관리자 콘솔 BFF 보호",()=>{
 it("로그인 없으면 native에 접근하지 않는다",async()=>{auth.allowed=false;const fetch=vi.fn();vi.stubGlobal("fetch",fetch);expect((await POST(request({operation:"catalog"}))).status).toBe(401);expect(fetch).not.toHaveBeenCalled();});
 it("교차출처를 거절한다",async()=>{auth.origin=false;const fetch=vi.fn();vi.stubGlobal("fetch",fetch);expect((await POST(request({operation:"catalog"}))).status).toBe(403);expect(fetch).not.toHaveBeenCalled();});
 it.each([{query:"mutation x{}"},{operation:"action",action:"launch",name:"fixture",requestId:"11111111-1111-4111-8111-111111111111",runConfigData:{}}])("임의 query/config를 보내지 않는다",async body=>{const fetch=vi.fn();vi.stubGlobal("fetch",fetch);expect((await POST(request(body))).status).toBe(422);expect(fetch).not.toHaveBeenCalled();});
 it("본문 상한을 유지한다",async()=>{const fetch=vi.fn();vi.stubGlobal("fetch",fetch);expect((await POST(request("x".repeat(4097)))).status).toBe(413);expect(fetch).not.toHaveBeenCalled();});
 it("native 원문 에러를 정적 오류로 바꾼다",async()=>{vi.stubGlobal("fetch",vi.fn().mockResolvedValue(Response.json({errors:[{message:"private-canary https://private.invalid"}]})));const res=await POST(request({operation:"catalog"}));expect(res.status).toBe(502);expect(await res.text()).not.toContain("private-canary");expect(res.headers.get("cache-control")).toContain("no-store");});
});
