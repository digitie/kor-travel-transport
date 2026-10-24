"use client";

// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Youn-sok Choi (digitie)
// Derived-From: kor-travel-map@974e2d025 home-client.tsx 운영 요약·실행·상태 배치
import { ExternalLink, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { PageHeader } from "@/components/admin-shell";
import { SectionCard } from "@/components/section-card";
import { StatStrip } from "@/components/stat-strip";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { getDagsterOverview, JOB_LABELS, statusLabel, type DagsterOverview } from "@/lib/dagster";
import { dagsterLocationUrl, dagsterRunUrl } from "@/lib/dagster-scope";
import { dateTime, transportGet } from "@/lib/journey";

type Provider = {
  source: string; name: string; enabled: boolean; mode: string; status: string;
  last_success_at: string | null; next_due_at: string | null; error_code: string | null;
};
type ProviderOverview = {
  generated_at: string; items: Provider[];
  kric_coverage?: { station_count: number; linked_station_count: number; expected_snapshots: number; stored_snapshots: number; fresh_snapshots: number } | null;
};

export function OperationsHome() {
  const [providers, setProviders] = useState<ProviderOverview | null>(null);
  const [dagster, setDagster] = useState<DagsterOverview | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [reload, setReload] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    const failed = (key: string, reason: unknown) => {
      if (!controller.signal.aborted) setErrors((previous) => ({ ...previous, [key]: reason instanceof Error ? reason.message : "조회 실패" }));
    };
    void Promise.allSettled([
      transportGet<ProviderOverview>("transport/providers", controller.signal)
        .then((value) => { if (!controller.signal.aborted) setProviders(value); })
        .catch((reason: unknown) => failed("수집 상태", reason)),
      getDagsterOverview(controller.signal)
        .then((value) => { if (!controller.signal.aborted) setDagster(value); })
        .catch((reason: unknown) => failed("파이프라인", reason)),
    ]).then(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [reload]);
  function refresh() {
    setProviders(null); setDagster(null); setErrors({}); setLoading(true); setReload((value) => value + 1);
  }
  const activeProviders = providers?.items.filter((item) => item.enabled && item.mode === "scheduled");
  const attention = providers?.items.filter((item) => item.enabled && (item.error_code || ["failed", "upstream_error", "not_collected"].includes(item.status)));
  const coverage = providers?.kric_coverage;
  const activeRuns = dagster?.activeRuns;
  const recentRuns = dagster?.runs ?? [];
  const failedRuns = dagster ? recentRuns.filter((run) => run.status === "FAILURE").length : null;
  const runningSchedules = dagster?.schedules.filter((schedule) => schedule.scheduleState.status === "RUNNING").length;
  return <>
    <PageHeader title="운영 홈" description="운영 상태를 한 화면에서 확인합니다." actions={<>
      <Button type="button" variant="outline" disabled={loading} onClick={refresh}><RefreshCw aria-hidden="true" className={loading ? "animate-spin" : ""} />새로고침</Button>
      <a className="button secondary" href={dagsterLocationUrl()} target="_blank" rel="noreferrer"><ExternalLink aria-hidden="true" size={15} />Dagster</a>
    </>} />
    <div className="operations-home space-y-6">
      {Object.keys(errors).length ? <Alert variant="destructive"><AlertTitle>운영 요약 확인 필요</AlertTitle><AlertDescription>{Object.entries(errors).map(([name, message]) => <p key={name}>{name} · {message}</p>)}<p>확인하지 못한 값은 —로 표시됩니다.</p></AlertDescription></Alert> : null}
      <Card size="sm" className="p-4">
        <StatStrip size="lg" ariaLabel="운영 요약" className="grid-cols-2 xl:grid-cols-4" items={[
          { key: "sources", label: "활성 수집 소스", value: activeProviders?.length, unit: "개", href: "/collections", caption: providers ? `전체 ${providers.items.length}개 소스 · 확인 필요 ${attention?.length ?? 0}개` : "수집 상태 확인 중", testId: "home-stat-sources" },
          { key: "pipeline", label: "진행 중 작업", value: activeRuns?.length, unit: "건", href: "/admin/dagster", caption: dagster ? `스케줄 ${runningSchedules ?? 0} / ${dagster.schedules.length}개 사용` : "파이프라인 상태 확인 중", testId: "home-stat-pipeline" },
          { key: "failures", label: "최근 실행 실패", value: failedRuns, unit: "건", href: "/admin/dagster", caption: dagster ? `조회한 최근 ${recentRuns.length}건 기준` : "최근 실행 확인 중", tone: failedRuns ? "destructive" : "neutral", testId: "home-stat-failures" },
          { key: "timetables", label: "도시철도 시간표", value: coverage?.fresh_snapshots, unit: "역·요일", href: "/rail/metro", caption: coverage ? `필요 ${coverage.expected_snapshots.toLocaleString()}개 · 저장 ${coverage.stored_snapshots.toLocaleString()}개` : "저장 범위 확인 중", testId: "home-stat-timetables" },
        ]} />
      </Card>
      <div className="grid min-w-0 gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="min-w-0 space-y-6">
          <SectionCard title="최근 실행" description="이 Transport 코드 위치의 최근 실행입니다." actions={<Link href="/admin/dagster" className="inline-link">전체 실행</Link>}>
            <div className="overflow-x-auto"><table className="operations-table"><thead><tr><th>작업</th><th>상태</th><th>시작 시각</th><th>실행</th></tr></thead><tbody>
              {recentRuns.slice(0, 8).map((run) => <tr key={run.runId}><td>{JOB_LABELS[run.jobName] ?? run.jobName}</td><td><span className={`operation-state ${run.status === "FAILURE" ? "failed" : run.status === "SUCCESS" ? "success" : ""}`}>{statusLabel(run.status)}</span></td><td>{dateTime(run.startTime ? new Date(run.startTime * 1000).toISOString() : null)}</td><td><a className="inline-link" href={dagsterRunUrl(run.runId)} target="_blank" rel="noreferrer">상세<ExternalLink aria-hidden="true" size={12} /></a></td></tr>)}
            </tbody></table></div>
            {!dagster ? <p className="quiet">{loading ? "최근 실행을 확인하는 중입니다…" : "최근 실행을 확인하지 못했습니다."}</p> : !recentRuns.length ? <p className="empty-state">최근 실행 기록이 없습니다.</p> : null}
            {dagster?.warning ? <p role="status">{dagster.warning}</p> : null}
          </SectionCard>
          <SectionCard title="확인이 필요한 수집" description="실패와 수집 이력 부재를 구분해 확인합니다." actions={<Link href="/collections" className="inline-link">수집 상태</Link>}>
            {attention?.length ? <ul className="operations-issues">{attention.map((item) => <li key={item.source}><div><strong>{item.name}</strong><span className="operation-state failed">{statusLabel(item.status)}</span></div><p>마지막 성공 {dateTime(item.last_success_at)}{item.next_due_at ? ` · 다음 평가 ${dateTime(item.next_due_at)}` : ""}</p></li>)}</ul> : <p className="quiet">{providers ? "확인이 필요한 수집 오류가 없습니다." : loading ? "수집 상태를 확인하는 중입니다…" : "수집 상태를 확인하지 못했습니다."}</p>}
          </SectionCard>
        </div>
        <div className="min-w-0 space-y-6">
          <SectionCard title="운영 상태"><dl className="operations-status">
            <div><dt>저장 API</dt><dd>{providers ? "응답 정상" : loading ? "확인 중" : "확인 실패"}</dd></div>
            <div><dt>Dagster</dt><dd>{dagster ? "응답 정상" : loading ? "확인 중" : "확인 실패"}</dd></div>
            <div><dt>시간표 역 연결</dt><dd>{coverage ? `${coverage.linked_station_count.toLocaleString()} / ${coverage.station_count.toLocaleString()}역` : "—"}</dd></div>
            <div><dt>수집 상태 확인</dt><dd>{dateTime(providers?.generated_at)}</dd></div>
          </dl></SectionCard>
          <SectionCard title="교통 정보"><nav className="operations-links" aria-label="교통 정보 바로가기">
            <Link href="/map">교통 지도<span>역·공항·터미널 위치</span></Link>
            <Link href="/highways">고속도로<span>지도·소통·돌발</span></Link>
            <Link href="/fuel/statistics">유가 통계<span>지역·고속도로 가격 비교</span></Link>
            <Link href="/flights">비행·공항<span>주차 현황과 출도착</span></Link>
          </nav></SectionCard>
        </div>
      </div>
    </div>
  </>;
}
