"use client";
import { VirtualTable } from "@kor-travel/ui/virtual-table";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { TransportError, transportGet, type Place } from "@/lib/journey";
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
    {points.length ? <><FuelPriceChart compact showExtremes={false} label="주유소 최근 30일 유종별 가격 추이" window={data.window} series={chartSeries} />
      <div className="fuel-trend-latest-values sr-only">{series.map(row => <span key={row.product}>{fuelProductLabel(row.product)} <strong data-latest-product={row.product}>{row.points.at(-1)!.price.toLocaleString("ko-KR", { maximumFractionDigits: 2 })}</strong>원/L <small>{historyTime(row.points.at(-1)!.observed_at)}</small></span>)}</div></> : <p className="quiet" role="status">최근 30일에 저장된 유효한 가격 관측이 없습니다.</p>}
    {afterChart}
    {points.length ? <details className="fuel-trend-table"><summary>관측값 표 · {points.length.toLocaleString("ko-KR")}건</summary><VirtualTable ariaLabel="주유소 30일 가격 관측값" data={[...points].reverse()} getRowId={point => `${point.product_code}:${point.instant}`} virtualized={false} columns={[
      { id: "time", header: "관측 시각 (한국)", cell: ({ row: { original: point } }) => <time dateTime={point.observed_at}>{historyTime(point.observed_at)}</time> },
      { id: "product", header: "유종", cell: ({ row: { original: point } }) => fuelProductLabel(point.product_code) },
      { id: "price", header: "원/L", cell: ({ row: { original: point } }) => point.price.toLocaleString("ko-KR") },
    ]} /></details> : null}
  </>;
}
export function FuelStationPriceHistory({ place, children, load = transportGet }: { load?: typeof transportGet; place: Pick<Place, "id" | "source">; children?: ReactNode }) {
  const { supported, current, setReload, key } = useFuelStationHistory({ place, load });
  const heading = useRef<HTMLHeadingElement>(null);
  // 다시 조회하면 오류 영역(버튼 포함)이 '불러오는 중'으로 바뀐다. 초점을 잃지 않게 구역 제목으로 옮긴다.
  const retry = () => { setReload(value => value + 1); heading.current?.focus(); };
  return <section className="fuel-station-history" aria-label="최근 30일 주유소 가격" aria-busy={supported && !current}>
    <div className="fuel-history-heading"><h3 ref={heading} tabIndex={-1}>최근 30일 유가</h3><InfoButton label="주유소 가격 추이">최근 720시간의 저장 관측만 표시합니다. 한국 날짜 기준으로 관측이 전혀 없는 날은 선을 끊고 보간하지 않습니다. 현재 가격과 마지막 실제 관측 가격의 시각은 다를 수 있습니다.{current?.data ? <><p>조회 범위 {historyTime(current.data.window.from_at)} → {historyTime(current.data.window.to_at)} · 한국 시각</p><p>출처 최근 수집 성공 {current.data.source_last_success_at ? historyTime(current.data.source_last_success_at) : "확인되지 않음"}</p></> : null}</InfoButton></div>
    <FuelStationHistoryBody supported={supported} current={current} dataKey={key} onRetry={retry}>{children}</FuelStationHistoryBody>
  </section>;
}

function FuelStationHistoryBody({ supported, current, dataKey, onRetry, children }: { supported: boolean; current?: FuelStationHistoryState; dataKey: string; onRetry: () => void; children?: ReactNode }) {
  if (!supported) return <><p className="quiet">이 출처는 개별 주유소의 저장 가격 추이를 제공하지 않습니다.</p>{children}</>;
  if (!current) return <><p className="quiet" role="status">가격 이력 불러오는 중…</p>{children}</>;
  // 오류마다(key) 대기 시간을 처음부터 센다.
  if (current.error) return <><HistoryRetryAlert key={dataKey} message={current.error} retryAfter={current.retryAfter ?? 0} onRetry={onRetry} />{children}</>;
  return current.data ? <FuelStationHistoryChart key={dataKey} data={current.data} afterChart={children} /> : <>{children}</>;
}

/** 서버 `Retry-After`초 동안 다시 조회를 막고 남은 초를 보인다. */
function HistoryRetryAlert({ message, retryAfter, onRetry }: { message: string; retryAfter: number; onRetry: () => void }) {
  const [retryIn, setRetryIn] = useState(retryAfter);
  useEffect(() => {
    if (retryIn <= 0) return;
    const timer = setTimeout(() => setRetryIn(value => Math.max(0, value - 1)), 1000);
    return () => clearTimeout(timer);
  }, [retryIn]);
  return <div role="alert"><p>{message}</p><Button type="button" variant="outline" size="sm" disabled={retryIn > 0} onClick={onRetry}>가격 이력 다시 조회{retryIn > 0 ? ` (${retryIn}초 후)` : ""}</Button></div>;
}

/** 서버 `Retry-After`를 존중하되 화면에서 오래 막지 않는다. */
const MAX_RETRY_WAIT_SECONDS = 60;
const HISTORY_TIMEOUT_MESSAGE = "가격 이력 조회가 제시간에 끝나지 않았습니다. 잠시 후 다시 조회해 주세요.";

/** backend는 DB 조회 시간 상한 초과를 504로, 성공한 수집 이력 부재를 503으로 구분한다. 브라우저 30초 상한도 지연이다. */
function historyErrorMessage(error: unknown) {
  if (error instanceof TransportError && error.status === 504 || error instanceof DOMException && error.name === "TimeoutError") return HISTORY_TIMEOUT_MESSAGE;
  if (error instanceof TransportError && error.status === 503) return "성공한 가격 수집 이력이 없어 추이를 조회할 수 없습니다.";
  return error instanceof Error && /[가-힣]/.test(error.message) ? error.message : "가격 이력을 불러오지 못했습니다. 다시 조회해 주세요.";
}

type FuelStationHistoryState = { key: string; data?: FuelStationHistory; error?: string; retryAfter?: number };

// 조회·선택·요청 수명은 이 도메인 훅이, 아래 컴포넌트는 표현을 소유한다.
function useFuelStationHistory({ place, load }: { load: typeof transportGet; place: Pick<Place, "id" | "source"> }) {
  const [reload, setReload] = useState(0);
  const key = `${place.source}/${place.id}/${reload}`;
  const [state, setState] = useState<FuelStationHistoryState>();
  const supported = place.id > 0 && place.source === "opinet_browser";
  useEffect(() => {
    if (!supported) return;
    const controller = new AbortController();
    loadFuelStationHistory(place.id, place.source, AbortSignal.any([controller.signal, AbortSignal.timeout(30_000)]), load)
      .then((data) => { if (!controller.signal.aborted) setState({ key, data }); })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setState({ key, error: historyErrorMessage(error), retryAfter: error instanceof TransportError ? Math.min(error.retryAfter, MAX_RETRY_WAIT_SECONDS) : 0 });
      });
    return () => controller.abort();
  }, [key, place.id, place.source, supported, load]);
  const current = state?.key === key ? state : undefined;

  return { supported, current, setReload, key };
}
