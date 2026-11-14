"use client";
// weather Dagster의 요약 → 최근 실행 → 접을 수 있는 스케줄 구조를 transport에 적용한다.
import { useEffect, useState } from "react";
import { DetailList } from "@/components/detail-list";
import { EmptyState } from "@/components/empty-state";
import { FilterActions, FilterBar, FilterField } from "@/components/filter-bar";
import { InfoButton } from "@/components/info-button";
import { SectionCard } from "@/components/section-card";
import { StatStrip } from "@/components/stat-strip";
import { StatusBadge } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { buttonVariants } from "@/components/ui/button-variants";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { dateTime, transportGet } from "@/lib/journey";
import { getDagsterOverview, JOB_LABELS, runStalled, scheduleDescription, statusLabel, type DagsterOverview } from "@/lib/dagster";
import { dagsterLocationUrl, dagsterRunUrl, dagsterJobRunsUrl } from "@/lib/dagster-scope";
import { cn } from "@/lib/utils";

type Provider = { source: string; job_status?: string | null; name: string; job_name: string | null; enabled: boolean; mode: string; status: string; interval_seconds: number | null; last_started_at: string | null; last_success_at: string | null; next_due_at: string | null; error_code: string | null };
type Providers = { generated_at: string; items: Provider[]; ferry_window_start: string; ferry_window_end: string; ferry_expected_snapshots: number; ferry_stored_snapshots: number; kric_coverage?: { station_count: number; linked_station_count: number; expected_snapshots: number; stored_snapshots: number; fresh_snapshots: number; oldest_collected_at: string | null } };

function jobRunHref(jobName: string, dagster: DagsterOverview | null) {
  const run = dagster?.runs.find((row) => row.jobName === jobName);
  return run ? dagsterRunUrl(run.runId) : dagsterJobRunsUrl(jobName);
}

function intervalLabel(seconds: number | null) {
  if (!seconds) return "정기 수집 없음";
  return seconds / 3600 >= 1 ? `${seconds / 3600}시간` : `${seconds / 60}분`;
}

export function CollectionStatus() {
  const { query, setQuery, loading, setReload, errors, providers, dagster, fuelReadModel } = useCollectionStatus();
  return <div className="flex min-w-0 flex-col gap-6">
    <FilterBar>
      <FilterField className="w-full sm:w-72" htmlFor="collection-query" label="제공기관·작업 검색">
        <Input id="collection-query" type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="예: 오피넷, 버스, KRIC" />
      </FilterField>
      <FilterActions>
        <Button loading={loading} type="button" variant="outline" onClick={() => setReload((value) => value + 1)}>새로고침</Button>
        <a className={cn(buttonVariants({ variant: "outline" }))} href={dagsterLocationUrl()} rel="noreferrer" target="_blank">Dagster 열기</a>
      </FilterActions>
    </FilterBar>
    {errors.map((error) => <p className="text-xs text-destructive" key={error} role="alert">{error} 이전 결과가 있으면 마지막 성공 조회 내용을 유지합니다.</p>)}
    <CollectionMetrics providers={providers} dagster={dagster} />
    {providers ? <p className="text-xs text-text-secondary">마지막 확인 {dateTime(providers.generated_at)} · 배편 {providers.ferry_window_start}~{providers.ferry_window_end}. 작업 성공과 전국 적재 완료는 다릅니다.</p> : null}
    {fuelReadModel?.error_code ? <FuelReadModelWarning fuelReadModel={fuelReadModel} /> : null}
    {providers?.kric_coverage ? <section aria-label="KRIC 시간표 적재 범위">
      <SectionCard title="KRIC 시간표 적재 범위">
        <DetailList columns={2} items={[
          { label: "위치 연결 역사", value: `${providers.kric_coverage.linked_station_count.toLocaleString()} / ${providers.kric_coverage.station_count.toLocaleString()}역` },
          { label: "저장 시간표", value: `${providers.kric_coverage.stored_snapshots.toLocaleString()} / ${providers.kric_coverage.expected_snapshots.toLocaleString()}개` },
          { label: "48시간 이내 저장본", value: `${providers.kric_coverage.fresh_snapshots.toLocaleString()}개` },
          { label: "가장 오래된 저장 시각", value: dateTime(providers.kric_coverage.oldest_collected_at) },
        ]} />
        <p className="text-xs text-text-secondary">활성 역사 × 평일·토요일·휴일 기준입니다. 빈 정상 응답도 포함하며, 미연결 역사와 오래된 저장본은 다음 열차 안내가 제한됩니다.</p>
      </SectionCard>
    </section> : null}
    <ProviderCollectionRows providers={providers} query={query} dagster={dagster} />
    <SectionCard title="최근 실행">
      <CollectionRuns dagster={dagster} />
      {dagster && !dagster.runs.length ? <EmptyState size="sm" title="최근 실행 기록이 없습니다." /> : null}
    </SectionCard>
    <SectionCard actions={<InfoButton label="수집 주기와 보호">철도는 48시간, 버스 기준정보는 72시간 경과 여부를 별도 확인합니다. 배편은 4시간마다 누락 범위를 보충합니다. 작업 성공과 전국 적재 완료는 다릅니다.</InfoButton>} title="스케줄">
      <div className="flex flex-col">
        {dagster?.schedules.map((schedule) => <details className="provider-row" key={schedule.name}>
          <summary className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
            <strong className="font-medium text-text-primary">{JOB_LABELS[schedule.pipelineName] ?? schedule.pipelineName}</strong>
            <span className="text-xs text-text-secondary">{schedule.scheduleState.status === "RUNNING" ? "사용" : "중지"}</span>
          </summary>
          <div className="mt-3 flex flex-col gap-2 text-xs text-text-secondary">
            <p>{scheduleDescription(schedule.cronSchedule)} · 한국 시각</p>
            <a className="text-brand underline-offset-4 hover:underline" href={dagsterLocationUrl(`/schedules/${encodeURIComponent(schedule.name)}`)} rel="noreferrer" target="_blank">Dagster 스케줄 열기 ↗</a>
          </div>
        </details>)}
      </div>
    </SectionCard>
  </div>;
}


// 조회·선택·요청 수명은 이 도메인 훅이, 아래 컴포넌트는 표현을 소유한다.
function useCollectionStatus() {
  const [providers, setProviders] = useState<Providers | null>(null);
  const [dagster, setDagster] = useState<DagsterOverview | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [reload, setReload] = useState(0);
  const [loading, setLoading] = useState(false);
  const [query, setQuery] = useState("");
  // 중첩 async의 각 await 뒤 AbortSignal 가드와 cleanup abort가 있다.
  // operations-query-lifecycle 회귀로 독립 응답 표시·두 요청 취소를 검증한다.
  // Doctor 0.9.22는 이 중첩 함수의 공유 signal 가드를 추적하지 못한다.
  // react-doctor-disable-next-line react-doctor/no-set-state-after-await-in-effect
  useEffect(() => {
    const controller = new AbortController();
    // 수동 새로고침을 포함한 외부 상태 조회의 시작 상태.
    setLoading(true); setErrors([]);
    // 두 조회는 독립적으로 즉시 반영하되, 각 await 뒤에 현재 요청의 취소 여부를 검사한다.
    async function loadProviders() {
      try {
        const value = await transportGet<Providers>("transport/providers", controller.signal);
        if (controller.signal.aborted) return;
        setProviders(value);
      } catch (reason) {
        if (controller.signal.aborted) return;
        setErrors((previous) => [...previous, reason instanceof Error ? reason.message : "상태 조회 실패"]);
      }
    }
    async function loadDagster() {
      try {
        const value = await getDagsterOverview(controller.signal);
        if (controller.signal.aborted) return;
        setDagster(value);
      } catch (reason) {
        if (controller.signal.aborted) return;
        setErrors((previous) => [...previous, reason instanceof Error ? reason.message : "상태 조회 실패"]);
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
  const fuelReadModel = providers?.items.find((item) => item.source === "fuel_latest_prices");

  return { query, setQuery, loading, setReload, errors, providers, dagster, fuelReadModel };
}


function ProviderCollectionRows({ providers, query, dagster }: Pick<ReturnType<typeof useCollectionStatus>, "providers" | "query" | "dagster">) {
  return (
    <section aria-label="모든 provider 수집 상태" className="provider-list flex flex-col">
      {providers?.items.filter((item) => [item.name, item.source, item.job_name].join(" ").toLowerCase().includes(query.toLowerCase())).map((item) => <details className="provider-row" key={item.source}>
        <summary className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
          <strong className="font-medium text-text-primary">{item.name}</strong>
          <StatusBadge label={statusLabel(item.status)} status={item.status} tone={item.error_code ? "destructive" : undefined} />
          <span className="text-xs text-text-secondary">{item.mode === "scheduled" ? "정기 수집" : item.mode === "on_demand" ? "명시 요청만" : "통합 필요"}</span>
        </summary>
        <div className="mt-3 flex flex-col gap-3">
          <DetailList columns={2} items={[
            { label: "공동 작업 상태", value: item.job_status ? statusLabel(item.job_status) : "이력 없음" },
            { label: "최근 시작", value: dateTime(item.last_started_at) },
            { label: item.status.startsWith("shared_job_") ? "공동 작업 최근 성공" : "최근 성공", value: dateTime(item.last_success_at) },
            { label: item.source === "kric_timetable" ? "호출 보호 종료" : "다음 실행 예약", value: item.next_due_at ? dateTime(item.next_due_at) : item.mode === "scheduled" ? "하단 Dagster 스케줄 확인" : "정기 수집 없음" },
            { label: "설정 주기", value: intervalLabel(item.interval_seconds) },
          ]} />
          <p className="text-xs text-text-secondary">{item.job_name ? <a className="text-brand underline-offset-4 hover:underline" href={jobRunHref(item.job_name, dagster)} rel="noreferrer" target="_blank">{JOB_LABELS[item.job_name] ?? item.job_name} · 실행 확인 ↗</a> : "연결된 정기 수집 작업 없음"} · {item.enabled ? "수집/조회 설정 활성" : "설정 비활성 또는 미연결"}</p>
          {item.source === "kric_timetable" ? <p className="text-xs text-text-secondary">보호 종료는 실행 예약이 아닙니다. 활성화된 Dagster 스케줄이 매시간 수집 가능 여부를 확인합니다.</p> : null}
          {item.error_code ? <p className="text-xs text-destructive">{item.source === "fuel_latest_prices" ? item.error_code === "read_model_refresh_pending" ? "유가 원본이 최신 가격 읽기 모델보다 새롭습니다. 다음 고속도로 수집에서 갱신합니다." : "유가 원본은 저장됐지만 최신 가격 읽기 모델 갱신이 지연됩니다. 상단 경고와 다음 재시도 시각을 확인해 주세요." : "수집 실패 · Dagster 실행 로그에서 원인을 확인해 주세요."}</p> : null}
        </div>
      </details>)}
    </section>
  );
}


function CollectionRuns({ dagster }: Pick<ReturnType<typeof useCollectionStatus>, "dagster">) {
  if (!dagster?.runs.length) return null;
  return (<ul className="divide-y divide-border">{dagster.runs.map((run) => <li className="flex flex-col gap-2 py-3 first:pt-0 last:pb-0 sm:flex-row sm:items-center sm:justify-between" key={run.runId}>
        <div className="flex min-w-0 flex-col gap-1">
          <strong className="text-sm font-medium text-text-primary">{JOB_LABELS[run.jobName] ?? run.jobName}</strong>
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge label={statusLabel(run.status)} status={run.status} />
            {runStalled(run) ? <span className="text-xs text-text-secondary">· 실행시간 초과 의심</span> : null}
          </div>
        </div>
        <div className="flex flex-col gap-1 text-xs text-text-secondary">
          <span className="tabular-nums">시작 {dateTime(run.startTime ? new Date(run.startTime * 1000).toISOString() : null)}</span>
          <p>{run.endTime ? `종료 ${dateTime(new Date(run.endTime * 1000).toISOString())}` : "아직 종료 기록 없음"}</p>
        </div>
        <a className="text-xs text-brand underline-offset-4 hover:underline" href={dagsterRunUrl(run.runId)} rel="noreferrer" target="_blank">실행 상세</a>
      </li>)}</ul>);
}


function CollectionMetrics({ providers, dagster }: Pick<ReturnType<typeof useCollectionStatus>, "providers" | "dagster">) {
  return (
    <Card size="sm">
      <CardContent>
        <StatStrip ariaLabel="수집 요약" size="lg" className="grid-cols-1 sm:grid-cols-2 xl:grid-cols-4" items={[
          { key: "areas", label: "등록된 정보 영역", value: providers?.items.length ?? null },
          { key: "schedules", label: "사용 중인 스케줄", value: dagster ? `${dagster.schedules.filter((row) => row.scheduleState.status === "RUNNING").length}/${dagster.schedules.length}` : null },
          { key: "failures", label: "최근 실패한 실행", value: dagster ? dagster.runs.filter((row) => row.status === "FAILURE").length : null },
          { key: "ferry", label: "배편 저장 범위", value: providers ? `${providers.ferry_stored_snapshots.toLocaleString()} / ${providers.ferry_expected_snapshots.toLocaleString()}` : null, caption: "항구 × 운항일 · 빈 응답 포함" },
        ]} />
      </CardContent>
    </Card>
  );
}


function FuelReadModelWarning({ fuelReadModel }: { fuelReadModel: NonNullable<ReturnType<typeof useCollectionStatus>["fuelReadModel"]> }) {
  return (<Alert variant="destructive">
      <AlertTitle>최신 유가 표시 지연</AlertTitle>
      <AlertDescription>{fuelReadModel.error_code === "read_model_refresh_delayed" ? "최신 가격 읽기 모델의 재시도가 예정 시각을 넘겼습니다." : fuelReadModel.error_code === "read_model_refresh_pending" ? "원본 가격이 읽기 모델보다 새롭습니다. 다음 고속도로 수집에서 갱신합니다." : "주유소·가격 원본은 저장됐지만 최신 가격 읽기 모델 갱신이 실패했습니다."} 마지막 성공 {dateTime(fuelReadModel.last_success_at)}{fuelReadModel.next_due_at ? ` · 다음 재시도 ${dateTime(fuelReadModel.next_due_at)}` : ""}. 주유소 가격 화면은 마지막으로 갱신된 값일 수 있습니다.</AlertDescription>
    </Alert>);
}
