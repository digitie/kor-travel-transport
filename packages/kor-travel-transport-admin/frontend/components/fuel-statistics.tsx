"use client";

import Link from "next/link";
import { InfoButton } from "./info-button";
import { useEffect, useId, useState } from "react";
import { dateTime, transportGet } from "@/lib/journey";
import { fuelProductLabel } from "@/lib/transport-presentation";
import { fuelDrivingCosts } from "@/lib/driver-statistics";
import { StatStrip } from "./stat-strip";
import { SectionCard } from "./section-card";

export type FuelMetrics = {
  update_pending?: boolean; station_count: number; average_price: number; minimum_price: number; maximum_price: number;
  price_spread: number; standard_deviation: number; saving_50l: number; cheapest_station_count: number;
  cheapest_station: { name: string; address: string | null; longitude?: number | null; latitude?: number | null } | null; generated_at: string;
};
export type FuelViewportStatistics = FuelMetrics & { product_code: string };
type Group = FuelMetrics & { scope_key: string; label: string };
type History = { day: string; average_price: number; station_count: number };
type Statistics = { generated_at: string | null; update_pending: boolean; history_scope_key: string | null; items: Group[]; history: History[] };
const money = (value: number) => value.toLocaleString("ko-KR", { maximumFractionDigits: 2 });
const scopes = [["nationwide", "전국"], ["sido", "시도"], ["sigungu", "시군구"], ["highways", "고속도로 전체"], ["highway", "고속도로별"], ["highway_direction", "고속도로·방향별"]];

export function FuelDriverStatistics({ metrics }: { metrics: FuelMetrics }) {
  const [liters, setLiters] = useState("50");
  const [efficiency, setEfficiency] = useState("10");
  const costs = fuelDrivingCosts(metrics, Number(liters), Number(efficiency));
  const amount = (n: number | null) => n === null ? null : money(n);
  return <SectionCard title="차량 운영비 비교" description="현재 선택한 범주의 유효 가격과 입력한 주유량·연비로 계산합니다. 주행 조건·할인·주유소까지의 이동 비용은 포함하지 않습니다.">
    <div className="journey-toolbar"><label>주유량(L)<input aria-label="주유량(L)" type="number" min="1" max="1000" value={liters} onChange={(event) => setLiters(event.target.value)} /></label><label>차량 연비(km/L)<input aria-label="차량 연비(km/L)" type="number" min="0.1" max="100" step="0.1" value={efficiency} onChange={(event) => setEfficiency(event.target.value)} /></label></div>
    <StatStrip ariaLabel="유가 운전 지표" className="driver-stats" items={[
      { label: "평균 가격", value: money(metrics.average_price), unit: "원/L" },
      { label: "최저 가격", value: money(metrics.minimum_price), unit: "원/L" },
      { label: "최고 가격", value: money(metrics.maximum_price), unit: "원/L" },
      { label: "최고·최저 가격 차이", value: money(metrics.price_spread), unit: "원/L" },
      { label: "가격 표준편차", value: money(metrics.standard_deviation), unit: "원/L" },
      { label: "평균가 주유 비용", value: amount(costs.averageFill), unit: "원", caption: `${liters || "—"}L 기준` },
      { label: "최저가 주유 비용", value: amount(costs.minimumFill), unit: "원", caption: `${liters || "—"}L 기준` },
      { label: "최고가 주유 비용", value: amount(costs.maximumFill), unit: "원", caption: `${liters || "—"}L 기준` },
      { label: "평균 대비 절약액", value: amount(costs.saving), unit: "원", caption: "최저가 주유 시" },
      { label: "평균 대비 절약률", value: amount(costs.savingPercent), unit: "%" },
      { label: "100km 평균 연료비", value: amount(costs.costPer100Km), unit: "원", caption: `연비 ${efficiency || "—"}km/L 가정` },
      { label: "100km 최저 연료비", value: amount(costs.minimumCostPer100Km), unit: "원", caption: "동일 연비·최저가 가정" },
    ]} />

  </SectionCard>;
}

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
    {metrics.cheapest_station?.address ? <p className="text-muted-foreground">{metrics.cheapest_station.longitude != null && metrics.cheapest_station.latitude != null ? <Link className="inline-link" href={`/fuel?longitude=${metrics.cheapest_station.longitude}&latitude=${metrics.cheapest_station.latitude}`}>{metrics.cheapest_station.address} · 지도</Link> : metrics.cheapest_station.address}</p> : null}
    <small>수집 기준 {dateTime(metrics.generated_at)}</small>
    {metrics.update_pending ? <p role="status">최신 수집 통계 반영 대기</p> : null}
  </article>;
}

export function FuelPriceStatus({ stale, lastRefreshedAt }: { stale: boolean; lastRefreshedAt?: string | null }) {
  return stale ? <p className="error" role="status">갱신 지연 · 가격 갱신 {dateTime(lastRefreshedAt)}</p>
    : lastRefreshedAt ? <p className="fuel-viewport-context">가격 갱신 {dateTime(lastRefreshedAt)}</p> : null;
}

export function FuelViewportSummary({ items, pending, failed = false, pricesStale = false, pricesLastRefreshedAt }: { items: FuelViewportStatistics[]; pending: boolean; failed?: boolean; pricesStale?: boolean; pricesLastRefreshedAt?: string | null }) {
  const productId = useId();
  const [product, setProduct] = useState("B027");
  const selected = items.find((item) => item.product_code === product) ?? items[0];
  return <section className="fuel-viewport-summary" aria-label="현재 지도 범위 유가 통계" aria-busy={pending}>
    <header><h2>현재 지도 범위</h2>
      {!pending && !failed && selected ? items.length > 1 ? <><label className="sr-only" htmlFor={productId}>지도 통계 유종</label><select id={productId} value={selected.product_code} onChange={(event) => setProduct(event.target.value)}>{items.map((item) => <option key={item.product_code} value={item.product_code}>{fuelProductLabel(item.product_code)}</option>)}</select></> : <span>{fuelProductLabel(selected.product_code)}</span> : null}
      <InfoButton label="지도 범위 유가 통계">
        {pending ? <p role="status">통계 조회 중…</p> : failed ? <p role="alert">통계를 불러오지 못했습니다.</p> : selected ? <>
          <p>현재 지도 범위와 검색·출처·유종 조건에 맞는 전체 주유소의 유효 가격을 집계합니다. 묶음 마커 개수와는 다릅니다.</p>
          <p>통계 기준은 공개된 통계 세대의 수집 시각이고, 가격 갱신은 가격 읽기 모델의 마지막 성공 갱신 시각입니다. 개별 가격의 관측 시각은 주유소 상세에서 확인할 수 있습니다.</p>
          {pricesStale ? <p>가격 갱신이 지연되어 현재 유종·가격·판매 여부가 표시된 자료와 다를 수 있습니다.</p> : null}
          <FuelStatisticsCard title={fuelProductLabel(selected.product_code)} metrics={selected} />
          <Link className="inline-link" href="/fuel/statistics">지역·기간별 유가 통계</Link>
        </> : <p>통계 없음 · 수집 완료 후 반영됩니다.</p>}
      </InfoButton>
    </header>
    {pending ? <p role="status">통계 조회 중…</p> : failed ? <p role="alert">통계를 불러오지 못했습니다.</p> : selected ? <>
      <dl><div><dt>평균</dt><dd>{money(selected.average_price)}<small>원/L</small></dd></div><div><dt>최저</dt><dd>{money(selected.minimum_price)}<small>원/L</small></dd></div></dl>
      <FuelPriceStatus stale={pricesStale} lastRefreshedAt={pricesLastRefreshedAt} />
      <p className="fuel-viewport-context"><span>{selected.station_count.toLocaleString()}개 주유소</span><span>통계 기준 {dateTime(selected.generated_at)}</span></p>
      {selected.update_pending ? <p role="status">최신 수집 통계 반영 대기</p> : null}
    </> : <p>통계 없음 · 수집 완료 후 반영됩니다.</p>}
  </section>;
}

export function FuelPriceTrend({ rows }: { rows: History[] }) {
  if (!rows.length) return <p>추이 데이터가 없습니다.</p>;
  const values = rows.map((row) => row.average_price);
  const low = Math.min(...values) - 1, range = Math.max(...values) + 1 - low;
  const dayMs = 86_400_000;
  const start = Date.parse(rows[rows.length - 1].day) - 6 * dayMs;
  const x = (day: string) => 40 + (Date.parse(day) - start) / dayMs * 520 / 6;
  const y = (value: number) => 125 - (value - low) / range * 100;
  return <><svg className="fuel-stat-trend" viewBox="0 0 600 170" role="img" aria-label="최근 7일 평균 유가 추이. 상세 수치는 다음 표에 표시됩니다.">
    {rows.map((row, i) => i > 0 && Date.parse(row.day) - Date.parse(rows[i - 1].day) === dayMs ? <line key={row.day} stroke="currentColor" strokeWidth="2" x1={x(rows[i - 1].day)} y1={y(rows[i - 1].average_price)} x2={x(row.day)} y2={y(row.average_price)} /> : null)}
    {rows.map((row) => <g key={row.day}><circle data-day={row.day} cx={x(row.day)} cy={y(row.average_price)} r="4" /><text x={x(row.day)} y={y(row.average_price) - 10} textAnchor="middle" fontSize="12">{money(row.average_price)}</text><text x={x(row.day)} y="155" textAnchor="middle" fontSize="12">{row.day.slice(5)}</text></g>)}
  </svg><div className="fuel-stat-table"><table><caption className="sr-only">최근 7일 평균 유가</caption><thead><tr><th>날짜(KST)</th><th>평균(원/L)</th><th>주유소</th></tr></thead><tbody>{rows.map((row) => <tr key={row.day}><td>{row.day}</td><td>{money(row.average_price)}</td><td>{row.station_count.toLocaleString()}</td></tr>)}</tbody></table></div></>;
}

export function FuelStatisticsPage() {
  const [scope, setScope] = useState("nationwide");
  const [product, setProduct] = useState("B027");
  const [scopeKey, setScopeKey] = useState("");
  const [reload, setReload] = useState(0);
  const [dataContext, setDataContext] = useState("");
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
      if (!controller.signal.aborted) { setData(value); setDataContext(`${scope}/${product}`); setPending(false); }
    }).catch(() => { if (!controller.signal.aborted) { setError(true); setPending(false); } });
    return () => controller.abort();
  }, [scope, product, scopeKey, reload]);
  const shownData = dataContext === `${scope}/${product}` ? data : null;
  const selected = shownData?.items.find((row) => row.scope_key === shownData.history_scope_key);
  const categoryKey = shownData?.items.some((row) => row.scope_key === scopeKey) ? scopeKey : selected?.scope_key ?? "";
  return <section className="fuel-stat-section" aria-label="유가 통계" aria-busy={pending}>
    <div className="fuel-stat-filters">
      <label>범위<select aria-label="범위" value={scope} onChange={(event) => { setScope(event.target.value); setScopeKey(""); }} >{scopes.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label>유종<select aria-label="유종" value={product} onChange={(event) => { setProduct(event.target.value); setScopeKey(""); }}>{["B027", "D047", "K015", "B034", "C004"].map((code) => <option key={code} value={code}>{fuelProductLabel(code)}</option>)}</select></label>
      <button type="button" onClick={() => setReload((value) => value + 1)}>새로고침</button>
    </div>
    {shownData?.items.length ? <label className="fuel-stat-category">추이 범주<select aria-label="추이 범주" value={categoryKey} onChange={(event) => setScopeKey(event.target.value)}>{shownData.items.map((row) => <option key={row.scope_key} value={row.scope_key}>{row.label}</option>)}</select></label> : null}
    {pending ? <p role="status">통계 조회 중…</p> : error ? <p role="alert">통계를 불러오지 못했습니다. 새로고침해 주세요.</p> : shownData ? <>
      <p>{shownData.generated_at ? `수집 기준 ${dateTime(shownData.generated_at)}` : "첫 수집 완료 후 통계가 생성됩니다."}{shownData.update_pending ? " · 최신 수집 통계 반영 대기" : ""}</p>
      {shownData.items.length ? <>
        {selected ? <FuelStatisticsCard title={`${selected.label} · ${fuelProductLabel(product)}`} metrics={selected} /> : null}
        <div className="section-title-row"><h2>최근 7일 평균 유가 · {selected?.label}</h2><InfoButton label="유가 집계 기준">KST 일별 마지막 정상 수집 기준이며 수집 기록이 있는 날짜만 표시합니다. 전국·지역은 오피넷, 고속도로는 한국도로공사 기준입니다. 유효 가격을 주유소별 동일 비중으로 집계합니다. 절감액은 범주 평균과 최저가의 차이입니다.</InfoButton></div><FuelPriceTrend rows={shownData.history} />

      </> : <p>선택한 유종의 통계가 없습니다.</p>}

    </> : null}
    {shownData?.items.length ? <div className="fuel-stat-table"><table><caption>전체 범주 비교 · {fuelProductLabel(product)} (원/L)</caption><thead><tr><th>범주</th><th>주유소</th><th>평균</th><th>최저</th><th>최저가 주유소</th><th>가격 차이</th><th>50L 절감(원)</th></tr></thead><tbody>{shownData.items.map((row) => <tr key={row.scope_key}><th><button type="button" onClick={() => setScopeKey(row.scope_key)}>{row.label}</button></th><td>{row.station_count}</td><td>{money(row.average_price)}</td><td>{money(row.minimum_price)}</td><td>{row.cheapest_station?.name}{row.cheapest_station_count > 1 ? ` 외 ${row.cheapest_station_count - 1}곳` : ""}</td><td>{money(row.price_spread)}</td><td>{money(row.saving_50l)}</td></tr>)}</tbody></table></div> : null}
    {!pending && !error && selected ? <details className="fuel-driving-details"><summary>차량 운영비 비교</summary><FuelDriverStatistics metrics={selected} /></details> : null}
  </section>;
}
