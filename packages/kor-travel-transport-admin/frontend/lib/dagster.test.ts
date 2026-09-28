import { afterEach, expect, test, vi } from "vitest";
import { getDagsterOverview, runStalled, statusLabel } from "./dagster";

afterEach(() => vi.unstubAllGlobals());

test("수집 전 보호 대기는 성공이나 장애로 표시하지 않는다", () => {
  expect(statusLabel("throttled")).toBe("호출 보호 대기");
  expect(statusLabel("not_collected")).toBe("수집 이력 없음");
});

test("최근 이력과 별도로 전체 진행 중 실행을 조회한다", async () => {
  const active = { runId: "old-run", jobName: "ferry_timetable_collection_job", status: "STARTED", startTime: Date.now() / 1000 - 5 * 3600, endTime: null };
  const fetch = vi.fn().mockResolvedValue(Response.json({ data: {
    repositoriesOrError: { __typename: "RepositoryConnection", nodes: [] },
    runsOrError: { __typename: "Runs", results: [] },
    activeRuns: { __typename: "Runs", results: [active] },
  } }));
  vi.stubGlobal("fetch", fetch);
  const result = await getDagsterOverview();
  expect(result.runs).toEqual([]);
  expect(result.activeRuns).toEqual([active]);
  expect(runStalled(result.activeRuns![0])).toBe(true);
  expect(JSON.parse(fetch.mock.calls[0][1].body).query).toContain("activeRuns: runsOrError(filter: { statuses: [STARTED] })");
});

test("진행 중 작업 조회 누락을 정상 0건으로 바꾸지 않는다", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ data: {
    repositoriesOrError: { __typename: "RepositoryConnection", nodes: [] },
    runsOrError: { __typename: "Runs", results: [] },
  } })));
  await expect(getDagsterOverview()).rejects.toThrow("작업 목록");
});
