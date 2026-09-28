"use client";

import { ChevronDown, ChevronRight, ExternalLink, RefreshCw } from "lucide-react";
import { Fragment, useEffect, useState } from "react";
import { PageHeader } from "./admin-shell";
import { dateTime } from "@/lib/journey";
import { getDagsterOverview, jobBudgetSeconds, JOB_LABELS, runStalled, scheduleDescription, statusLabel, type DagsterOverview } from "@/lib/dagster";

const DAGSTER_URL = "https://transport-dagster.digitie.mywire.org";
const epochLabel = (value: number | null) => dateTime(value == null ? null : new Date(value * 1000).toISOString());

export function DagsterTables({ snapshot }: { snapshot: DagsterOverview }) {
  const [expanded, setExpanded] = useState<string | null>(null);
  // 화면의 경과 시간도 마지막 상태 조회 시각에 고정한다.
  const checkedAt = Date.parse(snapshot.checkedAt ?? "") || 0;
  return <>
    <section className="panel dagster-runs"><div className="panel-head"><h2>최근 실행</h2><p>마지막 확인 {dateTime(snapshot.checkedAt)}</p></div>
      {snapshot.runs.length ? <div className="table-wrap" role="region" aria-label="최근 Dagster 실행 표" tabIndex={0}><table><thead><tr><th scope="col">상태</th><th scope="col">작업</th><th scope="col">시작</th><th scope="col">종료</th><th scope="col">상세</th></tr></thead><tbody>{snapshot.runs.map((run) => {
        const stalled = checkedAt > 0 && runStalled(run, checkedAt);
        const elapsed = run.startTime != null && (run.endTime != null || checkedAt > 0) ? Math.max(0, Math.floor(((run.endTime ?? checkedAt / 1000) - run.startTime) / 60)) : null;
        return <tr key={run.runId}><td><span className={`status-badge ${run.status === "FAILURE" ? "failed" : stalled ? "warning" : ""}`}>{statusLabel(run.status)}</span>{elapsed != null ? <small className="dagster-run-elapsed">{elapsed}분 경과{stalled ? " · 정체 의심" : ""}</small> : null}</td><td><strong title={run.jobName}>{JOB_LABELS[run.jobName] ?? run.jobName}</strong><code>{run.runId.slice(0, 14)}…</code>{run.status === "FAILURE" ? <small className="error">실패 원인은 실행 상세에서 확인하세요.</small> : null}</td><td>{epochLabel(run.startTime)}</td><td>{epochLabel(run.endTime)}</td><td><a className="inline-link" href={`${DAGSTER_URL}/runs/${encodeURIComponent(run.runId)}`} target="_blank" rel="noreferrer">실행 상세 <ExternalLink size={13} aria-hidden="true" /></a></td></tr>;
      })}</tbody></table></div> : <p className="empty-state">최근 Dagster 실행이 없습니다.</p>}
    </section>
    <section className="panel dagster-schedules"><div className="panel-head"><h2>스케줄</h2><p>주기는 한국 시각 기준이며 수집 보호 조건은 별도로 적용됩니다.</p></div>
      {snapshot.schedules.length ? <div className="table-wrap" role="region" aria-label="Dagster 스케줄 표" tabIndex={0}><table><thead><tr><th scope="col">작업</th><th scope="col">주기</th><th scope="col">상태</th></tr></thead><tbody>{snapshot.schedules.map((schedule) => <Fragment key={schedule.name}><tr><td><button type="button" className="row-expand-toggle" aria-expanded={expanded === schedule.name} onClick={() => setExpanded((value) => value === schedule.name ? null : schedule.name)}>{expanded === schedule.name ? <ChevronDown size={14} aria-hidden="true" /> : <ChevronRight size={14} aria-hidden="true" />}{JOB_LABELS[schedule.pipelineName] ?? schedule.pipelineName}</button></td><td>{scheduleDescription(schedule.cronSchedule)}</td><td><span className="status-badge">{schedule.scheduleState.status === "RUNNING" ? "사용" : schedule.scheduleState.status === "STOPPED" ? "중지" : "상태 확인 필요"}</span></td></tr>{expanded === schedule.name ? <tr className="sync-run-detail-row"><td colSpan={3}><dl className="sync-run-detail-grid"><div><dt>실행 작업</dt><dd>{schedule.pipelineName}</dd></div><div><dt>스케줄 이름</dt><dd>{schedule.name}</dd></div><div><dt>실행 주기 원본</dt><dd>{schedule.cronSchedule}</dd></div><div><dt>장시간 실행 확인 기준</dt><dd>{jobBudgetSeconds(schedule.pipelineName) / 60}분</dd></div></dl><p className="quiet">KRIC 48시간·버스 기준정보 72시간 보호를 따릅니다. 배편은 4시간마다 누락 범위를 보충합니다. 실행 성공은 전국 자료 적재 완료를 뜻하지 않습니다.</p></td></tr> : null}</Fragment>)}</tbody></table></div> : <p className="empty-state">등록된 스케줄이 없습니다.</p>}
    </section>
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
  const stalled = snapshot?.runs.filter((run) => runStalled(run, Date.parse(snapshot.checkedAt ?? ""))).length ?? 0;
  return <>
    <PageHeader title="Dagster" description="자동 수집 작업의 실행 기록과 스케줄을 확인합니다. 제공기관별 저장 범위는 수집 상태 메뉴에서 확인하세요." actions={<><button className="secondary" type="button" disabled={loading} onClick={refresh}><RefreshCw size={15} aria-hidden="true" />{loading ? "확인 중…" : "새로고침"}</button><a className="secondary" href={DAGSTER_URL} target="_blank" rel="noreferrer">Dagster UI <ExternalLink size={15} aria-hidden="true" /></a></>} />
    <div className="journey-workbench" aria-busy={loading}>
      {error ? <p className="error" role="alert">{snapshot ? "Dagster 갱신에 실패해 마지막 확인 결과를 표시합니다." : "Dagster 상태를 불러오지 못했습니다."} 새로고침으로 다시 확인해 주세요.</p> : null}
      {stalled > 0 ? <p className="error" role="alert">{stalled}개 실행이 작업별 확인 기준을 넘었습니다. 실제 저장 진행 여부를 실행 상세에서 확인하세요.</p> : null}
      <section className="ops-grid" aria-label="Dagster 요약">{[
        ["사용 중인 스케줄", snapshot ? `${snapshot.schedules.filter((row) => row.scheduleState.status === "RUNNING").length}/${snapshot.schedules.length}` : "—", "전체 스케줄 대비"],
        ["최근 성공", snapshot ? snapshot.runs.filter((row) => row.status === "SUCCESS").length : "—", `최근 ${snapshot?.runs.length ?? 0}건 중`],
        ["최근 실패", snapshot ? snapshot.runs.filter((row) => row.status === "FAILURE").length : "—", "원인 확인 대상"],
        ["장시간 실행", snapshot ? stalled : "—", "작업별 확인 기준 적용"],
      ].map(([label, value, caption]) => <div className="panel ops-card" key={label}><span>{label}</span><strong>{value}</strong><small>{caption}</small></div>)}</section>
      {snapshot ? <DagsterTables snapshot={snapshot} /> : loading ? <p role="status">실행 기록·스케줄을 불러오는 중…</p> : null}
    </div>
  </>;
}
