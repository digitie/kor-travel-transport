// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { OperationsHome } from "./operations-home";
import { CollectionStatus } from "./collection-status";
import { transportGet } from "@/lib/journey";
import { getDagsterOverview, type DagsterOverview } from "@/lib/dagster";
vi.mock("@/lib/journey", async (original) => ({ ...await original<typeof import("@/lib/journey")>(), transportGet: vi.fn() }));
vi.mock("@/lib/dagster", async (original) => ({ ...await original<typeof import("@/lib/dagster")>(), getDagsterOverview: vi.fn() }));
function deferred<T>() { let resolve!: (value: T) => void; return { promise: new Promise<T>(done => { resolve = done; }), resolve: (value: T) => resolve(value) }; }
const provider = { source: "sample", name: "검증 수집원", enabled: true, mode: "scheduled", status: "ok", last_success_at: null, next_due_at: null, error_code: null, job_name: null, interval_seconds: null, last_started_at: null };
const providers = { generated_at: "2026-11-11T00:00:00Z", items: [provider], ferry_window_start: "2026-11-11", ferry_window_end: "2026-11-12", ferry_expected_snapshots: 0, ferry_stored_snapshots: 0 };
let host: HTMLDivElement, root: Root;
beforeEach(() => { Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true }); host = document.createElement("div"); document.body.append(host); root = createRoot(host); vi.mocked(transportGet).mockReset(); vi.mocked(getDagsterOverview).mockReset(); });
afterEach(async () => { await act(async () => root.unmount()); host.remove(); });

test("운영 홈은 Dagster가 늦어도 먼저 완료된 제공기관 요약을 표시한다", async () => {
  const pipeline = deferred<DagsterOverview>();
  vi.mocked(transportGet).mockResolvedValue(providers); vi.mocked(getDagsterOverview).mockReturnValue(pipeline.promise);
  await act(async () => root.render(<OperationsHome />));
  expect(host.querySelector('[data-testid="home-stat-sources"]')?.textContent).toContain("1");
  expect(host.querySelector('[data-testid="home-stat-pipeline"]')?.textContent).toContain("상태 확인 중");
});

test("수집 상태는 한 조회가 늦어도 성공한 조회를 표시하고 해제 시 두 요청을 취소한다", async () => {
  const pipeline = deferred<DagsterOverview>();
  vi.mocked(transportGet).mockResolvedValue(providers); vi.mocked(getDagsterOverview).mockReturnValue(pipeline.promise);
  await act(async () => root.render(<CollectionStatus />));
  expect(host.querySelector('.provider-list')?.textContent).toContain("검증 수집원");
  const providerSignal = vi.mocked(transportGet).mock.calls[0][1];
  const dagsterSignal = vi.mocked(getDagsterOverview).mock.calls[0][0];
  await act(async () => root.render(null));
  expect(providerSignal?.aborted).toBe(true); expect(dagsterSignal?.aborted).toBe(true);
});
