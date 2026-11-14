"use client";

import { VirtualTable } from "@kor-travel/ui/virtual-table";
import Link from "next/link";
import { useEffect, useState } from "react";
import { transportGet, dateTime } from "@/lib/journey";
import { currentSpeeds, type SpeedObservation } from "@/lib/driver-statistics";
import { highwayRouteLabel } from "@/lib/transport-presentation";
import { FilterActions, FilterBar, FilterField } from "@/components/filter-bar";
import { SectionCard } from "./section-card";
import { StatStrip } from "./stat-strip";
import { Alert, AlertDescription } from "./ui/alert";
import { Button } from "./ui/button";
import { NativeSelect } from "./ui/native-select";
import { NativeSelectOption } from "./ui/native-select-option";

const inlineLink = "rounded-control text-sm font-medium text-brand underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";
const decimal = (n: number | null) => n === null ? null : n.toLocaleString("ko-KR", { maximumFractionDigits: 1 });
const SAMPLE_LIMIT = 1000;
export function HighwayStatistics() {
  const { route, setState, setRoute, options, setRevision, state, stats, sampleSegments } = useHighwayStatistics();
  return <div className="flex flex-col gap-6">
    <FilterBar>
      <FilterField label="고속도로"><NativeSelect value={route} onChange={(event) => { setState({}); setRoute(event.target.value); }}><NativeSelectOption value="">전체 노선(최근 관측 1,000행 표본)</NativeSelectOption>{options.map(([id, name]) => <NativeSelectOption key={id} value={id}>{name}</NativeSelectOption>)}</NativeSelect></FilterField>
      <FilterActions>
        <Button type="button" variant="outline" onClick={() => { setState({}); setRevision((v) => v + 1); }}>새로고침</Button>
        <Link className={inlineLink} href="/highways">지도에서 확인</Link>
      </FilterActions>
    </FilterBar>
    {state.error ? <Alert variant="destructive"><AlertDescription>고속도로 통계를 불러오지 못했습니다.</AlertDescription></Alert> : !state.rows ? <p role="status" className="text-sm text-text-secondary">최근 구간 관측을 확인하는 중입니다…</p> : null}
    <HighwaySpeedMetrics stats={stats} route={route} sampleSegments={sampleSegments} state={state} />
    <HighwaySpeedTable stats={stats} />
  </div>;
}


// 조회·선택·요청 수명은 이 도메인 훅이, 아래 컴포넌트는 표현을 소유한다.
function useHighwayStatistics() {
  const [state, setState] = useState<{ rows?: SpeedObservation[]; checked?: string; error?: boolean }>({});
  const [route, setRoute] = useState("");
  // 노선 선택지: 1일 통계(서버 캐시 60초)의 교통 노선과 조회 표본의 합집합이다. 표본에 없는 노선도 고를 수 있다.
  const [routeLabels, setRouteLabels] = useState<Record<string, string>>({});
  const [revision, setRevision] = useState(0);
  const [trafficRevision, setTrafficRevision] = useState(0);
  const [clock, setClock] = useState(() => Date.now());
  useEffect(() => {
    const refreshVisible = () => {
      setClock(Date.now());
      if (document.visibilityState !== "hidden") setTrafficRevision((value) => value + 1);
    };
    const timer = setInterval(refreshVisible, 60_000);
    document.addEventListener("visibilitychange", refreshVisible);
    return () => { clearInterval(timer); document.removeEventListener("visibilitychange", refreshVisible); };
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    // 전체 노선은 최근 관측 1,000행 표본이다. 노선을 고르면 그 노선만 다시 조회해 최신 주기 전체로 계산한다.
    const query = new URLSearchParams({ days: "1", limit: String(SAMPLE_LIMIT) });
    if (route) query.set("route_no", route);
    transportGet<{ items: SpeedObservation[]; generated_at: string }>(`transport/highways/traffic?${query}`, controller.signal)
      .then((data) => {
        if (controller.signal.aborted) return;
        setState({ rows: data.items, checked: data.generated_at });
        setRouteLabels((labels) => ({ ...labels, ...Object.fromEntries(data.items.filter((row) => row.route_no)
          .map((row) => [row.route_no!, highwayRouteLabel(row.route_no, row.route_name)])) }));
      })
      .catch(() => { if (!controller.signal.aborted) setState((current) => ({ ...current, error: true })); });
    return () => controller.abort();
  }, [revision, route, trafficRevision]);
  useEffect(() => {
    const controller = new AbortController();
    transportGet<{ traffic: { route_no: string | null }[] }>("transport/statistics?days=1", controller.signal)
      .then((data) => {
        if (controller.signal.aborted) return;
        // 표본에서 받은 노선 이름이 있으면 그것을 유지한다.
        setRouteLabels((labels) => ({ ...Object.fromEntries(data.traffic.filter((row) => row.route_no)
          .map((row) => [row.route_no!, highwayRouteLabel(row.route_no)])), ...labels }));
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, [revision]);
  const options = Object.entries(routeLabels).sort(([a], [b]) => a.localeCompare(b, "ko", { numeric: true }));
  const stats = state.rows ? currentSpeeds(state.rows.filter((row) => !route || row.route_no === route), clock) : null;
  const sampleSegments = state.rows ? new Set(state.rows.map((row) => row.identity_key)).size : null;

  return { route, setState, setRoute, options, setRevision, state, stats, sampleSegments };
}


function HighwaySpeedMetrics({ stats, route, sampleSegments, state }: Pick<ReturnType<typeof useHighwayStatistics>, "stats" | "route" | "sampleSegments" | "state">) {
  return (<SectionCard title="최근 15분 구간 속도" description="구간별 마지막 관측을 같은 비중으로 비교합니다. 실제 경로 소요시간이나 교통량 가중 평균이 아닙니다.">
      <StatStrip ariaLabel="고속도로 운전 지표" items={speedMetrics(stats)} />
      <p className="text-sm text-text-secondary">{route
        ? `선택 노선의 최근 관측(최대 ${SAMPLE_LIMIT.toLocaleString("ko-KR")}행)에서 구간별 최신 관측을 추립니다. `
        : `전체 노선은 최근 관측 ${SAMPLE_LIMIT.toLocaleString("ko-KR")}행 표본${sampleSegments !== null ? `(표본 구간 ${sampleSegments.toLocaleString("ko-KR")}곳)` : ""}으로 계산하므로 전체 구간 집계가 아닙니다. 노선을 고르면 그 노선의 최신 관측을 다시 조회합니다. `}
        {stats ? `15분 초과·결측 등 ${stats.excluded}구간 제외 · ` : ""}조회 {dateTime(state.checked)}. 속도 구간은 이 화면의 비교 기준입니다.</p>
    </SectionCard>);
}


function HighwaySpeedTable({ stats }: Pick<ReturnType<typeof useHighwayStatistics>, "stats">) {
  return (<SectionCard title="속도가 낮은 구간부터" description="출발 전 관심 노선의 정체 위치와 방향을 확인하세요.">
      <div className="overflow-x-auto"><VirtualTable ariaLabel="조회 결과" data={[...(stats?.rows ?? [])].sort((a, b) => a.speed! - b.speed!).slice(0, 100)} getRowId={(row) => String(row.identity_key)} virtualized={false} columns={[{ id: 'column0', header: '노선', cell: ({ row: { original: row } }) => <>{highwayRouteLabel(row.route_no, row.route_name)}</> },
{ id: 'column1', header: '구간', cell: ({ row: { original: row } }) => <>{(row as SpeedObservation & { conzone_name?: string }).conzone_name ?? "구간명 미제공"}</> },
{ id: 'column2', header: '방향', cell: ({ row: { original: row } }) => <>{(row as SpeedObservation & { direction?: string }).direction ?? "—"}</> },
{ id: 'column3', header: '속도(km/h)', cell: ({ row: { original: row } }) => <span className="tabular-nums">{decimal(row.speed)}</span> },
{ id: 'column4', header: '관측', cell: ({ row: { original: row } }) => <>{dateTime(row.observed_at)}</> }]} /></div>
      {stats && !stats.rows.length ? <p className="text-sm text-text-secondary">최근 15분 이내의 유효 속도 관측이 없습니다.</p> : null}
    </SectionCard>);
}

function speedMetrics(stats: ReturnType<typeof useHighwayStatistics>["stats"]) {
  return [
        { label: "평균 속도", value: decimal(stats?.mean ?? null), unit: "km/h" },
        { label: "중앙 속도", value: decimal(stats?.median ?? null), unit: "km/h" },
        { label: "최저 구간 속도", value: decimal(stats?.minimum ?? null), unit: "km/h" },
        { label: "최고 구간 속도", value: decimal(stats?.maximum ?? null), unit: "km/h" },
        { label: "하위 10% 속도", value: decimal(stats?.p10 ?? null), unit: "km/h" },
        { label: "상위 10% 속도", value: decimal(stats?.p90 ?? null), unit: "km/h" },
        { label: "정지 관측 구간", value: stats?.rows.length ? stats.stopped : null, unit: "곳", caption: "속도 0 km/h 관측" },
        { label: "40 km/h 이하 구간", value: stats?.rows.length ? stats.slow : null, unit: "곳" },
        { label: "40 km/h 이하 비율", value: decimal(stats?.slowRatio ?? null), unit: "%" },
        { label: "40 초과~80 미만 비율", value: decimal(stats?.mediumRatio ?? null), unit: "%" },
        { label: "80 km/h 이상 비율", value: decimal(stats?.fastRatio ?? null), unit: "%" },
        { label: "속도 확인 구간", value: stats?.rows.length, unit: "곳", caption: stats ? `${stats.routes}개 노선` : undefined },
      ];
}
