"use client";

import { DagsterOperations as CommonDagsterOperations, type DagsterSnapshot } from "@kor-travel/ui";
import { useCallback, useEffect, useRef, useState } from "react";
import { PageHeader } from "./admin-shell";
import { getDagsterOverview, getRunFailure, jobBudgetSeconds, JOB_LABELS, statusLabel, type DagsterOverview, type DagsterRunFailureDetail } from "@/lib/dagster";
import { DAGSTER_LOCATION_NAME, DAGSTER_REPOSITORY_NAME, dagsterLocationUrl, dagsterRunUrl } from "@/lib/dagster-scope";

export function commonSnapshot(snapshot: DagsterOverview): DagsterSnapshot {
  const runs = new Map(snapshot.runs.map(run => [run.runId, run]));
  for (const run of snapshot.activeRuns ?? []) if (!runs.has(run.runId)) runs.set(run.runId, run);
  return {
    checkedAt: snapshot.checkedAt ?? "",
    repositories: [{ name: DAGSTER_REPOSITORY_NAME, locationName: DAGSTER_LOCATION_NAME, jobs: [], assets: [],
      schedules: snapshot.schedules.map(row => ({ name: row.name, cron: row.cronSchedule, jobName: row.pipelineName, status: row.scheduleState.status })) }],
    runs: [...runs.values()].map(run => ({ ...run, errorMessage: run.errorMessage ?? null,
      maxRuntimeSeconds: Number(run.tags?.find(tag => tag.key === "dagster/max_runtime")?.value) || jobBudgetSeconds(run.jobName) })),
  };
}

const props = {
  jobLabel: (name: string) => JOB_LABELS[name] ?? name,
  runUrl: dagsterRunUrl,
  scheduleUrl: (name: string) => dagsterLocationUrl(`/schedules/${encodeURIComponent(name)}`),
};

export function DagsterTables({ snapshot }: { snapshot: DagsterOverview }) {
  return <CommonDagsterOperations {...props} snapshot={commonSnapshot(snapshot)} onRefresh={() => undefined} />;
}

export function DagsterOperations() {
  const [snapshot, setSnapshot] = useState<DagsterOverview | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [detail, setDetail] = useState<{ runId: string; loading: boolean; result?: DagsterRunFailureDetail; error?: string } | null>(null);
  const requestVersion = useRef(0);
  const detailVersion = useRef(0);
  const overviewRequest = useRef<AbortController | null>(null);
  const detailRequest = useRef<{ runId: string; controller: AbortController } | null>(null);
  const requestOverview = useCallback(() => {
    const version = ++requestVersion.current;
    overviewRequest.current?.abort();
    detailRequest.current?.controller.abort();
    ++detailVersion.current;
    detailRequest.current = null;
    const controller = new AbortController();
    overviewRequest.current = controller;
    getDagsterOverview(AbortSignal.any([controller.signal, AbortSignal.timeout(25_000)]))
      .then(value => { if (version === requestVersion.current && !controller.signal.aborted) setSnapshot(value); })
      .catch(() => { if (version === requestVersion.current && !controller.signal.aborted) setError("Dagster 상태를 조회하지 못했습니다. 마지막 확인 결과를 유지합니다."); })
      .finally(() => { if (version === requestVersion.current) { overviewRequest.current = null; setLoading(false); } });
  }, []);
  const load = useCallback(() => {
    setSelectedRunId(null);
    setDetail(null);
    setLoading(true);
    setError("");
    requestOverview();
  }, [requestOverview]);
  const selectRun = useCallback((runId: string) => {
    if (overviewRequest.current !== null || !snapshot) return;
    const run = commonSnapshot(snapshot).runs.find(item => item.runId === runId);
    if (!run || detailRequest.current?.runId === runId) return;
    detailRequest.current?.controller.abort();
    detailRequest.current = null;
    const version = ++detailVersion.current;
    const overviewVersion = requestVersion.current;
    setSelectedRunId(runId);
    if (run.status !== "FAILURE") { setDetail(null); return; }
    const controller = new AbortController();
    detailRequest.current = { runId, controller };
    setDetail({ runId, loading: true });
    getRunFailure(runId, controller.signal)
      .then(result => {
        if (version === detailVersion.current && overviewVersion === requestVersion.current && !controller.signal.aborted) setDetail({ runId, loading: false, result });
      })
      .catch(() => {
        if (version === detailVersion.current && overviewVersion === requestVersion.current && !controller.signal.aborted) setDetail({ runId, loading: false, error: "실패 원인을 조회하지 못했습니다. 다시 조회해 주세요." });
      })
      .finally(() => { if (version === detailVersion.current) detailRequest.current = null; });
  }, [snapshot]);
  useEffect(() => {
    const overviewSequence = requestVersion;
    const detailSequence = detailVersion;
    const overviewController = overviewRequest;
    const detailController = detailRequest;
    requestOverview();
    return () => {
      ++overviewSequence.current;
      ++detailSequence.current;
      overviewController.current?.abort();
      detailController.current?.controller.abort();
    };
  }, [requestOverview]);
  const common = snapshot ? commonSnapshot(snapshot) : null;
  const displaySnapshot = common && { ...common, runs: common.runs.map(run => ({
    ...run,
    errorMessage: run.status !== "FAILURE" ? run.errorMessage : detail?.runId !== run.runId
      ? "실패 원인 미조회 · 실행을 선택해 조회하세요."
      : detail.loading ? "실패 원인 조회 중…" : detail.error ? "실패 원인 조회 실패 · 상세에서 다시 조회하세요."
      : detail.result?.message ?? (detail.result?.complete ? "실패 이벤트가 없습니다." : "조회 상한에 도달했습니다."),
  })) };
  return <>
    <PageHeader title="Dagster" description="자동 수집 작업의 실행 기록과 스케줄을 확인합니다. 제공기관별 저장 범위는 수집 상태 메뉴에서 확인하세요." />
    <CommonDagsterOperations {...props} snapshot={displaySnapshot}
      error={error || snapshot?.warning} loading={loading} onRefresh={load} locationUrl={dagsterLocationUrl()}
      showRunDetails selectedRunId={selectedRunId} onSelectRun={selectRun}
      renderRunDetail={run => !run ? <p className="empty">실행을 선택하면 상세를 확인할 수 있습니다.</p> : <div>
        <h3>{props.jobLabel(run.jobName)}</h3><code>{run.runId}</code><p>{statusLabel(run.status)}</p>
        {run.status === "FAILURE" ? <div aria-busy={detail?.loading ?? false}>
          {detail?.runId !== run.runId ? <p>실패 원인 미조회</p> : detail.loading ? <p role="status">실패 원인 조회 중…</p> : detail.error ? <div role="alert"><p>{detail.error}</p><button type="button" onClick={() => selectRun(run.runId)}>실패 원인 다시 조회</button></div>
            : <><p className="dagster-run-error">{detail.result?.message ?? (detail.result?.complete ? "실패 이벤트가 없습니다." : "조회 범위에서 실패 원인을 찾지 못했습니다.")}</p>
              {!detail.result?.complete ? <p>조회 상한에 도달했습니다. 전체 로그는 Dagster에서 확인하세요.</p> : null}</>}
        </div> : <p>실패하지 않은 실행은 오류 로그를 자동 조회하지 않습니다.</p>}
        <a className="inline-link" href={dagsterRunUrl(run.runId)} target="_blank" rel="noreferrer">선택한 실행을 Dagster에서 열기 ↗</a>
      </div>} />
    <p className="description">KRIC 48시간·버스 기준정보 72시간 보호를 따릅니다. 배편은 4시간마다 누락 범위를 보충합니다. 실행 성공은 전국 자료 적재 완료를 뜻하지 않습니다.</p>
  </>;
}
