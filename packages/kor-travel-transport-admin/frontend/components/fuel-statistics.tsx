"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { dateTime, transportGet } from "@/lib/journey";
import { fuelProductLabel } from "@/lib/transport-presentation";
import { fuelDrivingCosts } from "@/lib/driver-statistics";
import { DetailList } from "@/components/detail-list";
import { FilterActions, FilterBar, FilterField } from "@/components/filter-bar";
import { HelpTip } from "./help-tip";
import { SectionCard } from "./section-card";
import { StatStrip } from "./stat-strip";
import { Alert, AlertDescription } from "./ui/alert";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { NativeSelect } from "./ui/native-select";
import { NativeSelectOption } from "./ui/native-select-option";
import { Table, TableBody, TableCaption, TableCell, TableHead, TableHeader, TableRow } from "./ui/table";

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
const inlineLink = "rounded-control text-sm font-medium text-brand underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";

export function FuelDriverStatistics({ metrics }: { metrics: FuelMetrics }) {
  const [liters, setLiters] = useState("50");
  const [efficiency, setEfficiency] = useState("10");
  const costs = fuelDrivingCosts(metrics, Number(liters), Number(efficiency));
  const amount = (n: number | null) => n === null ? null : money(n);
  return <SectionCard title="차량 운영비 비교" description="현재 선택한 범주의 유효 가격과 입력한 주유량·연비로 계산합니다. 주행 조건·할인·주유소까지의 이동 비용은 포함하지 않습니다.">
    <FilterBar>
      <FilterField label="주유량(L)"><Input aria-label="주유량(L)" type="number" min="1" max="1000" value={liters} onChange={(event) => setLiters(event.target.value)} /></FilterField>
      <FilterField label="차량 연비(km/L)"><Input aria-label="차량 연비(km/L)" type="number" min="0.1" max="100" step="0.1" value={efficiency} onChange={(event) => setEfficiency(event.target.value)} /></FilterField>
    </FilterBar>
    <StatStrip ariaLabel="유가 운전 지표" items={[
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
  return <article className="flex flex-col gap-3 rounded-panel border border-border bg-card p-4" aria-label={title}>
    <header className="flex flex-wrap items-baseline justify-between gap-2"><h3 className="text-sm font-semibold text-text-primary">{title}</h3><span className="text-xs text-text-secondary">{metrics.station_count.toLocaleString()}개 주유소</span></header>
    <DetailList columns="auto" items={[
      { label: "평균", value: <>{money(metrics.average_price)} <small className="text-xs font-normal text-text-secondary">원/L</small></>, numeric: true },
      { label: "최저", value: <>{money(metrics.minimum_price)} <small className="text-xs font-normal text-text-secondary">원/L</small></>, numeric: true },
      { label: "최고−최저", value: <>{money(metrics.price_spread)} <small className="text-xs font-normal text-text-secondary">원/L</small></>, numeric: true },
      { label: "가격 표준편차", value: <>{money(metrics.standard_deviation)} <small className="text-xs font-normal text-text-secondary">원/L</small></>, numeric: true },
      { label: "50L 평균 대비 절감", value: <>{money(metrics.saving_50l)} <small className="text-xs font-normal text-text-secondary">원</small></>, numeric: true },
    ]} />
    <p className="text-sm">최저가 · <strong>{metrics.cheapest_station?.name ?? "정보 없음"}</strong>{metrics.cheapest_station_count > 1 ? ` 외 ${metrics.cheapest_station_count - 1}곳` : ""}</p>
    {metrics.cheapest_station?.address ? <p className="text-sm text-text-secondary">{metrics.cheapest_station.longitude != null && metrics.cheapest_station.latitude != null ? <Link className={inlineLink} href={`/fuel?longitude=${metrics.cheapest_station.longitude}&latitude=${metrics.cheapest_station.latitude}`}>{metrics.cheapest_station.address} · 지도</Link> : metrics.cheapest_station.address}</p> : null}
    <small className="text-xs text-text-secondary">수집 기준 {dateTime(metrics.generated_at)}</small>
    {metrics.update_pending ? <p role="status" className="text-sm text-text-secondary">최신 수집 통계 반영 대기</p> : null}
  </article>;
}

export function FuelViewportSummary({ items, pending, failed = false }: { items: FuelViewportStatistics[]; pending: boolean; failed?: boolean }) {
  return <section aria-label="현재 지도 범위 유가 통계" aria-busy={pending}>
    <SectionCard title="현재 지도 범위" size="sm">
      {pending ? <p role="status" className="text-sm text-text-secondary">통계 조회 중…</p> : failed ? <Alert variant="destructive"><AlertDescription>통계를 불러오지 못했습니다.</AlertDescription></Alert> : items.length ? <div className="grid gap-4 xl:grid-cols-2">{items.map((item) => <FuelStatisticsCard key={item.product_code} title={fuelProductLabel(item.product_code)} metrics={item} />)}</div> : <p className="text-sm text-text-secondary">통계 없음 · 수집 완료 후 반영됩니다.</p>}
    </SectionCard>
  </section>;
}

export function FuelPriceTrend({ rows }: { rows: History[] }) {
  if (!rows.length) return <p className="text-sm text-text-secondary">추이 데이터가 없습니다.</p>;
  const values = rows.map((row) => row.average_price);
  const low = Math.min(...values) - 1, range = Math.max(...values) + 1 - low;
  const dayMs = 86_400_000;
  const start = Date.parse(rows[rows.length - 1].day) - 6 * dayMs;
  const x = (day: string) => 40 + (Date.parse(day) - start) / dayMs * 520 / 6;
  const y = (value: number) => 125 - (value - low) / range * 100;
  return <div className="grid gap-4">
    <svg className="w-full text-brand" viewBox="0 0 600 170" role="img" aria-label="최근 7일 평균 유가 추이. 상세 수치는 다음 표에 표시됩니다.">
      {rows.map((row, i) => i > 0 && Date.parse(row.day) - Date.parse(rows[i - 1].day) === dayMs ? <line key={row.day} stroke="currentColor" strokeWidth="2" x1={x(rows[i - 1].day)} y1={y(rows[i - 1].average_price)} x2={x(row.day)} y2={y(row.average_price)} /> : null)}
      {rows.map((row) => <g key={row.day}><circle data-day={row.day} cx={x(row.day)} cy={y(row.average_price)} r="4" fill="currentColor" /><text x={x(row.day)} y={y(row.average_price) - 10} textAnchor="middle" fontSize="12" className="fill-text-secondary">{money(row.average_price)}</text><text x={x(row.day)} y="155" textAnchor="middle" fontSize="12" className="fill-text-secondary">{row.day.slice(5)}</text></g>)}
    </svg>
    <div className="overflow-x-auto"><Table><TableCaption className="sr-only">최근 7일 평균 유가</TableCaption><TableHeader><TableRow><TableHead>날짜(KST)</TableHead><TableHead>평균(원/L)</TableHead><TableHead>주유소</TableHead></TableRow></TableHeader><TableBody>{rows.map((row) => <TableRow key={row.day}><TableCell>{row.day}</TableCell><TableCell className="tabular-nums">{money(row.average_price)}</TableCell><TableCell className="tabular-nums">{row.station_count.toLocaleString()}</TableCell></TableRow>)}</TableBody></Table></div>
  </div>;
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
  return <section className="flex flex-col gap-6" aria-label="유가 통계" aria-busy={pending}>
    <FilterBar>
      <FilterField label="범위"><NativeSelect aria-label="범위" value={scope} onChange={(event) => { setScope(event.target.value); setScopeKey(""); }}>{scopes.map(([value, label]) => <NativeSelectOption key={value} value={value}>{label}</NativeSelectOption>)}</NativeSelect></FilterField>
      <FilterField label="유종"><NativeSelect aria-label="유종" value={product} onChange={(event) => { setProduct(event.target.value); setScopeKey(""); }}>{["B027", "D047", "K015", "B034", "C004"].map((code) => <NativeSelectOption key={code} value={code}>{fuelProductLabel(code)}</NativeSelectOption>)}</NativeSelect></FilterField>
      {shownData?.items.length ? <FilterField label="추이 범주"><NativeSelect aria-label="추이 범주" value={categoryKey} onChange={(event) => setScopeKey(event.target.value)}>{shownData.items.map((row) => <NativeSelectOption key={row.scope_key} value={row.scope_key}>{row.label}</NativeSelectOption>)}</NativeSelect></FilterField> : null}
      <FilterActions><Button type="button" variant="outline" onClick={() => setReload((value) => value + 1)}>새로고침</Button></FilterActions>
    </FilterBar>
    {pending ? <p role="status" className="text-sm text-text-secondary">통계 조회 중…</p> : error ? <Alert variant="destructive"><AlertDescription>통계를 불러오지 못했습니다. 새로고침해 주세요.</AlertDescription></Alert> : shownData ? <>
      <p className="text-sm text-text-secondary">{shownData.generated_at ? `수집 기준 ${dateTime(shownData.generated_at)}` : "첫 수집 완료 후 통계가 생성됩니다."}{shownData.update_pending ? " · 최신 수집 통계 반영 대기" : ""}</p>
      {shownData.items.length ? <>
        {selected ? <FuelDriverStatistics metrics={selected} /> : null}
        {selected ? <FuelStatisticsCard title={`${selected.label} · ${fuelProductLabel(product)}`} metrics={selected} /> : null}
        <SectionCard title={`최근 7일 평균 유가 · ${selected?.label}`} actions={<HelpTip label="유가 집계 기준">KST 일별 마지막 정상 수집 기준이며 수집 기록이 있는 날짜만 표시합니다. 전국·지역은 오피넷, 고속도로는 한국도로공사 기준입니다. 유효 가격을 주유소별 동일 비중으로 집계합니다. 절감액은 범주 평균과 최저가의 차이입니다.</HelpTip>}>
          <FuelPriceTrend rows={shownData.history} />
        </SectionCard>
      </> : <p className="text-sm text-text-secondary">선택한 유종의 통계가 없습니다.</p>}
    </> : null}
    {shownData?.items.length ? <SectionCard title={`전체 범주 비교 · ${fuelProductLabel(product)} (원/L)`}><div className="overflow-x-auto"><Table><TableCaption className="sr-only">전체 범주 비교 · {fuelProductLabel(product)} (원/L)</TableCaption><TableHeader><TableRow><TableHead>범주</TableHead><TableHead>주유소</TableHead><TableHead>평균</TableHead><TableHead>최저</TableHead><TableHead>최저가 주유소</TableHead><TableHead>가격 차이</TableHead><TableHead>50L 절감(원)</TableHead></TableRow></TableHeader><TableBody>{shownData.items.map((row) => <TableRow key={row.scope_key}><TableCell className="font-medium"><Button type="button" variant="link" size="sm" className="h-auto p-0" onClick={() => setScopeKey(row.scope_key)}>{row.label}</Button></TableCell><TableCell className="tabular-nums">{row.station_count}</TableCell><TableCell className="tabular-nums">{money(row.average_price)}</TableCell><TableCell className="tabular-nums">{money(row.minimum_price)}</TableCell><TableCell>{row.cheapest_station?.name}{row.cheapest_station_count > 1 ? ` 외 ${row.cheapest_station_count - 1}곳` : ""}</TableCell><TableCell className="tabular-nums">{money(row.price_spread)}</TableCell><TableCell className="tabular-nums">{money(row.saving_50l)}</TableCell></TableRow>)}</TableBody></Table></div></SectionCard> : null}
  </section>;
}
