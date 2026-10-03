"use client";

import { ChevronDown, ChevronRight, ExternalLink, RefreshCw } from "lucide-react";
import { Fragment, useEffect, useState } from "react";
import { PageHeader } from "./admin-shell";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Empty, EmptyHeader, EmptyTitle } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { dateTime } from "@/lib/journey";
import { getDagsterOverview, jobBudgetSeconds, JOB_LABELS, runStalled, scheduleDescription, statusLabel, type DagsterOverview } from "@/lib/dagster";
import { dagsterLocationUrl, dagsterRunUrl } from "@/lib/dagster-scope";
import { cn } from "@/lib/utils";

const epochLabel = (value: number | null) => dateTime(value == null ? null : new Date(value * 1000).toISOString());

export function DagsterTables({ snapshot }: { snapshot: DagsterOverview }) {
  const [expanded, setExpanded] = useState<string | null>(null);
  // 화면의 경과 시간도 마지막 상태 조회 시각에 고정한다.
  const checkedAt = Date.parse(snapshot.checkedAt ?? "") || 0;
  const runs = [...(snapshot.activeRuns ?? []).filter((active) => !snapshot.runs.some((run) => run.runId === active.runId)), ...snapshot.runs];
  return <>
    <Card className="min-w-0">
      <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-4">
        <CardTitle><h2>최근 실행</h2></CardTitle>
        <CardDescription>마지막 확인 {dateTime(snapshot.checkedAt)}</CardDescription>
      </CardHeader>
      <CardContent>
        {runs.length ? <div className="max-w-full overflow-x-auto [&>[data-slot=table-container]]:overflow-visible" role="region" aria-label="최근 Dagster 실행 표" tabIndex={0}>
          <Table className="min-w-[38rem]">
            <TableHeader><TableRow><TableHead scope="col">상태</TableHead><TableHead scope="col">작업</TableHead><TableHead scope="col">시작</TableHead><TableHead scope="col">종료</TableHead><TableHead scope="col">상세</TableHead></TableRow></TableHeader>
            <TableBody>{runs.map((run) => {
              const stalled = checkedAt > 0 && runStalled(run, checkedAt);
              const elapsed = run.startTime != null && (run.endTime != null || checkedAt > 0) ? Math.max(0, Math.floor(((run.endTime ?? checkedAt / 1000) - run.startTime) / 60)) : null;
              return <TableRow key={run.runId}>
                <TableCell>
                  <div className="flex flex-col items-start gap-1">
                    <Badge variant={run.status === "FAILURE" || run.status === "CANCELED" ? "destructive" : stalled ? "warning" : run.status === "SUCCESS" || run.status === "STARTED" ? "success" : "warning"}>{statusLabel(run.status)}</Badge>
                    {elapsed != null ? <small>{elapsed}분 경과{stalled ? " · 정체 의심" : ""}</small> : null}
                  </div>
                </TableCell>
                <TableCell>
                  <div className="flex flex-col items-start gap-1">
                    <span title={run.jobName}>{JOB_LABELS[run.jobName] ?? run.jobName}</span>
                    <code>{run.runId.slice(0, 14)}…</code>
                    {run.status === "FAILURE" ? <small>실패 원인은 실행 상세에서 확인하세요.</small> : null}
                  </div>
                </TableCell>
                <TableCell>{epochLabel(run.startTime)}</TableCell>
                <TableCell>{epochLabel(run.endTime)}</TableCell>
                <TableCell><a data-slot="button" className={cn(buttonVariants({ variant: "link", size: "sm" }))} href={dagsterRunUrl(run.runId)} target="_blank" rel="noreferrer">실행 상세 <ExternalLink data-icon="inline-end" aria-hidden="true" /></a></TableCell>
              </TableRow>;
            })}</TableBody>
          </Table>
        </div> : <Empty><EmptyHeader><EmptyTitle>최근 Dagster 실행이 없습니다.</EmptyTitle></EmptyHeader></Empty>}
      </CardContent>
    </Card>
    <Card className="min-w-0">
      <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-4">
        <CardTitle><h2>스케줄</h2></CardTitle>
        <CardDescription>주기는 한국 시각 기준이며 수집 보호 조건은 별도로 적용됩니다.</CardDescription>
      </CardHeader>
      <CardContent>
        {snapshot.schedules.length ? <div className="max-w-full overflow-x-auto [&>[data-slot=table-container]]:overflow-visible" role="region" aria-label="Dagster 스케줄 표" tabIndex={0}>
          <Table className="min-w-[30rem]">
            <TableHeader><TableRow><TableHead scope="col">작업</TableHead><TableHead scope="col">주기</TableHead><TableHead scope="col">상태</TableHead></TableRow></TableHeader>
            <TableBody>{snapshot.schedules.map((schedule) => <Fragment key={schedule.name}>
              <TableRow>
                <TableCell><Button type="button" variant="ghost" aria-expanded={expanded === schedule.name} onClick={() => setExpanded((value) => value === schedule.name ? null : schedule.name)}>
                  {expanded === schedule.name ? <ChevronDown data-icon="inline-start" aria-hidden="true" /> : <ChevronRight data-icon="inline-start" aria-hidden="true" />}
                  {JOB_LABELS[schedule.pipelineName] ?? schedule.pipelineName}
                </Button></TableCell>
                <TableCell>{scheduleDescription(schedule.cronSchedule)}</TableCell>
                <TableCell><Badge variant={schedule.scheduleState.status === "RUNNING" ? "success" : schedule.scheduleState.status === "STOPPED" ? "destructive" : "warning"}>{schedule.scheduleState.status === "RUNNING" ? "사용" : schedule.scheduleState.status === "STOPPED" ? "중지" : "상태 확인 필요"}</Badge></TableCell>
              </TableRow>
              {expanded === schedule.name ? <TableRow><TableCell colSpan={3} className="whitespace-normal">
                <div className="flex flex-col gap-4">
                  <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
                    <div><dt>실행 작업</dt><dd className="mt-1 wrap-anywhere">{schedule.pipelineName}</dd></div>
                    <div><dt>스케줄 이름</dt><dd className="mt-1 wrap-anywhere">{schedule.name}</dd></div>
                    <div><dt>실행 주기 원본</dt><dd className="mt-1 wrap-anywhere">{schedule.cronSchedule}</dd></div>
                    <div><dt>장시간 실행 확인 기준</dt><dd className="mt-1">{jobBudgetSeconds(schedule.pipelineName) / 60}분</dd></div>
                  </dl>
                  <p>KRIC 48시간·버스 기준정보 72시간 보호를 따릅니다. 배편은 4시간마다 누락 범위를 보충합니다. 실행 성공은 전국 자료 적재 완료를 뜻하지 않습니다.</p>
                </div>
              </TableCell></TableRow> : null}
            </Fragment>)}</TableBody>
          </Table>
        </div> : <Empty><EmptyHeader><EmptyTitle>등록된 스케줄이 없습니다.</EmptyTitle></EmptyHeader></Empty>}
      </CardContent>
    </Card>
  </>;
}

export function DagsterOperations() {
  const [snapshot, setSnapshot] = useState<DagsterOverview | null>(null);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(true);
  const [reload, setReload] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    getDagsterOverview(AbortSignal.any([controller.signal, AbortSignal.timeout(25_000)]))
      .then((value) => { if (!controller.signal.aborted) setSnapshot(value); })
      .catch(() => { if (!controller.signal.aborted) setError(true); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [reload]);
  function refresh() { setLoading(true); setError(false); setReload((value) => value + 1); }
  const stalled = (snapshot?.activeRuns ?? snapshot?.runs ?? []).filter((run) => runStalled(run, Date.parse(snapshot?.checkedAt ?? ""))).length;
  return <>
    <PageHeader title="Dagster" description="자동 수집 작업의 실행 기록과 스케줄을 확인합니다. 제공기관별 저장 범위는 수집 상태 메뉴에서 확인하세요." actions={<><Button variant="outline" type="button" disabled={loading} onClick={refresh}>{loading ? <Spinner data-icon="inline-start" aria-hidden="true" /> : <RefreshCw data-icon="inline-start" aria-hidden="true" />}{loading ? "확인 중…" : "새로고침"}</Button><a data-slot="button" className={cn(buttonVariants({ variant: "outline" }))} href={dagsterLocationUrl()} target="_blank" rel="noreferrer">Dagster UI <ExternalLink data-icon="inline-end" aria-hidden="true" /></a></>} />
    <div className="journey-workbench dagster-workbench" aria-busy={loading}>
      {error ? <Alert variant="destructive"><AlertDescription>{snapshot ? "Dagster 갱신에 실패해 마지막 확인 결과를 표시합니다." : "Dagster 상태를 불러오지 못했습니다."} 새로고침으로 다시 확인해 주세요.</AlertDescription></Alert> : null}
      {stalled > 0 ? <Alert variant="destructive"><AlertDescription>{stalled}개 실행이 작업별 확인 기준을 넘었습니다. 실제 저장 진행 여부를 실행 상세에서 확인하세요.</AlertDescription></Alert> : null}
      <section className="ops-grid" aria-label="Dagster 요약">{[
        ["사용 중인 스케줄", snapshot ? `${snapshot.schedules.filter((row) => row.scheduleState.status === "RUNNING").length}/${snapshot.schedules.length}` : "—", "전체 스케줄 대비"],
        ["최근 성공", snapshot ? snapshot.runs.filter((row) => row.status === "SUCCESS").length : "—", `최근 ${snapshot?.runs.length ?? 0}건 중`],
        ["최근 실패", snapshot ? snapshot.runs.filter((row) => row.status === "FAILURE").length : "—", "원인 확인 대상"],
        ["장시간 실행", snapshot ? stalled : "—", "작업별 확인 기준 적용"],
      ].map(([label, value, caption]) => <Card className="ops-card min-h-40 min-w-0 gap-3" key={label}>
        <CardHeader><CardTitle className="text-xs leading-normal tracking-[0.04em] text-muted-foreground">{label}</CardTitle></CardHeader>
        <CardContent className="flex flex-col gap-2">
          {loading && !snapshot ? <Skeleton className="h-7 w-12" aria-hidden="true" /> : <strong>{value}</strong>}
          <CardDescription className="text-[0.8125rem] leading-[1.45]">{caption}</CardDescription>
        </CardContent>
      </Card>)}</section>
      {snapshot ? <DagsterTables snapshot={snapshot} /> : loading ? <div className="flex flex-col gap-4">
        <p role="status" className="flex items-center gap-2"><Spinner aria-hidden="true" />실행 기록·스케줄을 불러오는 중…</p>
        <Skeleton className="h-40 w-full" aria-hidden="true" />
        <Skeleton className="h-40 w-full" aria-hidden="true" />
      </div> : null}
    </div>
  </>;
}
