"use client";

import { useEffect, useState } from "react";
import { dateTime, transportGet } from "@/lib/journey";
import { fuelProductLabel } from "@/lib/transport-presentation";

export type FuelMetrics = {
  station_count: number; average_price: number; minimum_price: number; maximum_price: number;
  price_spread: number; standard_deviation: number; saving_50l: number; cheapest_station_count: number;
  cheapest_station: { name: string; address: string | null } | null; generated_at: string;
};
export type FuelViewportStatistics = FuelMetrics & { product_code: string };
type Group = FuelMetrics & { scope_key: string; label: string };
type History = { day: string; average_price: number; station_count: number };
type Statistics = { generated_at: string | null; update_pending: boolean; history_scope_key: string | null; items: Group[]; history: History[] };
const money = (value: number) => value.toLocaleString("ko-KR", { maximumFractionDigits: 2 });
const scopes = [["nationwide", "전국"], ["sido", "시도"], ["sigungu", "시군구"], ["highways", "고속도로 전체"], ["highway", "고속도로별"], ["highway_direction", "고속도로·방향별"]];

export function FuelStatisticsCard({ metrics, title }: { metrics: FuelMetrics; title: string }) {
  return <article className="fuel-stat-card" aria-label={title}>
    <header><h3>{title}</h3><span>{metrics.station_count.toLocaleString()}개 주유소</span></header>
    <dl className="fuel-stat-values">
      <div><dt>평균</dt><dd>{money(metrics.average_price)}<small>원/L</small></dd></div>
      <div><dt>최저</dt><dd>{money(metrics.minimum_price)}<small>원/L</small></dd></div>
      <div><dt>최고−최저</dt><dd>{money(metrics.price_spread)}<small>원/L</small></dd></div>
      <div><dt>가격 표준편차</dt><dd>{money(metrics.standard_deviation)}<small>원/L</small></dd></div>
      <div><dt>50L 평균 대비 절감</dt><dd>{money(metrics.saving_50l)}<small>원</small></dd></div>
    </dl>
    <p>최저가 · <strong>{metrics.cheapest_station?.name ?? "정보 없음"}</strong>{metrics.cheapest_station_count > 1 ? ` 외 ${metrics.cheapest_station_count - 1}곳` : ""}</p>
    {metrics.cheapest_station?.address ? <p className="text-muted-foreground">{metrics.cheapest_station.address}</p> : null}
    <small>수집 기준 {dateTime(metrics.generated_at)}</small>
  </article>;
}

export function FuelViewportSummary({ items, pending, failed = false }: { items: FuelViewportStatistics[]; pending: boolean; failed?: boolean }) {
  return <section className="fuel-stat-section" aria-label="현재 지도 범위 유가 통계" aria-busy={pending}>
    <h2>현재 지도 범위</h2>
    {pending ? <p role="status">통계 조회 중…</p> : failed ? <p role="alert">통계를 불러오지 못했습니다.</p> : items.length ? <div className="fuel-stat-grid">{items.map((item) => <FuelStatisticsCard key={item.product_code} title={fuelProductLabel(item.product_code)} metrics={item} />)}</div> : <p>통계 없음 · 수집 완료 후 반영됩니다.</p>}
  </section>;
}

function Trend({ rows }: { rows: History[] }) {
  if (!rows.length) return <p>추이 데이터가 없습니다.</p>;
  const values = rows.map((row) => row.average_price);
  const low = Math.min(...values) - 1, range = Math.max(...values) + 1 - low;
  const x = (i: number) => rows.length === 1 ? 300 : 40 + i * 520 / (rows.length - 1);
  const y = (value: number) => 125 - (value - low) / range * 100;
  return <><svg className="fuel-stat-trend" viewBox="0 0 600 170" role="img" aria-label="최근 7일 평균 유가 추이. 상세 수치는 다음 표에 표시됩니다.">
    <polyline fill="none" stroke="currentColor" strokeWidth="2" points={rows.map((row, i) => `${x(i)},${y(row.average_price)}`).join(" ")} />
    {rows.map((row, i) => <g key={row.day}><circle cx={x(i)} cy={y(row.average_price)} r="4" /><text x={x(i)} y={y(row.average_price) - 10} textAnchor="middle" fontSize="12">{money(row.average_price)}</text><text x={x(i)} y="155" textAnchor="middle" fontSize="12">{row.day.slice(5)}</text></g>)}
  </svg><div className="fuel-stat-table"><table><caption className="sr-only">최근 7일 평균 유가</caption><thead><tr><th>날짜(KST)</th><th>평균(원/L)</th><th>주유소</th></tr></thead><tbody>{rows.map((row) => <tr key={row.day}><td>{row.day}</td><td>{money(row.average_price)}</td><td>{row.station_count.toLocaleString()}</td></tr>)}</tbody></table></div></>;
}

export function FuelStatisticsPage() {
  const [scope, setScope] = useState("nationwide");
  const [product, setProduct] = useState("B027");
  const [scopeKey, setScopeKey] = useState("");
  const [reload, setReload] = useState(0);
  const [data, setData] = useState<Statistics | null>(null);
  const [error, setError] = useState(false);
  const [pending, setPending] = useState(true);
  useEffect(() => {
    const controller = new AbortController();
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setPending(true); setError(false);
    const search = new URLSearchParams({ scope, product_code: product });
    if (scopeKey) search.set("scope_key", scopeKey);
    transportGet<Statistics>(`transport/fuel/statistics?${search}`, controller.signal).then((value) => {
      if (!controller.signal.aborted) { setData(value); setPending(false); }
    }).catch(() => { if (!controller.signal.aborted) { setError(true); setPending(false); } });
    return () => controller.abort();
  }, [scope, product, scopeKey, reload]);
  const selected = data?.items.find((row) => row.scope_key === data.history_scope_key);
  return <section className="fuel-stat-section" aria-label="유가 통계" aria-busy={pending}>
    <div className="fuel-stat-filters">
      <label>범위<select value={scope} onChange={(event) => { setScope(event.target.value); setScopeKey(""); }} >{scopes.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label>유종<select value={product} onChange={(event) => { setProduct(event.target.value); setScopeKey(""); }}>{["B027", "D047", "K015", "B034", "C004"].map((code) => <option key={code} value={code}>{fuelProductLabel(code)}</option>)}</select></label>
      <button type="button" onClick={() => setReload((value) => value + 1)}>새로고침</button>
    </div>
    {pending ? <p role="status">통계 조회 중…</p> : error ? <p role="alert">통계를 불러오지 못했습니다. 새로고침해 주세요.</p> : data ? <>
      <p>{data.generated_at ? `수집 기준 ${dateTime(data.generated_at)}` : "첫 수집 완료 후 통계가 생성됩니다."}{data.update_pending ? " · 최신 수집 통계 반영 대기" : ""}</p>
      {data.items.length ? <>
        <label className="fuel-stat-category">추이 범주<select value={selected?.scope_key ?? ""} onChange={(event) => setScopeKey(event.target.value)}>{data.items.map((row) => <option key={row.scope_key} value={row.scope_key}>{row.label}</option>)}</select></label>
        {selected ? <FuelStatisticsCard title={`${selected.label} · ${fuelProductLabel(product)}`} metrics={selected} /> : null}
        <h2>최근 7일 평균 유가 · {selected?.label}</h2><Trend rows={data.history} />
        <p className="text-muted-foreground">KST 일별 마지막 정상 수집 기준 · 수집 기록이 있는 날짜만 표시</p>
        <div className="fuel-stat-table"><table><caption>전체 범주 비교 · {fuelProductLabel(product)} (원/L)</caption><thead><tr><th>범주</th><th>주유소</th><th>평균</th><th>최저</th><th>최저가 주유소</th><th>가격 차이</th><th>50L 절감(원)</th></tr></thead><tbody>{data.items.map((row) => <tr key={row.scope_key}><th><button type="button" onClick={() => setScopeKey(row.scope_key)}>{row.label}</button></th><td>{row.station_count}</td><td>{money(row.average_price)}</td><td>{money(row.minimum_price)}</td><td>{row.cheapest_station?.name}{row.cheapest_station_count > 1 ? ` 외 ${row.cheapest_station_count - 1}곳` : ""}</td><td>{money(row.price_spread)}</td><td>{money(row.saving_50l)}</td></tr>)}</tbody></table></div>
      </> : <p>선택한 유종의 통계가 없습니다.</p>}
      <p className="text-muted-foreground">전국·지역은 오피넷, 고속도로는 한국도로공사 기준입니다. 유효 가격만 주유소별 동일 비중으로 집계합니다. 절감액은 범주 평균과 최저가의 차이입니다.</p>
    </> : null}
  </section>;
}
