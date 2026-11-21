"use client";

import { lazy, Suspense, useEffect, useId, useRef, useState, type ReactNode, type RefObject } from "react";
import { ChartColumn } from "lucide-react";
import { VirtualTable } from "@kor-travel/ui/virtual-table";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogTitle } from "./ui/dialog";
import { Button } from "./ui/button";
import { fuelProductLabel } from "@/lib/transport-presentation";
import { FUEL_CHART_ORDER } from "@/lib/fuel-chart-model";
import { TransportError } from "@/lib/journey";
import {
  binLabel, distributionSummary, distributionTimestamp, gradeTone, histogramValues, loadFuelPriceDistribution,
  sigunguChipLabels, signedWon, won,
  type FuelDistributionTarget, type FuelPriceComparison, type FuelPriceDistribution, type FuelPriceScope,
  type FuelSigunguDistribution, type FuelViewportSigungu,
} from "@/lib/fuel-price-distribution";

// 공개 유가(TRANSPORT_UI_MODE=fuel) 전용. 관리 화면은 이 파일을 쓰지 않는다(publicFuel 조건에서만 렌더).
const Chart = lazy(() => import("./fuel-distribution-chart"));
type Loader = <T>(path: string, signal?: AbortSignal) => Promise<T>;
const VISIBLE_CHIPS = 5;
const scopeShort: Record<string, string> = { nationwide: "전국" };

// unavailable: 서버가 이 주유소·지역을 비교할 수 없다고 답했다(404·422). 재시도 대신 조용한 안내를 보인다.
type LoadState = { key: string; data?: FuelPriceDistribution; error?: boolean; unavailable?: boolean };

function useDistribution(load: Loader, target: FuelDistributionTarget | null, product: string) {
  const key = target ? `${JSON.stringify(target)}:${product}` : "";
  const [state, setState] = useState<LoadState>();
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    if (!target) return;
    const controller = new AbortController();
    loadFuelPriceDistribution(load, target, product, AbortSignal.any([controller.signal, AbortSignal.timeout(20_000)]))
      .then(data => { if (!controller.signal.aborted) setState({ key, data }); })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        const unavailable = error instanceof TransportError && (error.status === 404 || error.status === 422);
        setState({ key, error: !unavailable, unavailable });
      });
    return () => controller.abort();
    // key는 target·product의 값 표현이다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, retry, load]);
  const current = state?.key === key ? state : undefined;
  return { current, retry: () => setRetry(value => value + 1) };
}

/** 범위 요약 안: 지금 지도에 보이는 시군구. 누르면 그 시군구의 가격 분포 대화상자를 연다. */
export function FuelSigunguChips({ regions, total, product, load }: {
  regions: FuelViewportSigungu[]; total: number; product: string; load: Loader;
}) {
  const [expanded, setExpanded] = useState(false);
  const [target, setTarget] = useState<FuelDistributionTarget | null>(null);
  const opener = useRef<HTMLElement | null>(null);
  const listId = useId();
  if (!regions.length) return null;
  const labels = sigunguChipLabels(regions);
  const shown = expanded ? regions : regions.slice(0, VISIBLE_CHIPS);
  const hidden = Math.max(0, total - shown.length);
  return <nav className="fuel-sigungu-chips" aria-label="지도에 보이는 시군구 가격 통계">
    <ul id={listId}>
      {shown.map((region, index) => <li key={`${region.sido_value}:${region.sigungu_value}`}>
        <button type="button" className="fuel-sigungu-chip" onClick={event => {
          opener.current = event.currentTarget;
          setTarget({ kind: "region", sido_value: region.sido_value, sigungu_value: region.sigungu_value, label: labels[index] });
        }} aria-label={`${labels[index]} ${fuelProductLabel(product)} 가격 통계 · 지도 안 ${region.station_count}개 주유소`}>
          <span>{labels[index]}</span><small aria-hidden="true">{region.station_count}</small>
        </button>
      </li>)}
      {regions.length > VISIBLE_CHIPS ? <li>
        {/* 펼치기·접기는 같은 버튼이라 눌러도 초점을 잃지 않는다. */}
        <button type="button" className="fuel-sigungu-chip fuel-sigungu-more" aria-expanded={expanded} aria-controls={listId}
          aria-label={expanded ? "시군구 목록 접기" : `시군구 ${hidden}곳 더 보기`} onClick={() => setExpanded(value => !value)}>
          {expanded ? "접기" : `+${hidden}`}
        </button>
      </li> : null}
    </ul>
    {expanded && total > regions.length ? <p className="fuel-sigungu-note">주유소가 많은 {regions.length}곳만 보입니다. 지도를 확대해 나머지 {total - regions.length}곳을 확인하세요.</p> : null}
    <FuelDistributionDialog target={target} onClose={() => setTarget(null)} initialProduct={product} load={load} returnFocus={opener} />
  </nav>;
}

/** 시군구·주유소 공용 대화상자. 주유소면 그 가격을 곡선 위에 핀으로 표시한다. */
export function FuelDistributionDialog({ target, onClose, initialProduct, load, productChoices, returnFocus }: {
  target: FuelDistributionTarget | null; onClose: () => void; initialProduct: string; load: Loader; productChoices?: string[];
  /** 트리거 없이 여는 대화상자라 닫을 때 연 버튼으로 초점을 직접 돌려준다. */
  returnFocus?: RefObject<HTMLElement | null>;
}) {
  return <Dialog open={target !== null} onOpenChange={open => { if (!open) onClose(); }}>
    {target ? <DialogContent className="fuel-distribution-dialog" showCloseButton={false}
      onCloseAutoFocus={event => { event.preventDefault(); returnFocus?.current?.focus(); }}>
      <FuelDistributionBody key={JSON.stringify(target)} target={target} initialProduct={initialProduct} load={load} productChoices={productChoices} />
      <DialogClose asChild><Button type="button" variant="outline" className="fuel-distribution-close">닫기</Button></DialogClose>
    </DialogContent> : null}
  </Dialog>;
}

function FuelDistributionBody({ target, initialProduct, load, productChoices }: {
  target: FuelDistributionTarget; initialProduct: string; load: Loader; productChoices?: string[];
}) {
  const [product, setProduct] = useState(initialProduct);
  // 토글은 유종을 바꿔 다시 불러오는 동안에도 유지한다.
  const [percent, setPercent] = useState(false);
  const [compare, setCompare] = useState(false);
  const { current, retry } = useDistribution(load, target, product);
  const data = current?.data;
  const placeLabel = target.kind === "region" ? target.label : data?.sigungu_name ?? "주변";
  const productLabel = fuelProductLabel(product);
  const local = data?.sigungu;
  const title = local ? `${placeLabel} ${local.station_count}개 ${productLabel} 값 통계` : `${placeLabel} ${productLabel} 값 통계`;
  const choices = productChoices?.length ? productChoices : FUEL_CHART_ORDER;
  const productId = useId();
  return <div className="fuel-distribution-body" aria-busy={!current}>
    <DialogTitle className="fuel-distribution-title">{title}</DialogTitle>
    <DialogDescription className="fuel-distribution-subtitle">
      {local ? <>최저 {won(local.minimum_price)}, 평균 {won(local.average_price)}, 최고 {won(local.maximum_price)}</> : "가격 분포"}
      {data?.generated_at ? <><br /><time dateTime={data.generated_at}>{distributionTimestamp(data.generated_at)}</time></> : null}
      {data?.update_pending ? <><br />최신 수집 반영 대기</> : null}
    </DialogDescription>
    {choices.length > 1 ? <div className="fuel-distribution-product">
      <label htmlFor={productId}>유종</label>
      <select id={productId} value={product} onChange={event => setProduct(event.target.value)}>
        {choices.map(code => <option key={code} value={code}>{fuelProductLabel(code)}</option>)}
      </select>
    </div> : null}
    {!current ? <p role="status">가격 분포 불러오는 중…</p>
      : current.unavailable ? <p role="status">이 지역은 가격 분포를 제공하지 않습니다.</p>
      : current.error || !data ? <div role="alert"><p>가격 분포를 불러오지 못했습니다.</p><Button type="button" variant="outline" size="sm" onClick={retry}>다시 시도</Button></div>
      : <FuelDistributionContent data={data} productLabel={productLabel} percent={percent} setPercent={setPercent} compare={compare} setCompare={setCompare} />}
  </div>;
}

function FuelDistributionContent({ data, productLabel, percent, setPercent, compare, setCompare }: {
  data: FuelPriceDistribution; productLabel: string;
  percent: boolean; setPercent: (value: boolean) => void; compare: boolean; setCompare: (value: boolean) => void;
}) {
  const local = data.sigungu;
  const station = data.station;
  if (!data.generated_at) return <p role="status">아직 공개된 유가 통계가 없습니다. 수집이 끝나면 표시됩니다.</p>;
  if (!local) return <p role="status">이 시군구에는 이번 통계에 {productLabel} 가격이 없습니다.</p>;
  const pinned = station?.price ?? null;
  return <>
    {station && !station.sells_product ? <p className="fuel-distribution-notice" role="status">이 주유소는 {productLabel}를 팔지 않거나 이번 통계에 가격이 없습니다.</p> : null}
    {local.sufficient ? <>
      <Suspense fallback={<div className="fuel-distribution-chart"><p role="status">차트 준비 중…</p></div>}>
        <Chart distribution={local} nationwide={data.nationwide} productLabel={productLabel} percent={percent} compare={compare}
          pinnedPrice={pinned} label={`${local.label} ${productLabel} 가격 분포 그래프. 아래 요약과 표에 같은 내용이 있습니다.`} />
      </Suspense>
      <DistributionLegend productLabel={productLabel} percent={percent} pinned={pinned} national={compare ? data.nationwide : null} />
      <div className="fuel-distribution-toggles">
        <label><input type="checkbox" checked={percent} onChange={event => setPercent(event.target.checked)} /> 분포(%)</label>
        <label><input type="checkbox" checked={compare} disabled={!data.nationwide} onChange={event => setCompare(event.target.checked)} /> 전국 대비</label>
      </div>
      <p className="fuel-distribution-summary">{distributionSummary(local, productLabel, percent)}{nationalSentence(compare ? data.nationwide : null)}</p>
      <DistributionTable distribution={local} productLabel={productLabel} percent={percent} />
    </> : <p className="fuel-distribution-notice" role="status">
      주유소가 {local.station_count}곳뿐이라 분포 그래프를 그리지 않습니다(최소 {data.minimum_sample}곳). 위 최저·평균·최고만 참고하세요.
    </p>}
    {station?.comparisons.length ? <FuelGradeRow comparisons={station.comparisons} price={station.price!} productLabel={productLabel} sidoName={data.sido_name} /> : null}
  </>;
}

const nationalSentence = (national: FuelPriceScope | null) => national
  ? ` 전국 최저 ${won(national.minimum_price)}, 평균 ${won(national.average_price)}, 최고 ${won(national.maximum_price)}.` : "";

function DistributionLegend({ productLabel, percent, pinned, national }: {
  productLabel: string; percent: boolean; pinned: number | null; national: FuelPriceScope | null;
}) {
  return <ul className="fuel-distribution-legend" aria-label="그래프 범례">
    <li data-series="line">{productLabel} 값(낮은 가격부터)</li>
    <li data-series="bar">값 분포({percent ? "%" : "개"})</li>
    {pinned != null ? <li data-series="pin">이 주유소 {won(pinned)}</li> : null}
    {national ? <>
      <li data-series="national-min">전국 최저({won(national.minimum_price)})</li>
      <li data-series="national-avg">전국 평균({won(national.average_price)})</li>
      <li data-series="national-max">전국 최고({won(national.maximum_price)})</li>
    </> : null}
  </ul>;
}

function DistributionTable({ distribution, productLabel, percent }: { distribution: FuelSigunguDistribution; productLabel: string; percent: boolean }) {
  const shares = histogramValues(distribution, true);
  const last = distribution.histogram.length - 1;
  const rows = distribution.histogram.map((bin, index) => ({ ...bin, share: shares[index], last: index === last }));
  return <details className="fuel-distribution-table">
    <summary>가격 구간 표</summary>
    <VirtualTable ariaLabel={`${distribution.label} ${productLabel} 가격 구간별 주유소`} data={rows} getRowId={row => String(row.start)} virtualized={false} columns={[
      { id: "range", header: "가격 구간", cell: ({ row: { original: row } }) => row.last ? `${binLabel(row.start)} ${won(distribution.maximum_price)} 이하` : `${binLabel(row.start)} ${won(row.end)} 미만` },
      { id: "value", header: percent ? "비율" : "주유소", cell: ({ row: { original: row } }) => percent ? `${row.share}%` : `${row.count}개` },
    ]} />
  </details>;
}

/** 등급 원: 주유소 가격, 시군구·시도·전국 등급과 평균 대비 차이. */
export function FuelGradeRow({ comparisons, price, productLabel, sidoName, action }: {
  comparisons: FuelPriceComparison[]; price: number; productLabel: string; sidoName?: string | null; action?: ReactNode;
}) {
  return <section className="fuel-grade-row" aria-label={`${productLabel} 가격 비교`}>
    <div className="fuel-grade" data-tone="price">
      <span className="fuel-grade-circle" aria-hidden="true">{Math.round(price).toLocaleString("ko-KR")}<small>원</small></span>
      <span className="fuel-grade-caption">{productLabel} 값</span>
      <span className="sr-only">{productLabel} {won(price)}</span>
    </div>
    {comparisons.map(row => {
      const scope = row.scope === "sido" ? sidoName ?? row.label : scopeShort[row.scope] ?? row.label;
      const verdict = row.grade ? `${row.grade} ${row.grade_label}` : "비교 부족";
      return <div key={row.scope} className="fuel-grade" data-tone={gradeTone(row.grade)} data-scope={row.scope}>
        <span className="fuel-grade-circle" aria-hidden="true">{row.grade ?? "–"}<small>{scope}</small></span>
        <span className="fuel-grade-caption" aria-hidden="true">{row.grade_label ?? "비교 부족"}</span>
        <span className="fuel-grade-diff" aria-hidden="true">평균 {signedWon(row.difference)}</span>
        <span className="sr-only">{scope} {row.station_count}곳 중 {verdict}. 평균 {won(row.average_price)} 대비 {signedWon(row.difference)}, 낮은 가격부터 {row.percentile}%.</span>
      </div>;
    })}
    {action}
  </section>;
}

/** 주유소 상세: 시군구·시도·전국 대비 등급과 지역 가격 분포(핀) 대화상자. */
export function FuelStationPricePosition({ stationId, productCodes, selectedProducts, load }: {
  stationId: number; productCodes: string[]; selectedProducts: string[]; load: Loader;
}) {
  const sold = new Set(productCodes);
  const ordered = FUEL_CHART_ORDER.filter(code => sold.has(code));
  const orderedSet = new Set(ordered);
  const initial = selectedProducts.find(code => orderedSet.has(code)) ?? ordered[0];
  const [open, setOpen] = useState(false);
  const opener = useRef<HTMLButtonElement>(null);
  const target: FuelDistributionTarget = { kind: "station", station_id: stationId };
  const { current, retry } = useDistribution(load, initial ? target : null, initial ?? "B027");
  if (!initial) return null;
  const station = current?.data?.station;
  const productLabel = fuelProductLabel(initial);
  return <section className="fuel-station-position" aria-label="주변 대비 가격" aria-busy={!current}>
    {!current ? <p className="quiet" role="status">주변 대비 가격 확인 중…</p>
      : current.unavailable ? <p className="quiet">이 주유소는 지역 가격 비교를 제공하지 않습니다.</p>
      : current.error ? <div role="alert"><p>주변 대비 가격을 불러오지 못했습니다.</p><Button type="button" variant="outline" size="sm" onClick={retry}>다시 시도</Button></div>
      : !station?.comparisons.length ? <p className="quiet">이번 통계에 이 주유소의 {productLabel} 가격이 없어 비교하지 않습니다.</p>
      : <FuelGradeRow comparisons={station.comparisons} price={station.price!} productLabel={productLabel} sidoName={current.data?.sido_name}
          action={<Button ref={opener} type="button" variant="outline" size="sm" className="fuel-grade-open" onClick={() => setOpen(true)}>
            <ChartColumn aria-hidden="true" size={16} />{current.data?.sigungu_name ?? "지역"} 가격 분포
          </Button>} />}
    <FuelDistributionDialog target={open ? target : null} onClose={() => setOpen(false)} initialProduct={initial} load={load} productChoices={ordered} returnFocus={opener} />
  </section>;
}
