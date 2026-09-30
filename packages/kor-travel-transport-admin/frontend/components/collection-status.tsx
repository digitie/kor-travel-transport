"use client";
// weather Dagster의 요약 → 최근 실행 → 접을 수 있는 스케줄 구조를 transport에 적용한다.
import { useEffect, useState } from "react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { dateTime, transportGet } from "@/lib/journey";
import { getDagsterOverview, JOB_LABELS, runStalled, scheduleDescription, statusLabel, type DagsterOverview } from "@/lib/dagster";
type Provider = { source: string; job_status?: string | null; name: string; job_name: string | null; enabled: boolean; mode: string; status: string; interval_seconds: number | null; last_started_at: string | null; last_success_at: string | null; next_due_at: string | null; error_code: string | null };
type Providers = { generated_at: string; items: Provider[]; ferry_window_start: string; ferry_window_end: string; ferry_expected_snapshots: number; ferry_stored_snapshots: number; kric_coverage?: { station_count: number; linked_station_count: number; expected_snapshots: number; stored_snapshots: number; fresh_snapshots: number; oldest_collected_at: string | null } };
export function CollectionStatus() {
  const [providers, setProviders] = useState<Providers | null>(null);
  const [dagster, setDagster] = useState<DagsterOverview | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [reload, setReload] = useState(0);
  const [loading, setLoading] = useState(false);
  const [query, setQuery] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    // 수동 새로고침을 포함한 외부 상태 조회의 시작 상태.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true); setErrors([]);
    const failure = (error: unknown) => { if (!controller.signal.aborted) setErrors((current) => [...current, error instanceof Error ? error.message : "상태 조회 실패"]); };
    Promise.allSettled([
      transportGet<Providers>("transport/providers", controller.signal).then((value) => { if (!controller.signal.aborted) setProviders(value); }).catch(failure),
      getDagsterOverview(controller.signal).then((value) => { if (!controller.signal.aborted) setDagster(value); }).catch(failure),
    ]).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [reload]);
  const fuelReadModel = providers?.items.find((item) => item.source === "fuel_latest_prices");
  return <section className="journey-workbench">
    <div className="journey-toolbar"><label>제공기관·작업 검색<input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="예: 오피넷, 버스, KRIC" /></label><button className="secondary" type="button" disabled={loading} onClick={() => setReload((value) => value + 1)}>{loading ? "확인 중…" : "새로고침"}</button><a className="secondary" href="https://transport-dagster.digitie.mywire.org" target="_blank" rel="noreferrer">Dagster 열기</a></div>
    {errors.map((error) => <p className="error" key={error} role="alert">{error} 이전 결과가 있으면 마지막 성공 조회 내용을 유지합니다.</p>)}
    <div className="ops-grid" aria-label="수집 요약"><div className="panel"><span>등록된 정보 영역</span><strong>{providers?.items.length ?? "—"}</strong></div><div className="panel"><span>사용 중인 스케줄</span><strong>{dagster ? `${dagster.schedules.filter((row) => row.scheduleState.status === "RUNNING").length}/${dagster.schedules.length}` : "—"}</strong></div><div className="panel"><span>최근 실패한 실행</span><strong>{dagster?.runs.filter((row) => row.status === "FAILURE").length ?? "—"}</strong></div><div className="panel"><span>배편 저장 범위</span><strong>{providers ? `${providers.ferry_stored_snapshots.toLocaleString()} / ${providers.ferry_expected_snapshots.toLocaleString()}` : "—"}</strong><small>항구 × 운항일 · 빈 응답 포함</small></div></div>
    {providers ? <p className="quiet">마지막 확인 {dateTime(providers.generated_at)} · 배편 {providers.ferry_window_start}~{providers.ferry_window_end}. 작업 성공과 전국 적재 완료는 다릅니다.</p> : null}
    {fuelReadModel?.error_code ? <Alert variant="destructive"><AlertTitle>최신 유가 표시 지연</AlertTitle><AlertDescription>{fuelReadModel.error_code === "read_model_refresh_delayed" ? "최신 가격 읽기 모델의 재시도가 예정 시각을 넘겼습니다." : "주유소·가격 원본은 저장됐지만 최신 가격 읽기 모델 갱신이 실패했습니다."} 마지막 성공 {dateTime(fuelReadModel.last_success_at)} · 다음 재시도 {dateTime(fuelReadModel.next_due_at)}. 주유소 가격 화면은 마지막으로 갱신된 값일 수 있습니다.</AlertDescription></Alert> : null}
    {providers?.kric_coverage ? <section aria-label="KRIC 시간표 적재 범위"><h2>KRIC 시간표 적재 범위</h2><dl className="provider-detail">
      <div><dt>위치 연결 역사</dt><dd>{providers.kric_coverage.linked_station_count.toLocaleString()} / {providers.kric_coverage.station_count.toLocaleString()}역</dd></div>
      <div><dt>저장 시간표</dt><dd>{providers.kric_coverage.stored_snapshots.toLocaleString()} / {providers.kric_coverage.expected_snapshots.toLocaleString()}개</dd></div>
      <div><dt>48시간 이내 저장본</dt><dd>{providers.kric_coverage.fresh_snapshots.toLocaleString()}개</dd></div>
      <div><dt>가장 오래된 저장 시각</dt><dd>{dateTime(providers.kric_coverage.oldest_collected_at)}</dd></div>
    </dl><p className="quiet">활성 역사 × 평일·토요일·휴일 기준입니다. 빈 정상 응답도 포함하며, 미연결 역사와 오래된 저장본은 다음 열차 안내가 제한됩니다.</p></section> : null}
    <section className="provider-list" aria-label="모든 provider 수집 상태">{providers?.items.filter((item) => [item.name, item.source, item.job_name].join(" ").toLowerCase().includes(query.toLowerCase())).map((item) => <details className="provider-row" key={item.source}><summary><strong>{item.name}</strong><span className={`status-badge ${item.error_code ? "failed" : ""}`}>{statusLabel(item.status)}</span><span className="quiet">{item.mode === "scheduled" ? "정기 수집" : item.mode === "on_demand" ? "명시 요청만" : "통합 필요"}</span></summary><dl className="provider-detail"><div><dt>공동 작업 상태</dt><dd>{item.job_status ? statusLabel(item.job_status) : "이력 없음"}</dd></div><div><dt>최근 시작</dt><dd>{dateTime(item.last_started_at)}</dd></div><div><dt>{item.status.startsWith("shared_job_") ? "공동 작업 최근 성공" : "최근 성공"}</dt><dd>{dateTime(item.last_success_at)}</dd></div><div><dt>{item.source === "kric_timetable" ? "호출 보호 종료" : "다음 실행 예약"}</dt><dd>{item.next_due_at ? dateTime(item.next_due_at) : item.mode === "scheduled" ? "하단 Dagster 스케줄 확인" : "정기 수집 없음"}</dd></div><div><dt>설정 주기</dt><dd>{item.interval_seconds ? `${item.interval_seconds / 3600 >= 1 ? `${item.interval_seconds / 3600}시간` : `${item.interval_seconds / 60}분`}` : "정기 수집 없음"}</dd></div></dl><p className="quiet">{item.job_name ? JOB_LABELS[item.job_name] ?? item.job_name : "연결된 정기 수집 작업 없음"} · {item.enabled ? "수집/조회 설정 활성" : "설정 비활성 또는 미연결"}</p>{item.source === "kric_timetable" ? <p className="quiet">보호 종료는 실행 예약이 아닙니다. 활성화된 Dagster 스케줄이 매시간 수집 가능 여부를 확인합니다.</p> : null}{item.error_code ? <p className="error">수집 실패 · Dagster 실행 로그에서 원인을 확인해 주세요.</p> : null}</details>)}</section>
    <section><h2>최근 실행</h2><div className="run-list">{dagster?.runs.map((run) => <article className="departure-row" key={run.runId}><div><strong>{JOB_LABELS[run.jobName] ?? run.jobName}</strong><p>{statusLabel(run.status)}{runStalled(run) ? " · 실행시간 초과 의심" : ""}</p></div><div><span>시작 {dateTime(run.startTime ? new Date(run.startTime * 1000).toISOString() : null)}</span><p className="quiet">{run.endTime ? `종료 ${dateTime(new Date(run.endTime * 1000).toISOString())}` : "아직 종료 기록 없음"}</p></div><a className="inline-link" href={`https://transport-dagster.digitie.mywire.org/runs/${encodeURIComponent(run.runId)}`} target="_blank" rel="noreferrer">실행 상세</a></article>)}</div>{dagster && !dagster.runs.length ? <p>최근 실행 기록이 없습니다.</p> : null}</section>
    <section><h2>스케줄</h2>{dagster?.schedules.map((schedule) => <details className="provider-row" key={schedule.name}><summary><strong>{JOB_LABELS[schedule.pipelineName] ?? schedule.pipelineName}</strong><span>{schedule.scheduleState.status === "RUNNING" ? "사용" : "중지"}</span></summary><p>{scheduleDescription(schedule.cronSchedule)} · 한국 시각</p><p className="quiet">철도는 48시간, 버스 기준정보는 72시간 경과 여부를 별도 확인합니다. 배편은 4시간마다 누락 범위를 보충하며 저장본의 실제 확인 시각은 운항 화면에 표시합니다.</p></details>)}</section>
  </section>;
}
