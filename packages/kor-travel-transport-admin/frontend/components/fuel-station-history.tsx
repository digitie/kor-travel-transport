"use client";

import { useEffect, useId, useMemo, useState, type CSSProperties } from "react";
import { money, TransportError, type Place } from "@/lib/journey";
import { fuelProductLabel } from "@/lib/transport-presentation";
import { FUEL_HISTORY_PRODUCT_ORDER, fuelHistorySeries, isFuelHistoryGap, loadFuelStationHistory, type FuelStationHistory } from "@/lib/fuel-station-history";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { InfoButton } from "./info-button";

const colors = ["var(--brand)", "var(--success)", "var(--warning)", "var(--danger)", "var(--text-secondary)"];
const seriesColor = (product: string, fallback: number) => colors[(FUEL_HISTORY_PRODUCT_ORDER.includes(product) ? FUEL_HISTORY_PRODUCT_ORDER.indexOf(product) : fallback) % colors.length];
// SSR과 브라우저의 Intl 공백·오전/오후 표기 차이로 가격 차트가 재수화 실패하지 않게 고정한다.
const koreanTime = (instant: number) => new Date(instant + 9 * 3600_000).toISOString();
const dateLabel = (instant: number) => koreanTime(instant).slice(5, 10).replace("-", ".");
const historyTime = (value: string) => Number.isFinite(Date.parse(value)) ? koreanTime(Date.parse(value)).slice(0, 16).replace("T", " ").replaceAll("-", ".") : "시각 미확인";

export function FuelStationHistoryChart({ data }: { data: FuelStationHistory }) {
  const hint = useId();
  const series = useMemo(() => fuelHistorySeries(data), [data]);
  const points = useMemo(() => series.flatMap((row) => row.points).sort((a, b) => a.instant - b.instant || a.product_code.localeCompare(b.product_code)), [series]);
  const [active, setActive] = useState<number | null>(null);
  if (!points.length) return <p className="quiet" role="status">최근 7일에 저장된 유효한 가격 관측이 없습니다.</p>;
  const start = Date.parse(data.window.from_at), end = Date.parse(data.window.to_at);
  const low = Math.floor(Math.min(...points.map((point) => point.price)) / 10) * 10 - 5;
  const high = Math.ceil(Math.max(...points.map((point) => point.price)) / 10) * 10 + 5;
  const x = (instant: number) => 44 + (instant - start) / (end - start) * 278;
  const y = (price: number) => 118 - (price - low) / (high - low) * 92;
  const current = active === null ? null : points[Math.min(active, points.length - 1)];
  // 우측 실제 최신값 라벨끼리 겹치지 않도록 라벨만 배치한다. 관측점/가격축은 옮기지 않는다.
  const labels = series.map((row, index) => ({ index, point: row.points.at(-1)!, top: y(row.points.at(-1)!.price) })).sort((a, b) => a.top - b.top);
  for (let index = 1; index < labels.length; index++) labels[index].top = Math.max(labels[index].top, labels[index - 1].top + 14);
  const overflow = Math.max(0, labels.at(-1)!.top - 130);
  for (const label of labels) label.top -= overflow;
  function selectNearest(clientX: number, clientY: number, bounds: DOMRect) {
    const px = (clientX - bounds.left) / bounds.width * 400, py = (clientY - bounds.top) / bounds.height * 154;
    const distance = (point: typeof points[number]) => (x(point.instant) - px) ** 2 + (y(point.price) - py) ** 2;
    setActive(points.reduce((best, point, index) => distance(point) < distance(points[best]) ? index : best, 0));
  }
  return <>
    <svg className="fuel-station-trend" viewBox="0 0 400 154" role="group" aria-label="주유소 최근 7일 유종별 가격 추이" aria-describedby={hint} tabIndex={0}
      onKeyDown={(event) => {
        if (!["ArrowLeft", "ArrowRight", "Home", "End", "Escape"].includes(event.key)) return;
        event.preventDefault();
        if (event.key === "Escape") setActive(null);
        else if (event.key === "Home") setActive(0);
        else if (event.key === "End") setActive(points.length - 1);
        else setActive((previous) => Math.max(0, Math.min(points.length - 1, (previous ?? points.length - 1) + (event.key === "ArrowLeft" ? -1 : 1))));
      }} onPointerDown={(event) => selectNearest(event.clientX, event.clientY, event.currentTarget.getBoundingClientRect())}>
      <text x="0" y="12" className="fuel-trend-axis">원/L</text>
      {[low, (low + high) / 2, high].map((price) => <g key={price}><line x1="44" x2="322" y1={y(price)} y2={y(price)} className="fuel-trend-grid" /><text x="39" y={y(price) + 3} textAnchor="end" className="fuel-trend-axis">{price.toLocaleString("ko-KR", { maximumFractionDigits: 0 })}</text></g>)}
      {[0, 2, 4, 6, 7].map((day) => <text key={day} x={x(start + (end - start) * day / 7)} y="148" textAnchor="middle" className="fuel-trend-axis">{dateLabel(start + (end - start) * day / 7)}</text>)}
      {series.map((row, index) => <g key={row.product} style={{ color: seriesColor(row.product, index) }}>
        <path data-product={row.product} d={row.points.map((point, position) => `${position === 0 || isFuelHistoryGap(row.points[position - 1], point) ? "M" : "L"}${x(point.instant)},${y(point.price)}`).join(" ")} fill="none" stroke="currentColor" strokeWidth="2" strokeDasharray={index % 2 ? "5 2" : undefined} />
        {row.points.map((point) => <circle key={point.instant} cx={x(point.instant)} cy={y(point.price)} r="2.7" fill="currentColor"><title>{`${fuelProductLabel(row.product)} · ${historyTime(point.observed_at)} · ${money(point.price, "원/L")}`}</title></circle>)}
      </g>)}
      {labels.map(({ index, point, top }) => <g key={point.product_code} style={{ color: seriesColor(point.product_code, index) }}><line x1={x(point.instant) + 4} x2="328" y1={y(point.price)} y2={top - 3} stroke="currentColor" strokeDasharray="2 2" /><text className="fuel-trend-latest" data-latest-product={point.product_code} x="332" y={top} fill="currentColor">{point.price.toLocaleString("ko-KR")}</text></g>)}
      {current ? <circle cx={x(current.instant)} cy={y(current.price)} r="5" className="fuel-trend-active" /> : null}
    </svg>
    <span className="sr-only" id={hint}>좌우 방향키로 관측을 이동하고 Home·End로 처음·마지막 관측을 확인합니다. 터치로 날짜를 선택하거나 아래 관측값 표를 펼칠 수 있습니다.</span>
    <div className="fuel-trend-legend">{series.map((row, index) => <span key={row.product} style={{ "--series-color": seriesColor(row.product, index) } as CSSProperties}><i aria-hidden="true" /><span>{fuelProductLabel(row.product)} <strong>{money(row.points.at(-1)!.price, "원/L")}</strong><small>{historyTime(row.points.at(-1)!.observed_at)}</small></span></span>)}</div>
    {current ? <p className="fuel-trend-tooltip" role="status">{fuelProductLabel(current.product_code)} · {historyTime(current.observed_at)} · <strong>{money(current.price, "원/L")}</strong></p> : null}
    <details className="fuel-trend-table"><summary>관측값 표 · {points.length.toLocaleString("ko-KR")}건</summary><Table aria-label="주유소 7일 가격 관측값"><TableHeader><TableRow><TableHead>관측 시각 (한국)</TableHead><TableHead>유종</TableHead><TableHead>원/L</TableHead></TableRow></TableHeader><TableBody>{[...points].reverse().map((point) => <TableRow key={`${point.product_code}:${point.instant}`}><TableCell><time dateTime={point.observed_at}>{historyTime(point.observed_at)}</time></TableCell><TableCell>{fuelProductLabel(point.product_code)}</TableCell><TableCell>{point.price.toLocaleString("ko-KR")}</TableCell></TableRow>)}</TableBody></Table></details>
  </>;
}

export function FuelStationPriceHistory({ place }: { place: Pick<Place, "id" | "source"> }) {
  const [reload, setReload] = useState(0);
  const key = `${place.source}/${place.id}/${reload}`;
  const [state, setState] = useState<{ key: string; data?: FuelStationHistory; error?: string }>();
  const supported = place.id > 0 && place.source === "opinet_browser";
  useEffect(() => {
    if (!supported) return;
    const controller = new AbortController();
    loadFuelStationHistory(place.id, place.source, AbortSignal.any([controller.signal, AbortSignal.timeout(30_000)]))
      .then((data) => { if (!controller.signal.aborted) setState({ key, data }); })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setState({ key, error: error instanceof TransportError && error.status === 503 ? "성공한 가격 수집 이력이 없어 추이를 조회할 수 없습니다." : error instanceof Error && /[가-힣]/.test(error.message) ? error.message : "가격 이력을 불러오지 못했습니다. 다시 조회해 주세요." });
      });
    return () => controller.abort();
  }, [key, place.id, place.source, supported]);
  const current = state?.key === key ? state : undefined;
  return <section className="fuel-station-history" aria-label="최근 7일 주유소 가격" aria-busy={supported && !current}>
    <div className="fuel-history-heading"><h3>최근 7일 유가</h3><InfoButton label="주유소 가격 추이">최근 168시간의 저장 관측만 표시합니다. 한국 날짜 기준으로 관측이 전혀 없는 날은 선을 끊고 보간하지 않습니다. 오른쪽 숫자는 유종별 마지막 실제 관측 가격입니다. 현재 가격 카드의 기준 시각과 다를 수 있습니다.{current?.data ? <><p>조회 범위 {historyTime(current.data.window.from_at)} → {historyTime(current.data.window.to_at)} · 한국 시각</p><p>출처 최근 수집 성공 {current.data.source_last_success_at ? historyTime(current.data.source_last_success_at) : "확인되지 않음"}</p></> : null}</InfoButton></div>
    {!supported ? <p className="quiet">이 출처는 개별 주유소의 저장 가격 추이를 제공하지 않습니다.</p> : !current ? <p className="quiet" role="status">가격 이력 불러오는 중…</p> : current.error ? <div role="alert"><p>{current.error}</p><Button type="button" variant="outline" size="sm" onClick={() => setReload((value) => value + 1)}>다시 조회</Button></div> : current.data ? <FuelStationHistoryChart key={key} data={current.data} /> : null}
  </section>;
}
