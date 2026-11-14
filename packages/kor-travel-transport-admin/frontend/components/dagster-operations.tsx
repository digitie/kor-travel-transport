"use client";

import { DagsterOperations as CommonDagsterOperations } from "@kor-travel/ui";
import { useCallback, useEffect, useRef, useState } from "react";
import { EmptyState } from "@/components/empty-state";
import { Alert, AlertActions, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { getDagsterOverview, getRunFailure, JOB_LABELS, statusLabel, type DagsterOverview, type DagsterRunFailureDetail } from "@/lib/dagster";
import { dagsterLocationUrl, dagsterRunUrl, dagsterJobRunsUrl } from "@/lib/dagster-scope";

import { commonSnapshot } from "@/lib/dagster-snapshot";

const props = {
  jobLabel: (name: string) => JOB_LABELS[name] ?? name,
  runUrl: dagsterRunUrl,
  scheduleUrl: (name: string) => dagsterLocationUrl(`/schedules/${encodeURIComponent(name)}`),
};

export function DagsterTables({ snapshot }: { snapshot: DagsterOverview }) {
  return <CommonDagsterOperations {...props} snapshot={commonSnapshot(snapshot)} onRefresh={() => undefined} />;
}

/** 페이지 제목은 호출부(app/admin/dagster/page.tsx)가 소유하고, 이 컴포넌트는 실행·스케줄 본문만 그린다. */
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
    <CommonDagsterOperations {...props} snapshot={displaySnapshot}
      error={error || snapshot?.warning} loading={loading} onRefresh={load} locationUrl={dagsterLocationUrl()}
      showRunDetails selectedRunId={selectedRunId} onSelectRun={selectRun}
      renderRunDetail={run => !run ? <EmptyState size="sm" title="실행을 선택하면 상세를 확인할 수 있습니다." /> : <div className="flex min-w-0 flex-col gap-3 text-sm">
        <h3 className="font-semibold text-text-primary"><a className="text-brand underline-offset-4 hover:underline" href={dagsterJobRunsUrl(run.jobName)} rel="noreferrer" target="_blank">{props.jobLabel(run.jobName)} · 작업 실행 이력 ↗</a></h3>
        <code className="break-all font-mono text-xs text-text-secondary">{run.runId}</code>
        <p>{statusLabel(run.status)}</p>
        {run.status === "FAILURE" ? <div aria-busy={detail?.loading ?? false} className="flex flex-col gap-2">
          {detail?.runId !== run.runId ? <p className="text-xs text-text-secondary">실패 원인 미조회</p> : detail.loading ? <p className="text-xs text-text-secondary" role="status">실패 원인 조회 중…</p> : detail.error ? <Alert variant="destructive">
            <AlertDescription>
              <p>{detail.error}</p>
              <AlertActions><Button size="sm" type="button" variant="outline" onClick={() => selectRun(run.runId)}>실패 원인 다시 조회</Button></AlertActions>
            </AlertDescription>
          </Alert>
            : <>
              <p className="break-words whitespace-pre-wrap">{detail.result?.message ?? (detail.result?.complete ? "실패 이벤트가 없습니다." : "조회 범위에서 실패 원인을 찾지 못했습니다.")}</p>
              {!detail.result?.complete ? <p className="text-xs text-text-secondary">조회 상한에 도달했습니다. 전체 로그는 Dagster에서 확인하세요.</p> : null}</>}
        </div> : <p className="text-xs text-text-secondary">실패하지 않은 실행은 오류 로그를 자동 조회하지 않습니다.</p>}
        <a className="text-xs text-brand underline-offset-4 hover:underline" href={dagsterRunUrl(run.runId)} rel="noreferrer" target="_blank">선택한 실행을 Dagster에서 열기 ↗</a>
      </div>} />
    <p className="text-xs text-text-secondary">KRIC 48시간·버스 기준정보 72시간 보호를 따릅니다. 배편은 4시간마다 누락 범위를 보충합니다. 실행 성공은 전국 자료 적재 완료를 뜻하지 않습니다.</p>
  </>;
}
