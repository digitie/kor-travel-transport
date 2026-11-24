import { describe, expect, it } from "vitest";
import { failureDiagnostic, gridFailureCounts, sanitizeDagsterOverview, sanitizeFailureResponse } from "./dagster-failure-diagnostics";

const event = {
  __typename: "ExecutionStepFailureEvent", stepKey: "kma_regional_alert_events_sync", message: "step failed",
  error: { className: "DagsterExecutionStepExecutionError", message: "wrapper", cause: { className: "AlertCollectionError", message: "ALERT_PAGE_METADATA" } },
  failureMetadata: { metadataEntries: [
    { label: "error_code", text: "ALERT_PAGE_METADATA" }, { label: "stage", text: "page_validation" },
    { label: "requested_page", intValue: 1 }, { label: "metadata_field", text: "pageNo" }, { label: "metadata_type", text: "null" },
    { label: "total_count", intValue: 0 },
  ] },
};

describe("수집 실패 상세의 서버 정제", () => {
  it("단계·근본 원인·분류·0을 포함한 실제 페이지 진단을 제공한다", () => {
    const result = failureDiagnostic(event);
    expect(result).toContain("ALERT_PAGE_METADATA");
    expect(result).toContain("페이지 완결성 검사");
    expect(result).toContain("AlertCollectionError");
    expect(result).toContain("요청 페이지: 1");
    expect(result).toContain("전체 행 수: 0");
    expect(result).toContain("검사 필드: pageNo · 응답 형식: null");
  });
  it("기존 예외 chain의 안전한 행 수를 읽고 응답 규격 확인을 안내한다", () => {
    const result = failureDiagnostic({ error: { className: "Failure", message: "traffic flow response contains invalid records (received_rows=8352, parsed_rows=8351, invalid_rows=1)" } });
    expect(result).toContain("TRAFFIC_FLOW_INVALID_RECORDS");
    expect(result).toContain("수신 행 수: 8352");
    expect(result).toContain("불량 행 수: 1");
    expect(result).toContain("정상 저장분은 유지");
  });
  it("scope·재시도·성공 저장분과 단계 수치를 고정 규격으로 표시한다", () => {
    const result = failureDiagnostic({ failureMetadata: { metadataEntries: [
      { label: "error_code", text: "COLLECTION_TIMEOUT" }, { label: "scope", text: "fuel" },
      { label: "stage", text: "provider_fetch" }, { label: "retryable", boolValue: true },
      { label: "successful_data_preserved", boolValue: true }, { label: "publish_ms", floatValue: 150.25 },
      { label: "fuel_price_count", intValue: 0 },
    ] } });
    expect(result).toContain("제공기관 요청");
    expect(result).toContain("수집 범위: 유가");
    expect(result).toContain("재시도 가능: 예");
    expect(result).toContain("성공 저장분 보존: 예");
    expect(result).toContain("게시 소요(ms): 150.25");
    expect(result).toContain("가격 저장 수: 0");
  });
  it("auth·한도·timeout에 서로 다른 대응을 보여준다", () => {
    expect(failureDiagnostic({ message: "ALERT_PROVIDER_AUTH" })).toContain("활용신청·서비스 키 권한");
    expect(failureDiagnostic({ message: "ALERT_PROVIDER_RATE_LIMIT" })).toContain("한도 종류와 복구 정책");
    expect(failureDiagnostic({ message: "Opinet browser action failed: cause=TimeoutError" })).toContain("OPINET_BROWSER_TIMEOUT");
  });
  it("오피넷 시각 자원 차단 실패와 자동 재시도 여부를 구분한다", () => {
    const result = failureDiagnostic({ message: "교통정보 수집에 실패했습니다(status=failed): Opinet browser resource policy failed command=Fetch.failRequest cause=Error reason=unclassified" });
    expect(result).toContain("오류 코드: OPINET_BROWSER_RESOURCE_POLICY");
    expect(result).not.toContain("Fetch.failRequest");
    const metadata = (auto: boolean) => failureDiagnostic({ failureMetadata: { metadataEntries: [
      { label: "error_code", text: "DATABASE_RETRYABLE" }, { label: "auto_retry", boolValue: auto }] } });
    expect(metadata(true)).toContain("자동 재시도: 예");
    expect(metadata(false)).toContain("자동 재시도: 아니오 · 필요하면 재시도 버튼");
    expect(metadata(true)).toContain("DB 잠금 경합");
  });
  it("URL·키·SQL·HTML·임의 metadata를 응답에 그대로 전달하지 않는다", () => {
    const secret = "fixture-unlabelled-private-key";
    const result = sanitizeFailureResponse({ errors: undefined, data: { runsOrError: { __typename: "Runs", results: [{ eventConnection: {
      cursor: "cursor", hasMore: false, events: [{ ...event,
        message: `<script>${secret}</script> https://example.invalid/?key=${secret} SELECT * FROM private_table`,
        error: { className: secret, message: secret, stack: [secret], cause: { message: `ALERT_PAGE_METADATA ${secret}` } },
        failureMetadata: { metadataEntries: [
          { label: "raw_payload", text: secret }, { label: "stage", text: secret },
          { label: "metadata_field", text: secret }, { label: "requested_page", intValue: -1 },
          { label: "page_size", floatValue: Infinity }, { label: "total_count", intValue: 1_000_000_001 },
        ] },
      }] } }] } } });
    const serialized = JSON.stringify(result);
    for (const value of [secret, "https://", "<script>", "SELECT", "raw_payload", '"stack"', '"error"']) expect(serialized).not.toContain(value);
    expect(serialized).toContain("ALERT_PAGE_METADATA");
    expect(serialized).toContain('"diagnostic":true');
    expect(serialized).not.toContain("요청 페이지");
  });
  it.each([
    "Detected run worker status RunWorkerStatus.NOT_FOUND. Marking run 0f1e2d as failed.",
    "This run has been marked as failed from outside the execution context.",
  ])("작업자가 결과 없이 사라진 실행은 미등록 오류가 아니라 실행 소실로 안내한다: %s", (message) => {
    const result = failureDiagnostic({ message, stepKey: "collect_fuel_transport" });
    expect(result).toContain("오류 코드: RUN_WORKER_LOST");
    expect(result).toContain("재시도하면 같은 회차를 저장된 진행분에서 이어 합니다");
    expect(result).not.toContain("UNKNOWN_FAILURE");
    expect(result).not.toContain("0f1e2d");
  });
  it("새 오류는 고정된 미등록 안내를 주고 위조한 class·stage는 숨긴다", () => {
    const result = failureDiagnostic({ message: "unknown-secret", stepKey: "constructor", error: { className: "unknown-secret" }, failureMetadata: { metadataEntries: [{ label: "error_code", text: "__proto__" }] } });
    expect(result).toContain("UNKNOWN_FAILURE");
    expect(result).toContain("실패 단계: 작업 실행");
    expect(result).not.toContain("unknown-secret");
    expect(result).not.toContain("function");
  });
  it("잘못된 이벤트 연결을 빈 정상 결과로 꾸미지 않는다", () => {
    expect(sanitizeFailureResponse({ data: { runsOrError: { __typename: "Runs", results: [{}] } } })).toHaveProperty("errors");
    expect(sanitizeFailureResponse({ errors: [{ message: "provider private-key" }] })).toEqual({ errors: [{ message: "실행 오류 상세를 읽지 못했습니다." }] });
  });
});

it("배편 파일 규격 실패의 원천과 보존·건수를 표시한다", () => {
  const result = failureDiagnostic({ failureMetadata: { metadataEntries: [
    { label: "error_code", text: "VADAHUB_SCHEMA_CHANGED" }, { label: "stage", text: "validation" },
    { label: "error_type", text: "SchemaError" }, { label: "dataset", text: "official_terminals" },
    { label: "failed_dataset_count", intValue: 1 }, { label: "successful_dataset_count", intValue: 3 },
    { label: "successful_data_preserved", boolValue: true },
  ] } });
  expect(result).toContain("VADAHUB_SCHEMA_CHANGED");
  expect(result).toContain("원천 자료 규격 검사");
  expect(result).toContain("실패 데이터셋: 공식 여객터미널 파일");
  expect(result).toContain("실패 데이터셋 수: 1");
  expect(result).toContain("성공 데이터셋 수: 3");
  expect(result).toContain("성공 저장분 보존: 예");
});

describe("한도·부분 완료 복구 정책",()=>{
 it("일일한도와 초당보호를 서로 다른 복구 정책으로 보인다",()=>{
  const message=(scope:string,retryable:boolean,hint:string)=>failureDiagnostic({failureMetadata:{metadataEntries:[{label:"error_code",text:"PROVIDER_RATE_LIMIT"},{label:"rate_limit_scope",text:scope},{label:"retryable",boolValue:retryable},{label:"recovery_hint",text:hint}]}});
  const daily=message("daily",false,"WAIT_QUOTA_RESET"),burst=message("per_second",true,"RETRY_AFTER_BACKOFF");
  expect(daily).toContain("일일");expect(daily).toContain("아니오 · 복구 정책 확인");expect(daily).toContain("일일 한도 초기화 이후");expect(burst).toContain("초당");expect(burst).toContain("예 · 호출 보호 후");
 });
 it.each(["COLLECTION_DEFERRED","DERIVED_CACHE_DEFERRED","REFERENCE_EXPORT_DEFERRED"])("%s는 고정 복구 원인을 설명한다",code=>{const text=failureDiagnostic({failureMetadata:{metadataEntries:[{label:"error_code",text:code}]}});expect(text).toContain(code);expect(text).not.toContain("UNKNOWN_FAILURE");});
});

it("개요에서 임의 태그·원문 오류를 숨기고 경고와 실행 예산만 유지한다",()=>{
 const result=sanitizeDagsterOverview({data:{repositoryOrError:{__typename:"PythonError",message:"private-canary"},runsOrError:{__typename:"Runs",results:[{runId:"fixture",status:"SUCCESS",jobName:"fixture_job",tags:[{key:"private",value:"private-canary"},{key:"kortravel/collection-outcome",value:"partial"},{key:"dagster/max_runtime",value:"3600"}]}]}}});
 expect(JSON.stringify(result)).not.toContain("private-canary");expect(JSON.stringify(result)).toContain("partial");expect(JSON.stringify(result)).toContain("3600");
});


describe("격자 실패 JSON의 고정 진단",()=>{
 it("허용 원인별 건수와 전체 격자 실패 코드를 표시한다",()=>{
  const result=failureDiagnostic({failureMetadata:{metadataEntries:[{label:"error_code",text:"KMA_ALL_GRIDS_FAILED"},{label:"planned_grids",intValue:20},{label:"grid_failure_counts",jsonString:JSON.stringify({PROVIDER_NETWORK:2,PROVIDER_SERVER:3,PROVIDER_PARSE:4,PROVIDER_NO_DATA:5,DB_LOCK_CONTENTION:6,private:"private-canary"})}]}});
  expect(result).toContain("KMA_ALL_GRIDS_FAILED");expect(result).not.toContain("UNKNOWN_FAILURE");expect(result).toContain("계획 격자 수: 20");expect(result).toContain("제공기관 연결 실패: 2");expect(result).toContain("제공기관 서버 오류: 3");expect(result).toContain("제공기관 응답 해석 실패: 4");expect(result).toContain("제공기관 자료 없음: 5");expect(result).toContain("DB 잠금 경합: 6");expect(result).not.toContain("private-canary");
 });
 it.each(["{","[]",JSON.stringify({PROVIDER_NETWORK:"2",PROVIDER_SERVER:-1,PROVIDER_PARSE:0.2,PROVIDER_NO_DATA:1e10,DB_LOCK_CONTENTION:{private:"private-canary"}}),JSON.stringify({PROVIDER_NETWORK:1,padding:"x".repeat(4096)}),JSON.stringify({PROVIDER_NETWORK:1,padding:"한".repeat(2000)})])("잘못되거나 4KB를 넘는 JSON은 원문 없이 제외한다",jsonString=>{expect(gridFailureCounts([{label:"grid_failure_counts",jsonString}])).toEqual({});});
 it("0은 보존하고 임의 metadata JSON은 읽지 않는다",()=>{expect(gridFailureCounts([{label:"grid_failure_counts",jsonString:'{"PROVIDER_NETWORK":0,"private":"private-canary"}'}])).toEqual({PROVIDER_NETWORK:0});expect(gridFailureCounts([{label:"private",jsonString:'{"PROVIDER_NETWORK":2}'}])).toEqual({});});
});

describe("소통 저장·통계 재대조 진단(WLH-06)",()=>{
 const entries=(extra:unknown[])=>({failureMetadata:{metadataEntries:[{label:"error_code",text:"DERIVED_CACHE_DEFERRED"},...extra]}});
 it("통계 재대조 지연은 캐시가 아닌 고정 사유·원인·시간으로 설명한다",()=>{
  const text=failureDiagnostic(entries([{label:"traffic_statistics_refreshed",boolValue:false},{label:"traffic_statistics_deferred_reason",text:"lock_timeout"},{label:"traffic_statistics_seconds",floatValue:12.5}]));
  expect(text).toContain("최근 2시간 통계 재대조가 미뤄졌습니다");expect(text).toContain("DB 잠금 대기 초과");expect(text).toContain("소통 통계 재대조(초): 12.5");expect(text).not.toContain("조회 캐시 또는 통계");
 });
 it("다른 파생 지연은 일반 사유를 유지한다",()=>{const text=failureDiagnostic(entries([]));expect(text).toContain("조회 캐시 또는 통계");});
 it("소통 저장 실패의 단계·원인 코드만 고정 문구로 싣고 임의 값은 버린다",()=>{
  const text=failureDiagnostic({failureMetadata:{metadataEntries:[{label:"error_code",text:"DATABASE_RETRYABLE"},{label:"traffic_source_committed",boolValue:false},{label:"traffic_failed_step",text:"touched_statistics"},{label:"traffic_store_failure_reason",text:"statement_timeout"},{label:"traffic_history_seconds",floatValue:3.25}]}});
  expect(text).toContain("소통 원천 저장: 되돌림 · 단계 원천 안 5분 통계 · 원인 DB 문장 시간 초과");expect(text).toContain("소통 이력 저장(초): 3.25");
  const unsafe=failureDiagnostic({failureMetadata:{metadataEntries:[{label:"traffic_source_committed",boolValue:false},{label:"traffic_failed_step",text:"private-canary"},{label:"traffic_store_failure_reason",text:"sqlstate_x; private-canary"}]}});
  expect(unsafe).toContain("소통 원천 저장: 되돌림 · 마지막 정상 자료 유지");expect(unsafe).not.toContain("private-canary");
 });
});
