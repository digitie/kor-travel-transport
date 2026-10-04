"use client";

import { DagsterOperations as CommonDagsterOperations, type DagsterSnapshot } from "@kor-travel/ui";
import { useEffect, useState } from "react";
import { PageHeader } from "./admin-shell";
import { getDagsterOverview, jobBudgetSeconds, JOB_LABELS, type DagsterOverview } from "@/lib/dagster";
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
  const [reload, setReload] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    getDagsterOverview(AbortSignal.any([controller.signal, AbortSignal.timeout(25_000)]))
      .then(value => { if (!controller.signal.aborted) setSnapshot(value); })
      .catch(() => { if (!controller.signal.aborted) setError("Dagster 상태를 조회하지 못했습니다. 마지막 확인 결과를 유지합니다."); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [reload]);
  function refresh() { if (loading) return; setLoading(true); setError(""); setReload(value => value + 1); }
  return <>
    <PageHeader title="Dagster" description="자동 수집 작업의 실행 기록과 스케줄을 확인합니다. 제공기관별 저장 범위는 수집 상태 메뉴에서 확인하세요." />
    <CommonDagsterOperations {...props} snapshot={snapshot ? commonSnapshot(snapshot) : null}
      error={error || snapshot?.warning} loading={loading} onRefresh={refresh} locationUrl={dagsterLocationUrl()} />
    <p className="description">KRIC 48시간·버스 기준정보 72시간 보호를 따릅니다. 배편은 4시간마다 누락 범위를 보충합니다. 실행 성공은 전국 자료 적재 완료를 뜻하지 않습니다.</p>
  </>;
}
