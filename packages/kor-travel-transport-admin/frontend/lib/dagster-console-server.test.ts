import { describe, expect, it, vi } from "vitest";
import { DAGSTER_LOCATION_NAME } from "./dagster-scope";
import { consoleRequestId, handleConsoleRequest, parseConsoleRequest, sanitizeConsoleEvents, sanitizeConsoleRun } from "./dagster-console-server";

const id="11111111-1111-4111-8111-111111111111", other="22222222-2222-4222-8222-222222222222", requestId="33333333-3333-4333-8333-333333333333";
const tag=()=>({key:String(DAGSTER_LOCATION_NAME)==="kor-travel-transport"?"dagster/code_location":".dagster/repository",value:String(DAGSTER_LOCATION_NAME)==="kor-travel-transport"?DAGSTER_LOCATION_NAME:`__repository__@${DAGSTER_LOCATION_NAME}`});
const rows=(values:unknown[]=[])=>({runsOrError:{__typename:"Runs",results:values}});
const run=(status="STARTED")=>({runId:id,jobName:"fixture_job",status,creationTime:100,startTime:110,endTime:null,canTerminate:true,hasTerminatePermission:true,hasReExecutePermission:true,stats:{stepsSucceeded:1,stepsFailed:0,materializations:1,enqueuedTime:101},executionPlan:{steps:[{key:"fetch"},{key:"publish"}]},stepStats:[{stepKey:"fetch",status:"SUCCESS",startTime:110,endTime:111,attempts:[{startTime:110,endTime:111}]}]});
function fixture() {
  let prior:unknown[]=[];let active:unknown[]=[];let nextRun=run();let eventFails=false;let launchFails=false;let launchForeign=false;
  const catalog={repositoryOrError:{__typename:"Repository",jobs:[{name:"fixture_job",hasLaunchExecutionPermission:true},{name:"__ASSET_JOB",hasLaunchExecutionPermission:true},{name:"private_job",hasLaunchExecutionPermission:false}],schedules:[{name:"fixture_schedule",pipelineName:"fixture_job",cronSchedule:"*/5 * * * *",defaultStatus:"RUNNING",scheduleState:{id:"owned-schedule-id",status:"STOPPED",hasStartPermission:true,hasStopPermission:true}}],sensors:[{name:"fixture_sensor",defaultStatus:"STOPPED",sensorState:{id:"owned-sensor-id",status:"RUNNING",hasStartPermission:true,hasStopPermission:true}}]},__schema:{mutationType:{fields:["launchIdempotentRun","terminateRun","startSchedule","stopRunningSchedule","startSensor","stopSensor"].map(name=>({name}))}}};
  const graphql=vi.fn(async(query:string,variables:Record<string,unknown>):Promise<Record<string,unknown>>=>{
    if(query.includes("AdminDagsterCatalog"))return catalog;
    if(query.includes("AdminDagsterRequest"))return rows(prior);
    if(query.includes("AdminDagsterActive"))return rows(active);
    if(query.includes("AdminDagsterEvents")){if(eventFails)throw new Error("private-provider-url");return rows([{...nextRun,eventConnection:{events:[],hasMore:false,cursor:"done"}}]);}
    if(query.includes("query AdminDagsterRun")||query.includes("AdminDagsterOwnedRun"))return rows(nextRun?[nextRun]:[]);
    if(query.includes("AdminDagsterLaunch")){
      if(launchFails)throw new Error("private-upstream-message");
      return {result:{__typename:"IdempotentLaunchRunSuccess",replayed:false,run:{runId:other,status:"QUEUED",tags:launchForeign?[{key:"foreign",value:"foreign"}]:[tag()]}}};
    }
    if(query.includes("AdminDagsterCancel"))return {result:{__typename:"TerminateRunSuccess",run:{runId:id,status:"CANCELING"}}};
    if(query.includes("AdminDagsterStartSchedule")||query.includes("AdminDagsterStopSchedule"))return {result:{__typename:"ScheduleStateResult",scheduleState:{status:query.includes("Start")?"RUNNING":"STOPPED"}}};
    if(query.includes("AdminDagsterStartSensor"))return {result:{__typename:"Sensor",sensorState:{status:"RUNNING"}}};
    if(query.includes("AdminDagsterStopSensor"))return {result:{__typename:"StopSensorMutationResult",instigationState:{status:"STOPPED"}}};
    throw new Error(`unexpected test query ${variables}`);
  });
  return {graphql,catalog,setPrior:(value:unknown[])=>{prior=value;},setActive:(value:unknown[])=>{active=value;},setRun:(value:ReturnType<typeof run>|null)=>{nextRun=value as ReturnType<typeof run>;},eventFailure:()=>{eventFails=true;},launchFailure:()=>{launchFails=true;},foreignLaunch:()=>{launchForeign=true;}};
}

describe("관리자 고정 명령·범위",()=>{
  it.each([
    {operation:"catalog",query:"mutation{}"},{operation:"detail",runId:id,filter:{tags:[]}},
    {operation:"action",action:"launch",name:"fixture_job",requestId,runConfigData:{}},
    {operation:"action",action:"cancel",runId:"foreign-id",requestId},
    {operation:"action",action:"stopSensor",name:"../../foreign",requestId},
    {operation:"requestStatus",requestId:"invalid"},{operation:"detail",runId:id,cursor:"x".repeat(513)},
  ])("브라우저의 임의 query/config/scope/잘못된 식별자를 거부한다",value=>{expect(parseConsoleRequest(value)).toBeNull();});
  it("요청 UUID는 location별로 결정적으로 분리한다",()=>{
    expect(consoleRequestId(requestId)).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    expect(consoleRequestId(requestId.toUpperCase())).toBe(consoleRequestId(requestId));expect(consoleRequestId(requestId)).not.toBe(requestId);
  });
  it("실행 가능한 명시 job과 서버 권한만 catalog로 보낸다",async()=>{
    const f=fixture();const result=await handleConsoleRequest({operation:"catalog"},f.graphql);
    expect(result).toMatchObject({jobs:["fixture_job"],capabilities:{launch:true,cancel:true,retry:true,schedule:true,sensor:true}});
    expect(f.graphql.mock.calls[0][1]).toEqual({selector:{repositoryLocationName:DAGSTER_LOCATION_NAME,repositoryName:"__repository__"}});
    expect(JSON.stringify(result)).not.toContain("owned-schedule-id");
  });
  it("scope에서 찾지 못한 run은 상세·취소를 조회/실행하지 않는다",async()=>{
    const f=fixture();f.setRun(null);
    await expect(handleConsoleRequest({operation:"detail",runId:id},f.graphql)).rejects.toMatchObject({status:404});
    await expect(handleConsoleRequest({operation:"action",action:"cancel",runId:id,requestId},f.graphql)).rejects.toMatchObject({status:404});
    expect(f.graphql.mock.calls.some(([query])=>/^\s*mutation\b/.test(query))).toBe(false);
    for(const [query,variables]of f.graphql.mock.calls.filter(([query])=>query.includes("OwnedRun")||query.includes("query AdminDagsterRun"))){expect(query).toContain("$filter");expect(variables.filter).toMatchObject({runIds:[id],tags:[tag()]});}
  });
});

describe("실행 상세·자료 경고",()=>{
  it.each(["QUEUED","STARTED","SUCCESS","FAILURE","CANCELED"])("%s도 현재 단계와 시간을 조회한다",async state=>{
    const f=fixture();f.setRun(run(state));const result=await handleConsoleRequest({operation:"detail",runId:id},f.graphql);
    expect(result).toMatchObject({runId:id,status:state,steps:[{key:"fetch",status:"SUCCESS",attempts:1},{key:"publish",status:"NOT_STARTED"}]});
    expect(f.graphql).toHaveBeenCalledTimes(2);
  });
  it("이벤트 실패는 이미 읽은 단계 상태를 실패시키지 않는다",async()=>{
    const f=fixture();f.eventFailure();const result=await handleConsoleRequest({operation:"detail",runId:id},f.graphql);
    expect(result).toMatchObject({stepsSucceeded:1,events:[{kind:"UNAVAILABLE",warning:true}]});expect(JSON.stringify(result)).not.toContain("private-provider-url");
  });
  it("진행 상태만 갱신하면 이벤트를 다시 전수 조회하지 않는다",async()=>{
    const f=fixture();await handleConsoleRequest({operation:"detail",runId:id,includeEvents:false},f.graphql);expect(f.graphql).toHaveBeenCalledTimes(1);
  });
  it("부분완료·캐시 지연·안전한 숫자를 표시하고 원문은 제거한다",()=>{
    const secret="fixture-console-private-value";
    const events=sanitizeConsoleEvents([{__typename:"ExecutionStepOutputEvent",timestamp:"1780000000000",stepKey:"publish",message:secret,metadataEntries:[
      {label:"status",text:"partial_success"},{label:"collection_outcome",text:"partial"},{label:"cache_refresh_failed",boolValue:true},{label:"previous_data_preserved",boolValue:true},{label:"snapshot_count",intValue:100},{label:"raw",text:secret},{label:"error_code",text:"DERIVED_CACHE_DEFERRED"},
    ]},{__typename:"LogMessageEvent",message:`kma_collection_progress run_id=fixture counts={'fetch_ms': 12, 'published_values': 200} ${secret}`,timestamp:"1780000000000"}]);
    expect(events[0]).toMatchObject({warning:true,counts:{snapshot_count:100}});expect(events[0].detail).toContain("정상 저장분 보존");expect(events[0].detail).toContain("캐시");
    expect(events[1]).toMatchObject({title:"KMA 처리 진행",counts:{fetch_ms:12,published_values:200}});
    expect(JSON.stringify(events)).not.toContain(secret);
  });
  it("격리 행이 있는 부분 성공은 고정 사유와 격리 행 수를 보여 준다",()=>{
    const events=sanitizeConsoleEvents([{__typename:"ExecutionStepOutputEvent",timestamp:"1780000000000",stepKey:"collect_highway_transport",metadataEntries:[
      {label:"status",text:"partial_success"},{label:"collection_outcome",text:"partial"},{label:"error_code",text:"INVALID_ROWS_ISOLATED"},
      {label:"isolated_rows",intValue:2},{label:"received_rows",intValue:8251},{label:"invalid_rows",intValue:2},{label:"traffic_snapshot_count",intValue:8249},
    ]}]);
    expect(events[0]).toMatchObject({warning:true,counts:{isolated_rows:2,received_rows:8251,invalid_rows:2,traffic_snapshot_count:8249}});
    expect(events[0].detail).toContain("INVALID_ROWS_ISOLATED");expect(events[0].detail).toContain("격리");expect(events[0].detail).not.toContain("UNKNOWN_FAILURE");
  });
  it("수집 run 꼬리의 기준정보 본문 준비 부분 완료는 미등록 오류·저장 실패로 보이지 않는다",()=>{
    const events=sanitizeConsoleEvents([{__typename:"ExecutionStepOutputEvent",timestamp:"1780000000000",stepKey:"prepare_reference_exports",metadataEntries:[
      {label:"reference_status",text:"failed"},{label:"collection_outcome",text:"partial"},{label:"error_code",text:"REFERENCE_EXPORT_FAILED"},
      {label:"previous_data_preserved",boolValue:true},{label:"failed_kinds",text:"rail-stations-v1,ferry-ports-v1"},
    ]}]);
    expect(events[0].detail).toContain("REFERENCE_EXPORT_FAILED");expect(events[0].detail).toContain("기준정보 export 본문 준비");
    expect(events[0].detail).toContain("준비 실패 종류: 철도역, 여객선 터미널");expect(events[0].detail).toContain("일부 자료 미완료 · 정상 자료 유지");
    expect(events[0].detail).not.toContain("UNKNOWN_FAILURE");expect(events[0].detail).not.toContain("저장 결과: 실패");expect(events[0].detail).not.toContain("자료 수집 실패");
  });
  it("실패 원인도 고정 코드만 남기고 임의 로그는 전달하지 않는다",()=>{
    const secret="fixture-private-message";
    const result=sanitizeConsoleEvents([{__typename:"ExecutionStepFailureEvent",message:secret,error:{className:"RuntimeError",message:`${secret} https://private.invalid`},failureMetadata:{metadataEntries:[{label:"error_code",text:"PROVIDER_AUTH"}]}},{__typename:"LogMessageEvent",message:secret}]);
    expect(result).toHaveLength(1);expect(result[0].detail).toContain("PROVIDER_AUTH");expect(JSON.stringify(result)).not.toContain(secret);
  });
  it("실행 취소·재실행 가능 여부는 native 권한과 상태를 따른다",()=>{
    expect(sanitizeConsoleRun({...run(),hasTerminatePermission:false}).canCancel).toBe(false);
    expect(sanitizeConsoleRun(run("CANCELING")).canCancel).toBe(false);
    expect(sanitizeConsoleRun(run("SUCCESS")).canRetry).toBe(false);
    expect(sanitizeConsoleRun(run("FAILURE")).canRetry).toBe(true);
  });
});

describe("관리자 변경 요청",()=>{
  it("새 실행은 fixed selector/default config와 namespace UUID만 보낸다",async()=>{
    const f=fixture();const result=await handleConsoleRequest({operation:"action",action:"launch",name:"fixture_job",requestId},f.graphql);
    expect(result).toMatchObject({state:"accepted",runId:other,requestId});
    const [,variables]=f.graphql.mock.calls.find(([query])=>query.includes("mutation AdminDagsterLaunch"))!;
    expect(variables).toMatchObject({requestId:consoleRequestId(requestId),executionParams:{selector:{pipelineName:"fixture_job",repositoryLocationName:DAGSTER_LOCATION_NAME,repositoryName:"__repository__"},runConfigData:{}}});
  });
  it("이전 요청은 다시 launch하지 않는다",async()=>{
    const f=fixture();f.setPrior([{runId:other,jobName:"fixture_job",status:"QUEUED"}]);
    expect(await handleConsoleRequest({operation:"action",action:"launch",name:"fixture_job",requestId},f.graphql)).toMatchObject({state:"accepted",replayed:true});
    expect(f.graphql.mock.calls.some(([query])=>/^\s*mutation\b/.test(query))).toBe(false);
  });
  it("예약 전 단계의 동일 요청만 같은 UUID로 복구한다",async()=>{
    const f=fixture();f.setPrior([{runId:other,jobName:"fixture_job",status:"NOT_STARTED"}]);f.setActive([{runId:other,jobName:"fixture_job",status:"NOT_STARTED"}]);
    const input={operation:"action" as const,action:"launch" as const,name:"fixture_job",requestId};
    expect(await handleConsoleRequest({operation:"requestStatus",requestId},f.graphql)).toMatchObject({state:"unknown",runId:other});
    expect(await handleConsoleRequest(input,f.graphql)).toMatchObject({state:"accepted"});
    const calls=f.graphql.mock.calls.filter(([query])=>/^\s*mutation\b/.test(query));expect(calls).toHaveLength(1);expect(calls[0][1].requestId).toBe(consoleRequestId(requestId));
  });
  it("진행 중인 동일 작업은 기존 실행으로 안내한다",async()=>{
    const f=fixture();f.setActive([{runId:other,jobName:"fixture_job",status:"STARTED"}]);
    expect(await handleConsoleRequest({operation:"action",action:"launch",name:"fixture_job",requestId},f.graphql)).toMatchObject({state:"blocked",runId:other});
    expect(f.graphql.mock.calls.some(([query])=>/^\s*mutation\b/.test(query))).toBe(false);
  });
  it("불명확한 mutation 결과는 자동 재전송하지 않는다",async()=>{
    const f=fixture();f.launchFailure();const result=await handleConsoleRequest({operation:"action",action:"launch",name:"fixture_job",requestId},f.graphql);
    expect(result).toMatchObject({state:"unknown",requestId});expect(JSON.stringify(result)).not.toContain("private-upstream-message");expect(f.graphql.mock.calls.filter(([query])=>/^\s*mutation\b/.test(query))).toHaveLength(1);
  });
  it("다른 location의 native 반환 run을 노출하지 않는다",async()=>{
    const f=fixture();f.foreignLaunch();const result=await handleConsoleRequest({operation:"action",action:"launch",name:"fixture_job",requestId},f.graphql);
    expect(result).toMatchObject({state:"unknown"});expect(result).not.toHaveProperty("runId");
  });
  it("취소는 SAFE_TERMINATE만 쓰며 종료·취소 중에는 재요청하지 않는다",async()=>{
    const f=fixture();expect(await handleConsoleRequest({operation:"action",action:"cancel",runId:id,requestId},f.graphql)).toMatchObject({state:"accepted"});
    expect(f.graphql.mock.calls.find(([query])=>/^\s*mutation\b/.test(query))![0]).toContain("SAFE_TERMINATE");
    for(const state of ["SUCCESS","CANCELING"]){f.graphql.mockClear();f.setRun(run(state));expect(await handleConsoleRequest({operation:"action",action:"cancel",runId:id,requestId},f.graphql)).toMatchObject({state:"unchanged"});expect(f.graphql.mock.calls.some(([query])=>/^\s*mutation\b/.test(query))).toBe(false);}
  });
  it("같은 작업 재실행은 옛 config를 복사하거나 실패 단계 재개로 가장하지 않는다",async()=>{
    const f=fixture();f.setRun(run("FAILURE"));expect(await handleConsoleRequest({operation:"action",action:"retry",runId:id,requestId},f.graphql)).toMatchObject({state:"accepted"});
    const [,variables]=f.graphql.mock.calls.find(([query])=>query.includes("mutation AdminDagsterLaunch"))!;
    expect(variables.executionParams).toMatchObject({runConfigData:{},executionMetadata:{tags:expect.arrayContaining([{key:"kortravel/admin-retry-of",value:id}])}});
    expect(JSON.stringify(f.graphql.mock.calls)).not.toContain("runConfigYaml");
  });
  it("재시도는 요청자 감사 태그를 달고 형식을 벗어난 요청자는 싣지 않는다",async()=>{
    for(const [actor,expected] of [["admin","admin"],["bad actor\n<script>",null],[null,null]] as const){
      const f=fixture();f.setRun(run("FAILURE"));
      expect(await handleConsoleRequest({operation:"action",action:"retry",runId:id,requestId},f.graphql,{actor})).toMatchObject({state:"accepted"});
      const [,variables]=f.graphql.mock.calls.find(([query])=>query.includes("mutation AdminDagsterLaunch"))!;
      const tags=(variables.executionParams as {executionMetadata:{tags:{key:string;value:string}[]}}).executionMetadata.tags;
      expect(tags.find(item=>item.key==="kortravel/admin-actor")?.value??null).toBe(expected);
      expect(tags).toEqual(expect.arrayContaining([{key:"kortravel/admin-retry-of",value:id}]));
    }
  });
  it("실행 상세는 재시도 원본·요청자를 검증된 형식만 노출한다",()=>{
    const tagged=(tags:{key:string;value:string}[])=>sanitizeConsoleRun({...run("QUEUED"),tags});
    expect(tagged([{key:"kortravel/admin-retry-of",value:other.toUpperCase()},{key:"kortravel/admin-actor",value:"admin"}]))
      .toMatchObject({retryOf:other,requestedBy:"admin"});
    expect(tagged([{key:"kortravel/admin-retry-of",value:"../foreign"},{key:"kortravel/admin-actor",value:"<b>x</b>"}]))
      .toMatchObject({retryOf:null,requestedBy:null});
    expect(sanitizeConsoleRun(run("FAILURE"))).toMatchObject({retryOf:null,requestedBy:null});
  });
  it("스케줄·센서 식별자는 서버가 읽은 자기 repository 값만 쓴다",async()=>{
    const f=fixture();expect(await handleConsoleRequest({operation:"action",action:"startSchedule",name:"fixture_schedule",requestId},f.graphql)).toMatchObject({state:"accepted"});
    expect(f.graphql.mock.calls.at(-1)![1]).toEqual({selector:{repositoryLocationName:DAGSTER_LOCATION_NAME,repositoryName:"__repository__",scheduleName:"fixture_schedule"}});
    expect(await handleConsoleRequest({operation:"action",action:"stopSensor",name:"fixture_sensor",requestId},f.graphql)).toMatchObject({state:"accepted"});
    expect(f.graphql.mock.calls.at(-1)![1]).toEqual({id:"owned-sensor-id"});
  });
});


it("코드 위치 카탈로그가 잠시 없어도 소유 실행의 정상 취소는 제공한다",async()=>{
 const f=fixture();Object.assign(f.catalog.repositoryOrError,{__typename:"PythonError"});
 expect(await handleConsoleRequest({operation:"action",action:"cancel",runId:id,requestId},f.graphql)).toMatchObject({state:"accepted",runId:id});
 expect(f.graphql.mock.calls.filter(([query])=>/^\s*mutation\b/.test(query))).toHaveLength(1);
});

it("집계 조회가 불명확하면 실제 0건으로 표시하지 않는다",()=>{expect(sanitizeConsoleRun({...run(),stats:{__typename:"PythonError"}})).toMatchObject({stepsSucceeded:null,stepsFailed:null,materializations:null});});

it.each([{action:"cancel",runId:id},{action:"startSchedule",name:"fixture_schedule"},{action:"stopSensor",name:"fixture_sensor"}] as const)("$action의 native 내부오류는 확정 거절로 꾸미지 않는다",async action=>{
 const f=fixture(),original=f.graphql.getMockImplementation()!;
 f.graphql.mockImplementation(async(query,variables)=>/^\s*mutation\b/.test(query)?{result:{__typename:"PythonError"}}:original(query,variables));
 expect(await handleConsoleRequest({operation:"action",requestId,...action},f.graphql)).toMatchObject({state:"unknown"});
 expect(f.graphql.mock.calls.filter(([query])=>/^\s*mutation\b/.test(query))).toHaveLength(1);
});

it.each(["InvalidStepError","InvalidOutputError","RunConfigValidationInvalid","PipelineNotFoundError","UnauthorizedError","InvalidSubsetError","PresetNotFoundError","ConflictingExecutionParamsError","NoModeProvidedError"])("실제 union의 %s는 원문 없이 확정 거절로 표시한다",async type=>{
 const f=fixture(),original=f.graphql.getMockImplementation()!;
 f.graphql.mockImplementation(async(query,variables)=>query.includes("AdminDagsterLaunch")?{result:{__typename:type,message:"private-canary"}}:original(query,variables));
 const result=await handleConsoleRequest({operation:"action",action:"launch",name:"fixture_job",requestId},f.graphql);
 expect(result).toMatchObject({state:"rejected",requestId});expect(JSON.stringify(result)).not.toContain("private-canary");
 expect(f.graphql.mock.calls.filter(([query])=>/^\s*mutation\b/.test(query))).toHaveLength(1);
});
it.each(["PythonError","RunConflict","UnverifiedType"])("%s는 미예약으로 단정하지 않고 UNKNOWN을 유지한다",async type=>{
 const f=fixture(),original=f.graphql.getMockImplementation()!;
 f.graphql.mockImplementation(async(query,variables)=>query.includes("AdminDagsterLaunch")?{result:{__typename:type,message:"private-canary"}}:original(query,variables));
 expect(await handleConsoleRequest({operation:"action",action:"launch",name:"fixture_job",requestId},f.graphql)).toMatchObject({state:"unknown",requestId});
 expect(f.graphql.mock.calls.filter(([query])=>/^\s*mutation\b/.test(query))).toHaveLength(1);
});

it("부분 완료 출력의 JSON 원인은 허용한 숫자 열만 브라우저에 보낸다",()=>{
 const result=sanitizeConsoleEvents([{__typename:"ExecutionStepOutputEvent",metadataEntries:[{label:"collection_outcome",text:"partial"},{label:"planned_grids",intValue:20},{label:"grid_failure_counts",jsonString:'{"PROVIDER_NETWORK":2,"PROVIDER_PARSE":3,"private":"private-canary"}'}]}]);
 expect(result[0]).toMatchObject({warning:true,counts:{planned_grids:20,grid_failure_PROVIDER_NETWORK:2,grid_failure_PROVIDER_PARSE:3}});expect(JSON.stringify(result)).not.toContain("private-canary");expect(JSON.stringify(result)).not.toContain("jsonString");
});


describe("실제 native 시각 단위",()=>{
 it("Run·단계·대기 시각의 초를 그대로 유지한다",()=>{
  const value={...run(),creationTime:1780000000,startTime:1780000001,endTime:1780000010,stats:{enqueuedTime:1780000000.5},stepStats:[{stepKey:"fetch",startTime:1780000001,endTime:1780000002}]};
  expect(sanitizeConsoleRun(value)).toMatchObject({creationTime:1780000000,startTime:1780000001,endTime:1780000010,queuedTime:1780000000.5,steps:[{key:"fetch",startTime:1780000001,endTime:1780000002},{key:"publish"}]});
 });
 it.each([1780000000000,"1780000000000",1780000000125,"1780000000125",0,"0",8640000000000000,"8640000000000000"])("native event milliseconds %s를 초로 변환한다",value=>{expect(sanitizeConsoleEvents([{__typename:"RunSuccessEvent",timestamp:value}])[0].time).toBe(Number(value)/1000);});
 it.each([NaN,Infinity,-1,"NaN","-1",""," ","private-canary",8640000000000001,true,null])("잘못된 event 시각 %s는 null이다",value=>{expect(sanitizeConsoleEvents([{__typename:"RunSuccessEvent",timestamp:value}])[0].time).toBeNull();});
 it("Run 초의 Date 경계와 일반 건수 제한은 별개다",()=>{
  expect(sanitizeConsoleRun({...run(),startTime:8640000000000}).startTime).toBe(8640000000000);expect(sanitizeConsoleRun({...run(),startTime:8640000000001}).startTime).toBeNull();
  expect(sanitizeConsoleRun({...run(),startTime:NaN,endTime:-1}).startTime).toBeNull();
  const event=sanitizeConsoleEvents([{__typename:"ExecutionStepOutputEvent",timestamp:"1780000000000",metadataEntries:[{label:"fetch_ms",intValue:1000000000001}]}])[0];expect(event.time).toBe(1780000000);expect(event.counts).toEqual({});
 });
});

describe("확인한 미해결 예약은 일시 차단으로 해제되지 않는다",()=>{
 const input={operation:"action",action:"launch",name:"fixture_job",requestId} as const;
 it("다른 같은 작업이 진행 중이면 원래 예약의 UNKNOWN과 ID를 유지한다",async()=>{
  const f=fixture();f.setPrior([{runId:id,jobName:"fixture_job",status:"NOT_STARTED"}]);f.setActive([{runId:id,jobName:"fixture_job",status:"NOT_STARTED"},{runId:other,jobName:"fixture_job",status:"STARTED"}]);
  expect(await handleConsoleRequest(input,f.graphql)).toMatchObject({state:"unknown",requestId,runId:id});expect(f.graphql.mock.calls.some(([query])=>/^\s*mutation\b/.test(query))).toBe(false);
  f.setActive([{runId:id,jobName:"fixture_job",status:"NOT_STARTED"}]);expect(await handleConsoleRequest(input,f.graphql)).toMatchObject({state:"accepted",requestId});
  const calls=f.graphql.mock.calls.filter(([query])=>/^\s*mutation\b/.test(query));expect(calls).toHaveLength(1);expect(calls[0][1].requestId).toBe(consoleRequestId(requestId));
 });
 it.each(["permission","capability"])("기존 예약 뒤 %s가 차단돼도 UNKNOWN이며 native 실행하지 않는다",async reason=>{
  const f=fixture();f.setPrior([{runId:id,jobName:"fixture_job",status:"NOT_STARTED"}]);if(reason==="permission")f.catalog.repositoryOrError.jobs[0].hasLaunchExecutionPermission=false;else f.catalog.__schema.mutationType.fields=[];
  expect(await handleConsoleRequest(input,f.graphql)).toMatchObject({state:"unknown",requestId,runId:id});expect(f.graphql.mock.calls.some(([query])=>/^\s*mutation\b/.test(query))).toBe(false);
 });
 it.each(["UnauthorizedError","RunConfigValidationInvalid"])("기존 예약 뒤 native %s도 예약 해제를 뜻하지 않는다",async type=>{
  const f=fixture(),original=f.graphql.getMockImplementation()!;f.setPrior([{runId:id,jobName:"fixture_job",status:"NOT_STARTED"}]);f.graphql.mockImplementation(async(query,variables)=>query.includes("AdminDagsterLaunch")?{result:{__typename:type}}:original(query,variables));
  expect(await handleConsoleRequest(input,f.graphql)).toMatchObject({state:"unknown",requestId,runId:id});expect(f.graphql.mock.calls.filter(([query])=>/^\s*mutation\b/.test(query))).toHaveLength(1);
 });
});
it("KMA progress에서 SDK 정상 반환 요청 건수만 고정 숫자로 꺼낸다",()=>{
 const events=sanitizeConsoleEvents([{__typename:"LogMessageEvent",timestamp:"1780000000000",message:"kma_collection_progress counts={'requests_fetched': 4, 'wire_attempts': 99} private-canary"}]);
 expect(events[0].counts).toEqual({requests_fetched:4});expect(JSON.stringify(events)).not.toContain("wire_attempts");expect(JSON.stringify(events)).not.toContain("private-canary");
});


describe("유가 요약 통계 게시 결과",()=>{
 const warning="원본 보존 · 유가 통계 게시 대기";
 const output=(metadataEntries:unknown[])=>sanitizeConsoleEvents([{__typename:"ExecutionStepOutputEvent",timestamp:"1780000000000",metadataEntries}])[0];
 it.each([undefined,"success","partial_success"])("실행 결과 %s의 명시적 False를 고정 경고로 보존한다",status=>{
  const result=output([{label:"fuel_statistics_published",boolValue:false},...(status?[{label:"status",text:status}]:[])]);expect(result.warning).toBe(true);expect(result.detail).toContain(warning);expect(result.detail).not.toContain("이전 통계");
 });
 it.each([{name:"미제공",entries:[]},{name:"None",entries:[{label:"fuel_statistics_published",boolValue:null}]},{name:"True",entries:[{label:"fuel_statistics_published",boolValue:true}]},{name:"문자열",entries:[{label:"fuel_statistics_published",text:"False"}]},{name:"숫자",entries:[{label:"fuel_statistics_published",intValue:0}]}])("$name 값은 게시 실패를 만들지 않는다",({entries})=>{
  const result=output([{label:"status",text:"success"},...entries]);expect(result.warning).toBe(false);expect(result.detail).not.toContain(warning);
 });
 it.each([['skipped','건너뜀'],['disabled','비활성'],['not_ready','대기']])("%s는 통계게시 실패가 아니라 미실행/유예로 구분한다",(status,label)=>{
  const result=output([{label:"fuel_statistics_published",boolValue:false},{label:"status",text:status}]);expect(result.warning).toBe(true);expect(result.detail).toContain(label);expect(result.detail).not.toContain(warning);
 });
 it("boolean skipped도 status없는 게시실패로 오인하지 않는다",()=>{const result=output([{label:"fuel_statistics_published",boolValue:false},{label:"skipped",boolValue:true}]);expect(result.warning).toBe(true);expect(result.detail).toContain("건너뜀");expect(result.detail).not.toContain(warning);});
 it("게시 지연 안내를 더하되 기존 제공기관 원인·코드와 수치를 유지한다",()=>{
  const result=output([{label:"status",text:"partial_success"},{label:"fuel_statistics_published",boolValue:false},{label:"error_code",text:"PROVIDER_AUTH"},{label:"fuel_price_count",intValue:7},{label:"private",text:"private-canary"}]);
  expect(result.warning).toBe(true);expect(result.detail).toContain(warning);expect(result.detail).toContain("PROVIDER_AUTH");expect(result.detail).toContain("서비스 활용신청");expect(result.counts.fuel_price_count).toBe(7);expect(JSON.stringify(result)).not.toContain("private-canary");
 });
 it("일반 유가 로그를 원문이나 임의 정규식으로 확장하지 않는다",()=>{
  const values=sanitizeConsoleEvents([{__typename:"ExecutionStepOutputEvent",metadataEntries:[{label:"fuel_statistics_published",boolValue:false}]},{__typename:"LogMessageEvent",message:"fuel_statistics_published=False https://private.invalid/?key=private-canary"}]);
  expect(values).toHaveLength(1);expect(values[0].detail).toContain(warning);expect(JSON.stringify(values)).not.toContain("private.invalid");expect(JSON.stringify(values)).not.toContain("private-canary");
 });
});

describe("이전 유가 통계 정리 결과",()=>{
 const output=(metadataEntries:unknown[])=>sanitizeConsoleEvents([{__typename:"ExecutionStepOutputEvent",timestamp:"1780000000000",metadataEntries}])[0];
 it("정리 실패는 경고와 고정 안내로 보이고 원천 성공을 실패로 바꾸지 않는다",()=>{
  const result=output([{label:"status",text:"success"},{label:"fuel_statistics_cleanup",text:"failed"},{label:"fuel_statistics_pruned_rows",intValue:5000}]);
  expect(result.warning).toBe(true);expect(result.detail).toContain("이전 유가 통계 정리 실패");expect(result.detail).toContain("자료 수집 완료");expect(result.counts.fuel_statistics_pruned_rows).toBe(5000);
 });
 it("예산 소진은 안내만 하고 경고로 올리지 않는다",()=>{
  const result=output([{label:"status",text:"success"},{label:"fuel_statistics_cleanup",text:"budget_exhausted"},{label:"fuel_statistics_pruned_rows",intValue:120000}]);
  expect(result.warning).toBe(false);expect(result.detail).toContain("남은 세대는 다음 수집에서 이어 정리");expect(result.counts.fuel_statistics_pruned_rows).toBe(120000);
 });
 it.each([["done"],["private-canary"],[""]])("%s 값은 안내를 만들지 않는다",value=>{
  const result=output([{label:"status",text:"success"},{label:"fuel_statistics_cleanup",text:value}]);
  expect(result.warning).toBe(false);expect(result.detail??"").not.toContain("정리");expect(JSON.stringify(result)).not.toContain("private-canary");
 });
});

describe("소통 5분 통계 재대조 지연(WLH-06)",()=>{
 const note="원본·통계 보존 · 소통 5분 통계 최근 2시간 재대조 대기 (다음 수집이 자동 복구)";
 const output=(metadataEntries:unknown[])=>sanitizeConsoleEvents([{__typename:"ExecutionStepOutputEvent",timestamp:"1780000000000",stepKey:"collect_highway_transport",metadataEntries}])[0];
 it("명시적 False는 고정 안내·원인·단계 시간을 보이고 캐시 지연으로 설명하지 않는다",()=>{
  const result=output([{label:"status",text:"success"},{label:"collection_outcome",text:"partial"},{label:"error_code",text:"DERIVED_CACHE_DEFERRED"},{label:"traffic_statistics_refreshed",boolValue:false},{label:"traffic_statistics_deferred_reason",text:"statement_timeout"},{label:"traffic_statistics_seconds",floatValue:61.2},{label:"traffic_unchanged_rows",intValue:830}]);
  expect(result.warning).toBe(true);expect(result.detail).toContain(note);expect(result.detail).toContain("DB 문장 시간 초과");expect(result.detail).toContain("최근 2시간 통계 재대조가 미뤄졌습니다");
  expect(result.detail).not.toContain("조회 캐시 또는 통계");expect(result.counts).toMatchObject({traffic_statistics_seconds:61.2,traffic_unchanged_rows:830});
 });
 it.each(["INVALID_ROWS_ISOLATED","PROVIDER_RATE_LIMIT"])("error_code %s여도 재대조 안내를 따로 보인다",code=>{
  const result=output([{label:"status",text:"partial_success"},{label:"collection_outcome",text:"partial"},{label:"error_code",text:code},{label:"traffic_statistics_refreshed",boolValue:false},{label:"traffic_statistics_deferred_reason",text:"busy"}]);
  expect(result.warning).toBe(true);expect(result.detail).toContain(note);expect(result.detail).toContain(code);expect(result.detail).toContain("다른 실행이 통계 갱신 중");
 });
 it("True·미제공은 안내를 만들지 않고 임의 원인 문자열은 버린다",()=>{
  for(const entries of [[{label:"traffic_statistics_refreshed",boolValue:true}],[]]){const result=output([{label:"status",text:"success"},...entries]);expect(result.warning).toBe(false);expect(result.detail??"").not.toContain(note);}
  const result=output([{label:"traffic_statistics_refreshed",boolValue:false},{label:"traffic_statistics_deferred_reason",text:"private-canary"}]);
  expect(result.detail).toContain(note);expect(JSON.stringify(result)).not.toContain("private-canary");
 });
 it("원천 저장 되돌림은 단계·원인과 함께 경고로 보인다",()=>{
  const result=output([{label:"status",text:"partial_success"},{label:"traffic_source_committed",boolValue:false},{label:"traffic_failed_step",text:"history"},{label:"traffic_store_failure_reason",text:"sqlstate_22"},{label:"traffic_history_seconds",floatValue:59.9}]);
  expect(result.warning).toBe(true);expect(result.detail).toContain("소통 원천 저장 되돌림");expect(result.detail).toContain("관측 이력 저장");expect(result.detail).toContain("SQLSTATE 등급 22");expect(result.counts.traffic_history_seconds).toBe(59.9);
 });
});
