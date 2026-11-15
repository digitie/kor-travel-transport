// @vitest-environment jsdom
import { transferableAbortController } from "node:util";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { DagsterOperations } from "./dagster-operations";
import { getDagsterOverview, getRunFailure, type DagsterOverview, type DagsterRunFailureDetail } from "@/lib/dagster";
import type { ConsoleCatalog, ConsoleRunDetail } from "@/lib/dagster-console-model";

vi.mock("@/lib/dagster", async importOriginal => ({ ...await importOriginal<typeof import("@/lib/dagster")>(), getDagsterOverview: vi.fn(), getRunFailure: vi.fn() }));
const overview = vi.mocked(getDagsterOverview), failure = vi.mocked(getRunFailure);
const ids = ["00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000002", "00000000-0000-0000-0000-000000000003"];
const snapshot = (): DagsterOverview => ({ checkedAt: new Date().toISOString(), schedules: [], runs: ids.map((runId, index) => ({ runId, jobName: "airport_collection_job", status: index === 2 ? "SUCCESS" : "FAILURE", startTime: 1, endTime: 2 })) });
function deferred<T>() { let resolve!: (value: T) => void, reject!: (error: Error) => void; const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; }
type ConsoleCall={body:Record<string,unknown>;signal:AbortSignal|null|undefined};
const consoleCalls:ConsoleCall[]=[],consolePending=new Map<string,ReturnType<typeof deferred<ConsoleRunDetail>>>();
const catalog:ConsoleCatalog={jobs:["airport_collection_job"],schedules:[],sensors:[],capabilities:{launch:true,cancel:true,retry:true,schedule:true,sensor:true},checkedAt:"2026-11-15T00:00:00Z"};
function runDetail(runId:string,note?:string):ConsoleRunDetail {
  const run=snapshot().runs.find(item=>item.runId===runId)!;
  const success=run.status==="SUCCESS";
  return {runId,jobName:run.jobName,status:run.status,creationTime:0,startTime:1,endTime:2,queuedTime:0,canCancel:false,canRetry:!success,
    steps:[{key:"fetch",status:success?"SUCCESS":"FAILURE",startTime:1,endTime:2,attempts:1}],stepsSucceeded:success?1:0,stepsFailed:success?0:1,materializations:0,
    events:[{kind:success?"RunSuccessEvent":"ExecutionStepOutputEvent",time:1,step:null,title:success?"실행 완료":"일부 처리 결과",detail:note??(success?null:"고정 상세: 일부 원천 수집 확인 필요"),warning:!success,counts:{}}],cursor:success?"fixture-end":"fixture-page-1",hasMore:!success,stepsTruncated:false,checkedAt:"2026-11-15T00:00:00Z"};
}
function consoleDetails(){return consoleCalls.filter(call=>call.body.operation==="detail");}
async function consoleResponse(input:RequestInfo|URL,init?:RequestInit) {
  expect(String(input)).toBe("/api/dagster/console");
  const body=JSON.parse(String(init?.body)) as Record<string,unknown>;consoleCalls.push({body,signal:init?.signal});
  if(body.operation==="catalog")return Response.json(catalog);
  if(body.operation==="detail"){
    const runId=String(body.runId),pending=consolePending.get(runId);
    const value=pending?await pending.promise:runDetail(runId);
    return Response.json(body.cursor?{...value,events:[],cursor:"fixture-end",hasMore:false}:value);
  }
  throw new Error("이 조회 통합 시험에서는 변경 요청을 보내지 않습니다.");
}
let root: Root | null, container: HTMLDivElement;
beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  // jsdom25에는 any가 없다. 브라우저가 제공하는 동일 표준 API를 Node22 정본으로 검증한다.
  const native = transferableAbortController();
  vi.stubGlobal("AbortController", native.constructor); vi.stubGlobal("AbortSignal", native.signal.constructor);
  overview.mockReset(); failure.mockReset(); overview.mockResolvedValue(snapshot());
  consoleCalls.length=0;consolePending.clear();vi.stubGlobal("fetch",vi.fn(consoleResponse));
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
});
afterEach(async () => { if (root) await act(async () => root!.unmount()); container.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
async function render() { await act(async () => { root!.render(<DagsterOperations />); }); }
async function click(button: HTMLButtonElement | undefined) { expect(button).toBeDefined(); await act(async () => { button!.click(); }); }
function select(id: string) { return [...container.querySelectorAll<HTMLButtonElement>("button")].find(node => node.getAttribute("aria-label")?.endsWith(id)); }
function detail() { return container.querySelector("[data-slot=dagster-operations-run-detail]")!; }
function button(text: string) { return [...container.querySelectorAll<HTMLButtonElement>("button")].find(node => node.textContent === text); }

test("Common 실제 UI는 선택 전 상세를 받지 않고 성공 실행 선택 후 정상 진행 상세만 조회한다", async () => {
  await render(); expect(overview).toHaveBeenCalledTimes(1); expect(failure).not.toHaveBeenCalled();
  expect(container.textContent).toContain("실패 원인 미조회");
  expect(consoleCalls.map(call=>call.body)).toEqual([{operation:"catalog"}]);
  await click(select(ids[2]));expect(failure).not.toHaveBeenCalled();
  expect(consoleDetails().map(call=>call.body)).toEqual([{operation:"detail",runId:ids[2],cursor:null}]);
  expect(detail().textContent).toContain("실행·단계 진행");expect(detail().textContent).toContain("실행 완료");expect(detail().querySelector('[aria-label="안전한 처리 내역"]')?.textContent).toContain("실행 완료");
});

test("pending 중복 선택은1회이고 선택 변경은 이전 취소·늦은 응답 차단을 수행한다", async () => {
  const first = deferred<DagsterRunFailureDetail>(), second = deferred<DagsterRunFailureDetail>();
  const firstConsole=deferred<ConsoleRunDetail>(),secondConsole=deferred<ConsoleRunDetail>();consolePending.set(ids[0],firstConsole);consolePending.set(ids[1],secondConsole);
  failure.mockImplementationOnce(() => first.promise).mockImplementationOnce(() => second.promise);
  await render(); await click(select(ids[0])); await click(select(ids[0])); expect(failure).toHaveBeenCalledTimes(1);
  const firstSignal = failure.mock.calls[0][1]!; expect(firstSignal.aborted).toBe(false);
  expect(consoleDetails()).toHaveLength(1);const firstConsoleSignal=consoleDetails()[0].signal!;expect(firstConsoleSignal.aborted).toBe(false);
  await click(select(ids[1])); expect(firstSignal.aborted).toBe(true); expect(failure).toHaveBeenCalledTimes(2);expect(firstConsoleSignal.aborted).toBe(true);expect(consoleDetails()).toHaveLength(2);
  await act(async () => { first.resolve({ message: "old-result", complete: true });firstConsole.resolve(runDetail(ids[0],"old-console-result")); });
  expect(detail().textContent).not.toContain("old-result");expect(detail().textContent).not.toContain("old-console-result");
  await act(async () => { second.resolve({ message: "current-result", complete: true });secondConsole.resolve(runDetail(ids[1],"current-console-result")); });
  expect(detail().textContent).toContain("current-result"); expect(detail().textContent).toContain(ids[1]);expect(detail().textContent).toContain("current-console-result");
});

test("상세 오류는 목록과 격리하고 같은 실행의 명시 재조회로 복구한다", async () => {
  failure.mockRejectedValueOnce(new Error("synthetic error")).mockResolvedValueOnce({ message: null, complete: true });
  await render(); await click(select(ids[0]));
  expect(detail().querySelector('div[aria-busy] [role="alert"]')?.textContent).toContain("실패 원인을 조회하지 못했습니다");
  expect(container.querySelector("[data-slot=dagster-operations-error]")).toBeNull(); expect(select(ids[1])).toBeDefined();
  await click(button("실패 원인 다시 조회")); expect(failure).toHaveBeenCalledTimes(2); expect(detail().textContent).toContain("실패 이벤트가 없습니다");
});

test("새로고침은 상세를 취소하고 취소를 무시한 늦은 결과도 채택하지 않는다", async () => {
  const pending = deferred<DagsterRunFailureDetail>(); failure.mockReturnValue(pending.promise);
  const pendingConsole=deferred<ConsoleRunDetail>();consolePending.set(ids[0],pendingConsole);
  await render(); await click(select(ids[0])); const signal = failure.mock.calls[0][1]!,consoleSignal=consoleDetails()[0].signal!;
  await click(button("새로고침")); expect(signal.aborted).toBe(true);expect(consoleSignal.aborted).toBe(true); expect(overview).toHaveBeenCalledTimes(2);
  await act(async () => { pending.resolve({ message: "stale-after-refresh", complete: true });pendingConsole.resolve(runDetail(ids[0],"stale-console-after-refresh")); });
  expect(detail().textContent).not.toContain("stale-after-refresh");expect(detail().textContent).not.toContain("stale-console-after-refresh"); expect(detail().textContent).toContain("실행을 선택하면");
});

test("화면 이탈은 pending overview를 취소한다", async () => {
  const pending = deferred<DagsterOverview>(); overview.mockReturnValue(pending.promise);
  await render(); const signal = overview.mock.calls[0][0]!;
  await act(async () => root!.unmount()); root = null; expect(signal.aborted).toBe(true);
  await act(async () => { pending.resolve(snapshot()); }); expect(container.textContent).toBe("");
});

test("화면 이탈은 pending 상세를 취소한다", async () => {
  const pending = deferred<DagsterRunFailureDetail>(); failure.mockReturnValue(pending.promise);
  const pendingConsole=deferred<ConsoleRunDetail>();consolePending.set(ids[0],pendingConsole);
  await render(); await click(select(ids[0])); const signal = failure.mock.calls[0][1]!,consoleSignal=consoleDetails()[0].signal!;
  await act(async () => root!.unmount()); root = null; expect(signal.aborted).toBe(true);expect(consoleSignal.aborted).toBe(true);
  await act(async () => { pending.resolve({ message: "after-unmount", complete: true });pendingConsole.resolve(runDetail(ids[0],"console-after-unmount")); }); expect(container.textContent).toBe("");
});

test("상한 도달 요약은 완료나 오류로 위장하지 않는다", async () => {
  failure.mockResolvedValue({ message: "partial-summary", complete: false });
  await render(); await click(select(ids[0]));
  expect(detail().textContent).toContain("partial-summary"); expect(detail().textContent).toContain("조회 상한에 도달했습니다");
  // 상한 안내는 조회 오류가 아니다. 별도의 수집 경고는 계속 표시한다.
  expect(detail().querySelector('div[aria-busy] [role="alert"]')).toBeNull();
  expect(detail().querySelector('[aria-label="실행 진행 상세"] [role="status"]')?.textContent).toContain("고정 상세: 일부 원천 수집 확인 필요");
  expect(consoleDetails()).toHaveLength(1);expect(failure).toHaveBeenCalledTimes(1);
  await click(button("다음 내역 보기"));expect(consoleDetails().at(-1)?.body).toEqual({operation:"detail",runId:ids[0],cursor:"fixture-page-1"});
  expect(detail().textContent).toContain("partial-summary");expect(failure).toHaveBeenCalledTimes(1);
});

test("overview 새로고침 실패는 마지막 목록을 보존한다", async () => {
  overview.mockResolvedValueOnce(snapshot()).mockRejectedValueOnce(new Error("unavailable"));
  await render(); await click(button("새로고침"));
  expect(container.querySelector("[data-slot=dagster-operations-error]")?.textContent).toContain("마지막 확인 결과");
  expect(select(ids[0])).toBeDefined(); expect(failure).not.toHaveBeenCalled();expect(consoleDetails()).toHaveLength(0);
});


test("목록에는 오류 코드 한 줄만 남기고 선택 상세에는 전체 진단을 표시한다", async () => {
  failure.mockResolvedValue({ message: "오류 코드: COLLECTION_TIMEOUT\n실패 단계: 제공기관 요청\n요청 횟수: 2", complete: true });
  await render(); await click(select(ids[0]));
  expect(detail().textContent).toContain("요청 횟수: 2");
  expect(container.querySelector("[data-slot=dagster-operations-run-table]")?.textContent).toContain("오류 코드: COLLECTION_TIMEOUT");
  expect(container.querySelector("[data-slot=dagster-operations-run-table]")?.textContent).not.toContain("요청 횟수: 2");
});
