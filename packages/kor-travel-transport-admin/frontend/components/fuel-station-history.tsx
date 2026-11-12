"use client";
import { VirtualTable } from "@kor-travel/ui/virtual-table";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { TransportError, type Place } from "@/lib/journey";
import { fuelProductLabel } from "@/lib/transport-presentation";
import { fuelHistorySeries, loadFuelStationHistory, type FuelStationHistory } from "@/lib/fuel-station-history";
import { fuelChartTime } from "@/lib/fuel-chart-model";
import FuelPriceChart from "./fuel-price-chart-loader";
import { Button } from "@/components/ui/button";
import { InfoButton } from "./info-button";
const historyTime = (value: string) => fuelChartTime(value);

export function FuelStationHistoryChart({ data, afterChart }: { data: FuelStationHistory; afterChart?: ReactNode }) {
  const series = useMemo(() => fuelHistorySeries(data), [data]);
  const points = useMemo(() => series.flatMap(row => row.points).sort((a, b) => a.instant - b.instant || a.product_code.localeCompare(b.product_code)), [series]);
  const chartSeries = useMemo(() => series.map(row => ({ product: row.product, points: row.points.map(point => ({ time: point.observed_at, average: point.price })) })), [series]);
  return <>
    {points.length ? <><FuelPriceChart showExtremes={false} label="주유소 최근 30일 유종별 가격 추이" window={data.window} series={chartSeries} />
      <div className="fuel-trend-latest-values sr-only">{series.map(row => <span key={row.product}>{fuelProductLabel(row.product)} <strong data-latest-product={row.product}>{row.points.at(-1)!.price.toLocaleString("ko-KR", { maximumFractionDigits: 2 })}</strong>원/L <small>{historyTime(row.points.at(-1)!.observed_at)}</small></span>)}</div></> : <p className="quiet" role="status">최근 30일에 저장된 유효한 가격 관측이 없습니다.</p>}
    {afterChart}
    {points.length ? <details className="fuel-trend-table"><summary>관측값 표 · {points.length.toLocaleString("ko-KR")}건</summary><VirtualTable ariaLabel="주유소 30일 가격 관측값" data={[...points].reverse()} getRowId={point => `${point.product_code}:${point.instant}`} virtualized={false} columns={[
      { id: "time", header: "관측 시각 (한국)", cell: ({ row: { original: point } }) => <time dateTime={point.observed_at}>{historyTime(point.observed_at)}</time> },
      { id: "product", header: "유종", cell: ({ row: { original: point } }) => fuelProductLabel(point.product_code) },
      { id: "price", header: "원/L", cell: ({ row: { original: point } }) => point.price.toLocaleString("ko-KR") },
    ]} /></details> : null}
  </>;
}
export function FuelStationPriceHistory({ place, children }: { place: Pick<Place, "id" | "source">; children?: ReactNode }) {
  const { supported, current, setReload, key } = useFuelStationHistory({ place });
  return <section className="fuel-station-history" aria-label="최근 30일 주유소 가격" aria-busy={supported && !current}>
    <div className="fuel-history-heading"><h3>최근 30일 유가</h3><InfoButton label="주유소 가격 추이">최근 720시간의 저장 관측만 표시합니다. 한국 날짜 기준으로 관측이 전혀 없는 날은 선을 끊고 보간하지 않습니다. 현재 가격과 마지막 실제 관측 가격의 시각은 다를 수 있습니다.{current?.data ? <><p>조회 범위 {historyTime(current.data.window.from_at)} → {historyTime(current.data.window.to_at)} · 한국 시각</p><p>출처 최근 수집 성공 {current.data.source_last_success_at ? historyTime(current.data.source_last_success_at) : "확인되지 않음"}</p></> : null}</InfoButton></div>
    {!supported ? <><p className="quiet">이 출처는 개별 주유소의 저장 가격 추이를 제공하지 않습니다.</p>{children}</> : !current ? <><p className="quiet" role="status">가격 이력 불러오는 중…</p>{children}</> : current.error ? <><div role="alert"><p>{current.error}</p><Button type="button" variant="outline" size="sm" onClick={() => setReload(value => value + 1)}>다시 조회</Button></div>{children}</> : current.data ? <FuelStationHistoryChart key={key} data={current.data} afterChart={children} /> : children}
  </section>;
}

// 조회·선택·요청 수명은 이 도메인 훅이, 아래 컴포넌트는 표현을 소유한다.
function useFuelStationHistory({ place }: { place: Pick<Place, "id" | "source"> }) {
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

  return { supported, current, setReload, key };
}
