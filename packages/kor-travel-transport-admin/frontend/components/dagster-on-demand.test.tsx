// @vitest-environment jsdom
import { transferableAbortController } from "node:util";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { DagsterOperations } from "./dagster-operations";
import { getDagsterOverview, getRunFailure, type DagsterOverview, type DagsterRunFailureDetail } from "@/lib/dagster";

vi.mock("@/lib/dagster", async importOriginal => ({ ...await importOriginal<typeof import("@/lib/dagster")>(), getDagsterOverview: vi.fn(), getRunFailure: vi.fn() }));
const overview = vi.mocked(getDagsterOverview), failure = vi.mocked(getRunFailure);
const ids = ["00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000002", "00000000-0000-0000-0000-000000000003"];
const snapshot = (): DagsterOverview => ({ checkedAt: new Date().toISOString(), schedules: [], runs: ids.map((runId, index) => ({ runId, jobName: "airport_collection_job", status: index === 2 ? "SUCCESS" : "FAILURE", startTime: 1, endTime: 2 })) });
function deferred<T>() { let resolve!: (value: T) => void, reject!: (error: Error) => void; const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; }
let root: Root | null, container: HTMLDivElement;
beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  // jsdom25에는 any가 없다. 브라우저가 제공하는 동일 표준 API를 Node22 정본으로 검증한다.
  const native = transferableAbortController();
  vi.stubGlobal("AbortController", native.constructor); vi.stubGlobal("AbortSignal", native.signal.constructor);
  overview.mockReset(); failure.mockReset(); overview.mockResolvedValue(snapshot());
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
});
afterEach(async () => { if (root) await act(async () => root!.unmount()); container.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
async function render() { await act(async () => { root!.render(<DagsterOperations />); }); }
async function click(button: HTMLButtonElement | undefined) { expect(button).toBeDefined(); await act(async () => { button!.click(); }); }
function select(id: string) { return [...container.querySelectorAll<HTMLButtonElement>("button")].find(node => node.getAttribute("aria-label")?.endsWith(id)); }
function detail() { return container.querySelector("[data-slot=dagster-operations-run-detail]")!; }
function button(text: string) { return [...container.querySelectorAll<HTMLButtonElement>("button")].find(node => node.textContent === text); }

test("Common 실제 UI는 초기 overview1회와 미조회 상태를 표시하고 성공 실행은 상세를 요청하지 않는다", async () => {
  await render(); expect(overview).toHaveBeenCalledTimes(1); expect(failure).not.toHaveBeenCalled();
  expect(container.textContent).toContain("실패 원인 미조회");
  await click(select(ids[2])); expect(failure).not.toHaveBeenCalled(); expect(detail().textContent).toContain("자동 조회하지 않습니다");
});

test("pending 중복 선택은1회이고 선택 변경은 이전 취소·늦은 응답 차단을 수행한다", async () => {
  const first = deferred<DagsterRunFailureDetail>(), second = deferred<DagsterRunFailureDetail>();
  failure.mockImplementationOnce(() => first.promise).mockImplementationOnce(() => second.promise);
  await render(); await click(select(ids[0])); await click(select(ids[0])); expect(failure).toHaveBeenCalledTimes(1);
  const firstSignal = failure.mock.calls[0][1]!; expect(firstSignal.aborted).toBe(false);
  await click(select(ids[1])); expect(firstSignal.aborted).toBe(true); expect(failure).toHaveBeenCalledTimes(2);
  await act(async () => { first.resolve({ message: "old-result", complete: true }); });
  expect(detail().textContent).not.toContain("old-result");
  await act(async () => { second.resolve({ message: "current-result", complete: true }); });
  expect(detail().textContent).toContain("current-result"); expect(detail().textContent).toContain(ids[1]);
});

test("상세 오류는 목록과 격리하고 같은 실행의 명시 재조회로 복구한다", async () => {
  failure.mockRejectedValueOnce(new Error("synthetic error")).mockResolvedValueOnce({ message: null, complete: true });
  await render(); await click(select(ids[0]));
  expect(detail().querySelector("[role=alert]")).not.toBeNull();
  expect(container.querySelector("[data-slot=dagster-operations-error]")).toBeNull(); expect(select(ids[1])).toBeDefined();
  await click(button("실패 원인 다시 조회")); expect(failure).toHaveBeenCalledTimes(2); expect(detail().textContent).toContain("실패 이벤트가 없습니다");
});

test("새로고침은 상세를 취소하고 취소를 무시한 늦은 결과도 채택하지 않는다", async () => {
  const pending = deferred<DagsterRunFailureDetail>(); failure.mockReturnValue(pending.promise);
  await render(); await click(select(ids[0])); const signal = failure.mock.calls[0][1]!;
  await click(button("새로고침")); expect(signal.aborted).toBe(true); expect(overview).toHaveBeenCalledTimes(2);
  await act(async () => { pending.resolve({ message: "stale-after-refresh", complete: true }); });
  expect(detail().textContent).not.toContain("stale-after-refresh"); expect(detail().textContent).toContain("실행을 선택하면");
});

test("화면 이탈은 pending overview를 취소한다", async () => {
  const pending = deferred<DagsterOverview>(); overview.mockReturnValue(pending.promise);
  await render(); const signal = overview.mock.calls[0][0]!;
  await act(async () => root!.unmount()); root = null; expect(signal.aborted).toBe(true);
  await act(async () => { pending.resolve(snapshot()); }); expect(container.textContent).toBe("");
});

test("화면 이탈은 pending 상세를 취소한다", async () => {
  const pending = deferred<DagsterRunFailureDetail>(); failure.mockReturnValue(pending.promise);
  await render(); await click(select(ids[0])); const signal = failure.mock.calls[0][1]!;
  await act(async () => root!.unmount()); root = null; expect(signal.aborted).toBe(true);
  await act(async () => { pending.resolve({ message: "after-unmount", complete: true }); }); expect(container.textContent).toBe("");
});

test("상한 도달 요약은 완료나 오류로 위장하지 않는다", async () => {
  failure.mockResolvedValue({ message: "partial-summary", complete: false });
  await render(); await click(select(ids[0]));
  expect(detail().textContent).toContain("partial-summary"); expect(detail().textContent).toContain("조회 상한에 도달했습니다"); expect(detail().querySelector("[role=alert]")).toBeNull();
});

test("overview 새로고침 실패는 마지막 목록을 보존한다", async () => {
  overview.mockResolvedValueOnce(snapshot()).mockRejectedValueOnce(new Error("unavailable"));
  await render(); await click(button("새로고침"));
  expect(container.querySelector("[data-slot=dagster-operations-error]")?.textContent).toContain("마지막 확인 결과");
  expect(select(ids[0])).toBeDefined(); expect(failure).not.toHaveBeenCalled();
});
