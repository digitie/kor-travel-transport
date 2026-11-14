"use client";

// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Youn-sok Choi (digitie)
// Derived-From: kor-travel-map@974e2d025 home-client.tsx 운영 요약·실행·상태 배치
import type { ColumnDef } from "@kor-travel/ui/virtual-table";
import { ExternalLink, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { PageHeader } from "@/components/admin-shell";
import { DetailList } from "@/components/detail-list";
import { EmptyState } from "@/components/empty-state";
import { SectionCard } from "@/components/section-card";
import { StatStrip } from "@/components/stat-strip";
import { StatusBadge } from "@/components/status-badge";
import { Alert, AlertActions, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { buttonVariants } from "@/components/ui/button-variants";
import { Card } from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
import { getDagsterOverview, JOB_LABELS, statusLabel, type DagsterOverview } from "@/lib/dagster";
import { dagsterLocationUrl, dagsterRunUrl, dagsterJobRunsUrl } from "@/lib/dagster-scope";
import { needsProviderAttention } from "@/lib/provider-status";
import { dateTime, transportGet } from "@/lib/journey";
import { cn } from "@/lib/utils";

type Provider = {
  source: string; name: string; enabled: boolean; mode: string; status: string;
  last_success_at: string | null; next_due_at: string | null; error_code: string | null;
};
type ProviderOverview = {
  generated_at: string; items: Provider[];
  kric_coverage?: { station_count: number; linked_station_count: number; expected_snapshots: number; stored_snapshots: number; fresh_snapshots: number } | null;
};
type DagsterRun = DagsterOverview["runs"][number];

const HOME_STAT_COLUMNS = "grid-cols-1 sm:grid-cols-2 xl:grid-cols-4";
const RUN_COLUMNS: ColumnDef<DagsterRun, unknown>[] = [
  {
    id: "job",
    accessorKey: "jobName",
    header: "작업",
    enableSorting: false,
    cell: ({ row }) => (
      <a className="text-brand underline-offset-4 hover:underline" href={dagsterJobRunsUrl(row.original.jobName)} rel="noreferrer" target="_blank">
        {JOB_LABELS[row.original.jobName] ?? row.original.jobName}
      </a>
    ),
  },
  {
    id: "status",
    accessorKey: "status",
    header: "상태",
    enableSorting: false,
    cell: ({ row }) => <StatusBadge label={statusLabel(row.original.status)} status={row.original.status} />,
  },
  {
    id: "startedAt",
    accessorKey: "startTime",
    header: "시작 시각",
    enableSorting: false,
    cell: ({ row }) => (
      <span className="text-text-secondary tabular-nums">
        {dateTime(row.original.startTime ? new Date(row.original.startTime * 1000).toISOString() : null)}
      </span>
    ),
  },
  {
    id: "run",
    accessorKey: "runId",
    header: "실행",
    enableSorting: false,
    cell: ({ row }) => (
      <a className="inline-flex items-center gap-1 text-brand underline-offset-4 hover:underline" href={dagsterRunUrl(row.original.runId)} rel="noreferrer" target="_blank">
        상세<ExternalLink aria-hidden="true" size={12} />
      </a>
    ),
  },
];
const TRAFFIC_LINKS = [
  ["/map", "교통 지도", "역·공항·터미널 위치"],
  ["/highways", "고속도로", "지도·소통·돌발"],
  ["/fuel/statistics", "유가 통계", "지역·고속도로 가격 비교"],
  ["/flights", "비행·공항", "주차 현황과 출도착"],
] as const;

export function OperationsHome() {
  const { loading, refresh, errors, activeProviders, providers, attention, activeRuns, dagster, runningSchedules, failedRuns, recentRuns, coverage } = useOperationsOverview();
  return <>
    <PageHeader title="운영 홈" description="운영 상태를 한 화면에서 확인합니다." actions={<>
      <Button type="button" variant="outline" loading={loading} onClick={refresh}><RefreshCw aria-hidden="true" data-icon="inline-start" />새로고침</Button>
      <a className={cn(buttonVariants({ variant: "outline" }))} href={dagsterLocationUrl()} rel="noreferrer" target="_blank"><ExternalLink aria-hidden="true" data-icon="inline-start" />Dagster</a>
    </>} />
    <OperationsSummary errors={errors} activeProviders={activeProviders} providers={providers} attention={attention} activeRuns={activeRuns} dagster={dagster} runningSchedules={runningSchedules} failedRuns={failedRuns} recentRuns={recentRuns} coverage={coverage} loading={loading} refresh={refresh} />
  </>;
}


// 조회·선택·요청 수명은 이 도메인 훅이, 아래 컴포넌트는 표현을 소유한다.
function useOperationsOverview() {
  const [providers, setProviders] = useState<ProviderOverview | null>(null);
  const [dagster, setDagster] = useState<DagsterOverview | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [reload, setReload] = useState(0);
  // 중첩 async의 각 await 뒤 AbortSignal 가드와 cleanup abort가 있다.
  // operations-query-lifecycle 회귀로 독립 응답 표시·두 요청 취소를 검증한다.
  // Doctor 0.9.22는 이 중첩 함수의 공유 signal 가드를 추적하지 못한다.
  // react-doctor-disable-next-line react-doctor/no-set-state-after-await-in-effect
  useEffect(() => {
    const controller = new AbortController();
    // 두 조회는 독립적으로 즉시 반영하되, 각 await 뒤에 현재 요청의 취소 여부를 검사한다.
    async function loadProviders() {
      try {
        const value = await transportGet<ProviderOverview>("transport/providers", controller.signal);
        if (controller.signal.aborted) return;
        setProviders(value);
      } catch (reason) {
        if (controller.signal.aborted) return;
        setErrors((previous) => ({ ...previous, "수집 상태": reason instanceof Error ? reason.message : "조회 실패" }));
      }
    }
    async function loadDagster() {
      try {
        const value = await getDagsterOverview(controller.signal);
        if (controller.signal.aborted) return;
        setDagster(value);
      } catch (reason) {
        if (controller.signal.aborted) return;
        setErrors((previous) => ({ ...previous, "파이프라인": reason instanceof Error ? reason.message : "조회 실패" }));
      }
    }
    async function load() {
      await Promise.all([loadProviders(), loadDagster()]);
      if (controller.signal.aborted) return;
      setLoading(false);
    }
    void load();
    return () => controller.abort();
  }, [reload]);
  function refresh() {
    setProviders(null); setDagster(null); setErrors({}); setLoading(true); setReload((value) => value + 1);
  }
  const activeProviders = providers?.items.filter((item) => item.enabled && item.mode === "scheduled");
  const attention = providers?.items.filter(needsProviderAttention);
  const coverage = providers?.kric_coverage;
  const activeRuns = dagster?.activeRuns;
  const recentRuns = dagster?.runs ?? [];
  const failedRuns = dagster ? recentRuns.filter((run) => run.status === "FAILURE").length : null;
  const runningSchedules = dagster?.schedules.filter((schedule) => schedule.scheduleState.status === "RUNNING").length;

  return { loading, refresh, errors, activeProviders, providers, attention, activeRuns, dagster, runningSchedules, failedRuns, recentRuns, coverage };
}


function OperationsSummary({ errors, activeProviders, providers, attention, activeRuns, dagster, runningSchedules, failedRuns, recentRuns, coverage, loading, refresh }: Pick<ReturnType<typeof useOperationsOverview>, "errors" | "activeProviders" | "providers" | "attention" | "activeRuns" | "dagster" | "runningSchedules" | "failedRuns" | "recentRuns" | "coverage" | "loading" | "refresh">) {
  return (<div className="operations-home space-y-6">
      {Object.keys(errors).length ? <Alert variant="destructive">
        <AlertTitle>운영 요약 확인 필요</AlertTitle>
        <AlertDescription>
          {Object.entries(errors).map(([name, message]) => <p key={name}>{name} · {message}</p>)}
          <p>확인하지 못한 값은 —로 표시됩니다.</p>
        </AlertDescription>
        <AlertActions>
          <Button size="sm" type="button" variant="outline" loading={loading} onClick={refresh}>다시 시도</Button>
        </AlertActions>
      </Alert> : null}
      <OperationsMetrics activeProviders={activeProviders} providers={providers} attention={attention} activeRuns={activeRuns} dagster={dagster} runningSchedules={runningSchedules} failedRuns={failedRuns} recentRuns={recentRuns} coverage={coverage} />
      <div className="grid min-w-0 gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="min-w-0 space-y-6">
          <RecentOperations recentRuns={recentRuns} dagster={dagster} loading={loading} />
          <ProviderAttention attention={attention} providers={providers} loading={loading} />
        </div>
        <div className="min-w-0 space-y-6">
          <OperationsHealth providers={providers} loading={loading} dagster={dagster} coverage={coverage} />
          <SectionCard title="교통 정보">
            <nav aria-label="교통 정보 바로가기" className="flex flex-col divide-y divide-border">
              {TRAFFIC_LINKS.map(([href, label, caption]) => <Link className="flex flex-col gap-0.5 rounded-control py-2.5 text-sm font-medium text-text-primary first:pt-0 last:pb-0 hover:text-brand focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus" href={href} key={href}>
                {label}<span className="text-xs font-normal text-text-secondary">{caption}</span>
              </Link>)}
            </nav>
          </SectionCard>
        </div>
      </div>
    </div>);
}

type SummaryProps = NonNullable<Parameters<typeof OperationsSummary>[0]>;

function OperationsMetrics({ activeProviders, providers, attention, activeRuns, dagster, runningSchedules, failedRuns, recentRuns, coverage }: Pick<SummaryProps, "activeProviders" | "providers" | "attention" | "activeRuns" | "dagster" | "runningSchedules" | "failedRuns" | "recentRuns" | "coverage">) {
  return (<Card size="sm">
        <StatStrip size="lg" ariaLabel="운영 요약" className={HOME_STAT_COLUMNS} items={[
          { key: "sources", label: "활성 수집 소스", value: activeProviders?.length, unit: "개", href: "/collections", caption: providers ? `전체 ${providers.items.length}개 소스 · 확인 필요 ${attention?.length ?? 0}개` : "수집 상태 확인 중", testId: "home-stat-sources" },
          { key: "pipeline", label: "진행 중 작업", value: activeRuns?.length, unit: "건", href: "/admin/dagster", caption: dagster ? `스케줄 ${runningSchedules ?? 0} / ${dagster.schedules.length}개 사용` : "파이프라인 상태 확인 중", testId: "home-stat-pipeline" },
          { key: "failures", label: "최근 실행 실패", value: failedRuns, unit: "건", href: "/admin/dagster", caption: dagster ? `조회한 최근 ${recentRuns.length}건 기준` : "최근 실행 확인 중", tone: failedRuns ? "destructive" : "neutral", testId: "home-stat-failures" },
          { key: "timetables", label: "도시철도 시간표", value: coverage?.fresh_snapshots, unit: "역·요일", href: "/rail/metro", caption: coverage ? `필요 ${coverage.expected_snapshots.toLocaleString()}개 · 저장 ${coverage.stored_snapshots.toLocaleString()}개` : "저장 범위 확인 중", testId: "home-stat-timetables" },
        ]} />
      </Card>);
}


function RecentOperations({ recentRuns, dagster, loading }: Pick<SummaryProps, "recentRuns" | "dagster" | "loading">) {
  const runsEmptyTitle = !dagster
    ? loading ? "최근 실행을 확인하는 중입니다…" : "최근 실행을 확인하지 못했습니다."
    : "최근 실행 기록이 없습니다.";
  return (<SectionCard title="최근 실행" description="이 Transport 코드 위치의 최근 실행입니다." actions={<Link className={cn(buttonVariants({ variant: "ghost", size: "sm" }))} href="/admin/dagster">전체 실행</Link>}>
            <DataTable
              ariaLabel="조회 결과"
              columns={RUN_COLUMNS}
              data={recentRuns.slice(0, 8)}
              emptyState={{ title: runsEmptyTitle }}
              getRowId={(run) => run.runId}
              isLoading={!dagster && loading}
              manualSorting={false}
            />
            {dagster?.warning ? <p className="text-xs text-text-secondary" role="status">{dagster.warning}</p> : null}
          </SectionCard>);
}


function ProviderAttention({ attention, providers, loading }: Pick<SummaryProps, "attention" | "providers" | "loading">) {
  return (<SectionCard title="확인이 필요한 수집" description="실패와 수집 이력 부재를 구분해 확인합니다." actions={<Link className={cn(buttonVariants({ variant: "ghost", size: "sm" }))} href="/collections">수집 상태</Link>}>
            {attention?.length ? <ul className="divide-y divide-border">{attention.map((item) => <li className="flex flex-col gap-1 py-3 first:pt-0 last:pb-0" key={item.source}>
              <div className="flex flex-wrap items-center gap-2">
                <strong className="text-sm font-medium text-text-primary">{item.name}</strong>
                <StatusBadge label={statusLabel(item.status)} status={item.status} tone="destructive" />
              </div>
              <p className="text-xs text-text-secondary">마지막 성공 {dateTime(item.last_success_at)}{item.next_due_at ? ` · 다음 평가 ${dateTime(item.next_due_at)}` : ""}</p>
            </li>)}</ul> : <EmptyState size="sm" title={providers ? "확인이 필요한 수집 오류가 없습니다." : loading ? "수집 상태를 확인하는 중입니다…" : "수집 상태를 확인하지 못했습니다."} />}
          </SectionCard>);
}


function OperationsHealth({ providers, loading, dagster, coverage }: Pick<SummaryProps, "providers" | "loading" | "dagster" | "coverage">) {
  return (<SectionCard title="운영 상태">
            <DetailList columns={1} layout="inline" items={[
              { label: "저장 API", value: providers ? "응답 정상" : loading ? "확인 중" : "확인 실패" },
              { label: "Dagster", value: dagster ? "응답 정상" : loading ? "확인 중" : "확인 실패" },
              { label: "시간표 역 연결", value: coverage ? `${coverage.linked_station_count.toLocaleString()} / ${coverage.station_count.toLocaleString()}역` : null },
              { label: "수집 상태 확인", value: dateTime(providers?.generated_at) },
            ]} />
          </SectionCard>);
}
