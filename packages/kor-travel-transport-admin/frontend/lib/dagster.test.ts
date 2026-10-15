import { afterEach, expect, test, vi } from "vitest";
import { getDagsterOverview, getRunFailure, runStalled, statusLabel } from "./dagster";

afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

test("job 실행 상한 태그가 오래 걸리는 정상 작업의 오탐을 막는다", () => {
  const run = { runId: "run", jobName: "airport_collection_job", status: "STARTED", startTime: 0, endTime: null,
    tags: [{ key: "dagster/max_runtime", value: "14400" }] };
  expect(runStalled(run, 3600_000)).toBe(false);
  expect(runStalled(run, 14400_000)).toBe(true);
});

test("첫 1000개 event 뒤의 실패 원인도 페이지를 넘겨 확인한다", async () => {
  const fetch = vi.fn().mockResolvedValueOnce(Response.json({ data: { runsOrError: { __typename: "Runs", results: [{ eventConnection: {
    events: [], hasMore: true, cursor: "next" } }] } } })).mockResolvedValueOnce(Response.json({ data: { runsOrError: { __typename: "Runs", results: [{ eventConnection: {
    events: [{ __typename: "RunFailureEvent", message: "failure" }], hasMore: false } }] } } }));
  vi.stubGlobal("fetch", fetch);
  expect(await getRunFailure("00000000-0000-0000-0000-000000000001")).toEqual({ message: "failure", complete: true });
  expect(JSON.parse(fetch.mock.calls[1][1].body).variables.cursor).toBe("next");
});

test("수집 전 보호 대기는 성공이나 장애로 표시하지 않는다", () => {
  expect(statusLabel("throttled")).toBe("호출 보호 대기");
  expect(statusLabel("not_collected")).toBe("수집 이력 없음");
});

test("최근 이력과 별도로 전체 진행 중 실행을 조회한다", async () => {
  const active = { runId: "old-run", jobName: "ferry_timetable_collection_job", status: "STARTED", startTime: Date.now() / 1000 - 5 * 3600, endTime: null };
  const fetch = vi.fn().mockResolvedValue(Response.json({ data: {
    repositoryOrError: { __typename: "Repository", schedules: [] },
    runsOrError: { __typename: "Runs", results: [] },
    activeRuns: { __typename: "Runs", results: [active] },
  } }));
  vi.stubGlobal("fetch", fetch);
  const result = await getDagsterOverview();
  expect(result.runs).toEqual([]);
  expect(result.activeRuns).toEqual([active]);
  expect(runStalled(result.activeRuns![0])).toBe(true);
});

test("브라우저는 query 문서가 아니라 이름 붙은 작업만 보낸다", async () => {
  const fetch = vi.fn().mockResolvedValue(Response.json({ data: {
    repositoryOrError: { __typename: "Repository", schedules: [] },
    runsOrError: { __typename: "Runs", results: [] },
    activeRuns: { __typename: "Runs", results: [] },
  } }));
  vi.stubGlobal("fetch", fetch);
  await getDagsterOverview();
  expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ operationName: "TransportDagsterOverview" });
});

test("진행 중 작업 조회 누락을 정상 0건으로 바꾸지 않는다", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ data: {
    repositoryOrError: { __typename: "Repository", schedules: [] },
    runsOrError: { __typename: "Runs", results: [] },
  } })));
  await expect(getDagsterOverview()).rejects.toThrow("작업 목록");
});

test("이 location을 찾지 못한 응답을 빈 스케줄로 바꾸지 않는다", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ data: {
    repositoryOrError: { __typename: "RepositoryNotFoundError", message: "not found" },
    runsOrError: { __typename: "Runs", results: [] },
    activeRuns: { __typename: "Runs", results: [] },
  } })));
  await expect(getDagsterOverview()).rejects.toThrow("작업 목록");
});


test("실패3개가 있어도 초기 overview는 한 번만 조회한다", async () => {
  const fetch = vi.fn(async (_url: string, init: RequestInit) => {
    const request = JSON.parse(String(init.body));
    return Response.json(request.operationName === "TransportDagsterOverview" ? { data: {
      repositoryOrError: { __typename: "Repository", schedules: [] },
      runsOrError: { __typename: "Runs", results: Array.from({ length: 3 }, (_, index) => ({
        runId: "00000000-0000-0000-0000-" + String(index).padStart(12, "0"), status: "FAILURE", jobName: "airport_collection_job", startTime: 1, endTime: 2,
      })) }, activeRuns: { __typename: "Runs", results: [] },
    } } : { data: { runsOrError: { __typename: "Runs", results: [{ eventConnection: {
      events: [{ __typename: "RunFailureEvent", message: "detail" }], hasMore: false,
    } }] } } });
  });
  vi.stubGlobal("fetch", fetch);
  expect((await getDagsterOverview()).runs).toHaveLength(3);
  expect(fetch).toHaveBeenCalledTimes(1);
});


function detailPage(events: object[] = [], hasMore = false, cursor: string | null = null) {
  return Response.json({ data: { runsOrError: { __typename: "Runs", results: [{ eventConnection: { events, hasMore, cursor } }] } } });
}

test("미조회와 조회 완료 뒤 이벤트 없음은 다르다", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => detailPage()));
  expect(await getRunFailure("00000000-0000-0000-0000-000000000001")).toEqual({ message: null, complete: true });
});

test("상세 오류를 빈 성공으로 감추지 않는다", async () => {
  for (const response of [new Response("unavailable", { status: 503 }), Response.json({ errors: [{ message: "error" }] }),
    Response.json({ data: { runsOrError: { __typename: "PythonError" } } }), Response.json({ data: { runsOrError: { __typename: "Runs", results: [] } } }),
    Response.json({ data: { runsOrError: { __typename: "Runs", results: [{ eventConnection: { events: null } }] } } })]) {
    vi.stubGlobal("fetch", vi.fn(async () => response));
    await expect(getRunFailure("00000000-0000-0000-0000-000000000001")).rejects.toThrow();
  }
});

test("20page까지만 읽고 마지막 요약을 incomplete로 표시한다", async () => {
  let page = 0;
  const fetch = vi.fn(async () => detailPage([{ __typename: "ExecutionStepFailureEvent", message: "step-" + ++page }], true, "page-" + page));
  vi.stubGlobal("fetch", fetch);
  expect(await getRunFailure("00000000-0000-0000-0000-000000000001")).toEqual({ message: "step-20", complete: false });
  expect(fetch).toHaveBeenCalledTimes(20);
});

test("run 실패를 찾으면 step 요약 대신 표시하고2000자로 제한한다", async () => {
  const fetch = vi.fn(async () => detailPage([{ __typename: "ExecutionStepFailureEvent", message: "step" }, { __typename: "RunFailureEvent", message: "x".repeat(2100) }], true, "next"));
  vi.stubGlobal("fetch", fetch);
  expect(await getRunFailure("00000000-0000-0000-0000-000000000001")).toEqual({ message: "x".repeat(2000), complete: true });
  expect(fetch).toHaveBeenCalledTimes(1);
});

test("다음cursor 누락과 반복을 조회 완료로 바꾸지 않는다", async () => {
  for (const cursor of [null, "repeat"]) {
    const fetch = vi.fn(async () => detailPage([], true, cursor));
    vi.stubGlobal("fetch", fetch);
    await expect(getRunFailure("00000000-0000-0000-0000-000000000001")).rejects.toThrow("다음 페이지");
    expect(fetch).toHaveBeenCalledTimes(cursor ? 2 : 1);
  }
});

test("전체15초는 마지막 응답 뒤에도 검사하며 예산을 늘리지 않는다", async () => {
  let now = 0;
  vi.spyOn(performance, "now").mockImplementation(() => now);
  const fetch = vi.fn(async () => { now += 8_000; return detailPage([], true, String(now)); });
  vi.stubGlobal("fetch", fetch);
  await expect(getRunFailure("00000000-0000-0000-0000-000000000001")).rejects.toThrow("시간이 초과");
  expect(fetch).toHaveBeenCalledTimes(2);
});

test("최종page가15초에 도착해도 완료 응답으로 채택하지 않는다", async () => {
  let now = 0;
  vi.spyOn(performance, "now").mockImplementation(() => now);
  vi.stubGlobal("fetch", vi.fn(async () => { now = 15_000; return detailPage(); }));
  await expect(getRunFailure("00000000-0000-0000-0000-000000000001")).rejects.toThrow("시간이 초과");
});

test("이미 취소된 overview와 상세는 요청을 만들지 않는다", async () => {
  const controller = new AbortController(); controller.abort();
  vi.stubGlobal("fetch", vi.fn());
  await expect(getDagsterOverview(controller.signal)).rejects.toThrow();
  await expect(getRunFailure("00000000-0000-0000-0000-000000000001", controller.signal)).rejects.toThrow();
  expect(fetch).not.toHaveBeenCalled();
});

test("상세 대기 중 취소는 다음page 조회를 막는다", async () => {
  const controller = new AbortController();
  const fetch = vi.fn(async (_url: string, init: RequestInit) => {
    expect(init.signal?.aborted).toBe(false); controller.abort(); expect(init.signal?.aborted).toBe(true);
    return detailPage([], true, "next");
  });
  vi.stubGlobal("fetch", fetch);
  await expect(getRunFailure("00000000-0000-0000-0000-000000000001", controller.signal)).rejects.toThrow();
  expect(fetch).toHaveBeenCalledTimes(1);
});
