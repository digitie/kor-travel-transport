"use client";
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
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "./ui/table";

const inlineLink = "rounded-control text-sm font-medium text-brand underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";
const decimal = (n: number | null) => n === null ? null : n.toLocaleString("ko-KR", { maximumFractionDigits: 1 });
export function HighwayStatistics() {
  const [state, setState] = useState<{ rows?: SpeedObservation[]; checked?: string; error?: boolean }>({});
  const [route, setRoute] = useState("");
  const [revision, setRevision] = useState(0);
  const [clock, setClock] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setClock(Date.now()), 60_000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    transportGet<{ items: SpeedObservation[]; generated_at: string }>("transport/highways/traffic?days=1&limit=1000", controller.signal)
      .then((data) => { if (!controller.signal.aborted) setState({ rows: data.items, checked: data.generated_at }); })
      .catch(() => { if (!controller.signal.aborted) setState({ error: true }); });
    return () => controller.abort();
  }, [revision]);
  const names = new Map((state.rows ?? []).filter((row) => row.route_no).map((row) => [row.route_no!, highwayRouteLabel(row.route_no, row.route_name)]));
  const stats = state.rows ? currentSpeeds(state.rows.filter((row) => !route || row.route_no === route), clock) : null;
  return <div className="flex flex-col gap-6">
    <FilterBar>
      <FilterField label="고속도로"><NativeSelect value={route} onChange={(event) => setRoute(event.target.value)}><NativeSelectOption value="">조회된 모든 노선</NativeSelectOption>{[...names].map(([id, name]) => <NativeSelectOption key={id} value={id}>{name}</NativeSelectOption>)}</NativeSelect></FilterField>
      <FilterActions>
        <Button type="button" variant="outline" onClick={() => { setState({}); setRevision((v) => v + 1); }}>새로고침</Button>
        <Link className={inlineLink} href="/highways">지도에서 확인</Link>
      </FilterActions>
    </FilterBar>
    {state.error ? <Alert variant="destructive"><AlertDescription>고속도로 통계를 불러오지 못했습니다.</AlertDescription></Alert> : !state.rows ? <p role="status" className="text-sm text-text-secondary">최근 구간 관측을 확인하는 중입니다…</p> : null}
    <SectionCard title="최근 15분 구간 속도" description="구간별 마지막 관측을 같은 비중으로 비교합니다. 실제 경로 소요시간이나 교통량 가중 평균이 아닙니다.">
      <StatStrip ariaLabel="고속도로 운전 지표" items={[
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
      ]} />
      <p className="text-sm text-text-secondary">최대 1,000개 저장 행에서 구간별 최신 관측을 추립니다. {stats ? `15분 초과·결측 등 ${stats.excluded}구간 제외 · ` : ""}조회 {dateTime(state.checked)}. 속도 구간은 이 화면의 비교 기준입니다.</p>
    </SectionCard>
    <SectionCard title="속도가 낮은 구간부터" description="출발 전 관심 노선의 정체 위치와 방향을 확인하세요.">
      <div className="overflow-x-auto"><Table><TableHeader><TableRow><TableHead>노선</TableHead><TableHead>구간</TableHead><TableHead>방향</TableHead><TableHead>속도(km/h)</TableHead><TableHead>관측</TableHead></TableRow></TableHeader><TableBody>{[...(stats?.rows ?? [])].sort((a, b) => a.speed! - b.speed!).slice(0, 100).map((row) => <TableRow key={row.identity_key}><TableCell>{highwayRouteLabel(row.route_no, row.route_name)}</TableCell><TableCell>{(row as SpeedObservation & { conzone_name?: string }).conzone_name ?? "구간명 미제공"}</TableCell><TableCell>{(row as SpeedObservation & { direction?: string }).direction ?? "—"}</TableCell><TableCell className="tabular-nums">{decimal(row.speed)}</TableCell><TableCell>{dateTime(row.observed_at)}</TableCell></TableRow>)}</TableBody></Table></div>
      {stats && !stats.rows.length ? <p className="text-sm text-text-secondary">최근 15분 이내의 유효 속도 관측이 없습니다.</p> : null}
    </SectionCard>
  </div>;
}
