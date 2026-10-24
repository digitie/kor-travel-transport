"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { transportGet, dateTime } from "@/lib/journey";
import { currentSpeeds, type SpeedObservation } from "@/lib/driver-statistics";
import { highwayRouteLabel } from "@/lib/transport-presentation";
import { SectionCard } from "./section-card";
import { StatStrip } from "./stat-strip";

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
  return <div className="space-y-6">
    <div className="journey-toolbar"><label>고속도로<select value={route} onChange={(event) => setRoute(event.target.value)}><option value="">조회된 모든 노선</option>{[...names].map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label><button type="button" className="secondary" onClick={() => { setState({}); setRevision((v) => v + 1); }}>새로고침</button><Link className="inline-link" href="/highways">지도에서 확인</Link></div>
    {state.error ? <p role="alert">고속도로 통계를 불러오지 못했습니다.</p> : !state.rows ? <p role="status">최근 구간 관측을 확인하는 중입니다…</p> : null}
    <SectionCard title="최근 15분 구간 속도" description="구간별 마지막 관측을 같은 비중으로 비교합니다. 실제 경로 소요시간이나 교통량 가중 평균이 아닙니다.">
      <StatStrip ariaLabel="고속도로 운전 지표" className="driver-stats" items={[
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
      <p className="quiet">최대 1,000개 저장 행에서 구간별 최신 관측을 추립니다. {stats ? `15분 초과·결측 등 ${stats.excluded}구간 제외 · ` : ""}조회 {dateTime(state.checked)}. 속도 구간은 이 화면의 비교 기준입니다.</p>
    </SectionCard>
    <SectionCard title="속도가 낮은 구간부터" description="출발 전 관심 노선의 정체 위치와 방향을 확인하세요.">
      <div className="overflow-x-auto"><table className="operations-table"><thead><tr><th>노선</th><th>구간</th><th>방향</th><th>속도(km/h)</th><th>관측</th></tr></thead><tbody>{[...(stats?.rows ?? [])].sort((a, b) => a.speed! - b.speed!).slice(0, 100).map((row) => <tr key={row.identity_key}><td>{highwayRouteLabel(row.route_no, row.route_name)}</td><td>{(row as SpeedObservation & { conzone_name?: string }).conzone_name ?? "구간명 미제공"}</td><td>{(row as SpeedObservation & { direction?: string }).direction ?? "—"}</td><td>{decimal(row.speed)}</td><td>{dateTime(row.observed_at)}</td></tr>)}</tbody></table></div>
      {stats && !stats.rows.length ? <p>최근 15분 이내의 유효 속도 관측이 없습니다.</p> : null}
    </SectionCard>
  </div>;
}
