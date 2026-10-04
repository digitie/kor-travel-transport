import type { DagsterOperationRequest } from "./dagster-scope";

export type DagsterRun ={ runId: string; status: string; jobName: string; startTime: number | null; endTime: number | null; tags?: { key: string; value: string }[]; errorMessage?: string | null };
export type DagsterSchedule = { name: string; cronSchedule: string; pipelineName: string; scheduleState: { status: string } };
export type DagsterOverview = { runs: DagsterRun[]; activeRuns?: DagsterRun[]; schedules: DagsterSchedule[]; checkedAt?: string; warning?: string };
export const JOB_LABELS: Record<string, string> = { airport_collection_job: "공항 주차·요금", highway_collection_job: "고속도로 소통·돌발", fuel_collection_job: "주유소·유가", rail_reference_collection_job: "철도·도시철도 기준정보", maritime_reference_collection_job: "여객항구 기준정보", ferry_timetable_collection_job: "여객선 10일 시간표", bus_reference_collection_job: "고속·시외버스 터미널" };
export function statusLabel(value: string): string {
  const key = value.toLowerCase();
  if (key.startsWith("shared_job_")) return `공동 작업 ${statusLabel(key.slice(11))}`;
  if (key === "throttled") return "호출 보호 대기";
  return ({ success: "성공", failure: "실패", failed: "실패", partial: "일부 실패", partial_success: "일부 실패", started: "진행 중", starting: "시작 중", running: "진행 중", queued: "대기 중", disabled: "비활성", stopped: "중지", canceled: "취소", canceling: "취소 중", skipped: "실행 건너뜀", not_collected: "수집 이력 없음", on_demand: "요청 시 조회", unconnected: "미연결" } as Record<string, string>)[key] ?? "상태 확인 필요";
}
JOB_LABELS.kric_timetable_collection_job = "도시철도 예정 시간표";
JOB_LABELS.place_location_collection_job = "시설 좌표 보강 (VWorld)";
JOB_LABELS.kakao_place_location_collection_job = "시설 좌표 보강 (Kakao)";
JOB_LABELS.rest_area_reference_collection_job = "휴게소 기준정보";
JOB_LABELS.rest_area_fuel_price_collection_job = "휴게소 유가";
export function jobBudgetSeconds(job: string) { return ["ferry_timetable_collection_job", "kric_timetable_collection_job"].includes(job) ? 4 * 3600 : job === "fuel_collection_job" ? 2 * 3600 + 600 : job.includes("reference") ? 3600 : 600; }
export function scheduleDescription(cron: string) {
  const [minute, hour, day, month, weekday] = cron.split(" ");
  if (day !== "*" || month !== "*" || weekday !== "*") return "개별 실행 규칙 (상세 확인)";
  if (minute?.startsWith("*/") && hour === "*") return `${minute.slice(2)}분마다`;
  if (/^\d+$/.test(minute ?? "") && hour?.startsWith("*/")) return `${hour.slice(2)}시간마다 ${minute}분`;
  if (/^\d+$/.test(minute ?? "") && /^\d+(,\d+)*$/.test(hour ?? "")) return `매일 ${hour.split(",").map((value) => `${value.padStart(2, "0")}:${minute.padStart(2, "0")}`).join(" · ")}`;
  return "개별 실행 규칙 (상세 확인)";
}
export function runStalled(run: DagsterRun, now = Date.now()) { return run.status === "STARTED" && run.startTime != null && now / 1000 - run.startTime >= (Number(run.tags?.find(tag => tag.key === "dagster/max_runtime")?.value) || jobBudgetSeconds(run.jobName)); }
export async function getDagsterOverview(signal?: AbortSignal): Promise<DagsterOverview> {
  // 공용 Dagster webserver다 — query 본문과 이 location의 범위는 proxy가 채운다(lib/dagster-scope.ts).
  const request: DagsterOperationRequest = { operationName: "TransportDagsterOverview" };
  const response = await fetch("/api/dagster/graphql", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(request), cache: "no-store", signal });
  if (!response.ok) throw new Error("Dagster 연결에 실패했습니다. 다시 조회해 주세요.");
  const payload = await response.json() as { errors?: unknown[]; data?: { repositoryOrError: { __typename: string; schedules?: DagsterSchedule[] }; runsOrError: { __typename: string; results?: DagsterRun[] }; activeRuns?: { __typename: string; results?: DagsterRun[] } } };
  if (payload.errors?.length || payload.data?.repositoryOrError?.__typename !== "Repository" || payload.data?.runsOrError?.__typename !== "Runs" || payload.data?.activeRuns?.__typename !== "Runs") throw new Error("Dagster 작업 목록을 확인하지 못했습니다.");
  const runs = payload.data.runsOrError.results ?? [];
  // 실패 상세는 최대 3개만 조회한다. event 페이지를 순차 회수해 전체 로그를 메모리에 보관하지 않는다.
  await Promise.all(runs.filter(run => run.status === "FAILURE").slice(0, 3).map(async run => {
    run.errorMessage = await getRunFailure(run.runId, signal).catch(() => null);
  }));
  return { warning: (payload.data.activeRuns.results?.length ?? 0) >= 1000 ? "진행 중 실행이 조회 상한 1000건에 도달했습니다. Dagster UI에서 전체 목록을 확인하세요." : undefined, checkedAt: new Date().toISOString(), schedules: payload.data.repositoryOrError.schedules ?? [], runs: payload.data.runsOrError.results ?? [], activeRuns: payload.data.activeRuns.results ?? [] };
}


export async function getRunFailure(runId: string, signal?: AbortSignal): Promise<string | null> {
  const deadline = AbortSignal.timeout(15_000);
  const boundedSignal = signal ? AbortSignal.any([signal, deadline]) : deadline;
  let cursor: string | null = null;
  for (let page = 0; page < 20; page++) {
    const request: DagsterOperationRequest = { operationName: "TransportDagsterRunFailure", variables: { runId, cursor } };
    const response = await fetch("/api/dagster/graphql", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(request), cache: "no-store", signal: boundedSignal });
    if (!response.ok) return null;
    const payload = await response.json();
    const connection = payload.data?.runsOrError?.results?.[0]?.eventConnection;
    if (payload.errors?.length || !connection) return null;
    const failures = connection.events?.filter((event: { __typename: string }) => ["RunFailureEvent", "ExecutionStepFailureEvent"].includes(event.__typename)) ?? [];
    if (failures.length) return String(failures.at(-1).message ?? "실패 원인을 Dagster에서 확인하세요.").slice(0, 2000);
    if (!connection.hasMore || !connection.cursor || connection.cursor === cursor) return null;
    cursor = connection.cursor;
  }
  return null;
}
