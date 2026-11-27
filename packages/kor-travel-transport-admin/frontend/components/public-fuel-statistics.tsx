"use client";

import { ArrowLeft, MapPin } from "lucide-react";
import Link from "next/link";
import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import { statisticsGet } from "@/lib/public-fuel-statistics-client";
import { EmptyState } from "./empty-state";
import { usePublicFuelStatistics, type ResourceView } from "./public-fuel-statistics-data";
import { TrendSection } from "./public-fuel-statistics-trend";
import { StatStrip } from "./stat-strip";
import { Pending, RetryAlert, Segmented } from "./public-fuel-statistics-parts";
import { buttonVariants } from "./ui/button-variants";
import { NativeSelect } from "./ui/native-select";
import {
  ALL_ROUTES, HIGHWAY_PRODUCTS, formatPrice as money, PUBLIC_FUEL_AREAS, PUBLIC_FUEL_PRODUCTS, STALE_STATISTICS_HOURS, isImplausibleMinimum, listScope, publicMapHref,
  regionOptions, sidoOfSigungu, sigunguGroups, statisticsAgeHours,
  type PublicFuelArea, type PublicFuelMetrics, type PublicFuelPeriod, type PublicFuelStatistics,
} from "@/lib/public-fuel-statistics";
import { fuelProductLabel } from "@/lib/transport-presentation";

const timeFormat = new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
function kstTimestamp(value?: string | null) {
  const instant = value ? new Date(value) : null;
  if (!instant || !Number.isFinite(instant.getTime())) return null;
  const parts = Object.fromEntries(timeFormat.formatToParts(instant).map(({ type, value: part }) => [type, part]));
  return `${parts.year}.${parts.month}.${parts.day} ${parts.hour}:${parts.minute}`;
}

export function PublicFuelStatisticsPage() {
  const state = usePublicFuelStatistics();
  const { view, update, list, current, selected, trend } = state;
  const product = fuelProductLabel(view.product);
  const settled = selected && !current.pending && !current.error;
  return <main className="public-fuel-stats" aria-labelledby="public-fuel-stats-title">
    <header className="public-fuel-stats-header">
      <MapBackLink fromMap={state.fromMap} />
      <div>
        <h1 id="public-fuel-stats-title">지역별 유가 통계</h1>
        <p>전국·시도·시군구·고속도로의 평균·최저·최고 가격과 기간별 변화</p>
      </div>
    </header>
    <section className="public-fuel-stats-controls" aria-label="조회 조건">
      <Segmented legend="범위" name="area" options={PUBLIC_FUEL_AREAS} value={view.area}
        onChange={area => update({ area: area as PublicFuelArea, region: "" })} />
      <RegionPicker area={view.area} list={list} region={state.region ?? view.region} onChange={region => update({ region })} />
      <Segmented legend="유종" name="product" value={view.product} onChange={code => update({ product: code })}
        options={PUBLIC_FUEL_PRODUCTS.map(code => [code, fuelProductLabel(code)])}
        disabled={view.area === "highway" ? PUBLIC_FUEL_PRODUCTS.filter(code => !HIGHWAY_PRODUCTS.includes(code)) : []}
        note={view.area === "highway" ? "고속도로 휴게소는 휘발유·경유·LPG 가격만 있습니다." : undefined} />
    </section>
    <SubstitutionNotices replacedProduct={state.replacedProduct} substitution={settled ? state.substitution : null} product={product} shown={selected?.label} />
    <CurrentStatistics resource={current} selected={selected} product={product} area={view.area} scope={state.scope} onRetry={state.retryCurrent} />
    {!current.error && (current.pending || selected) ? <TrendSection view={view} trend={trend} selected={selected} to={state.to}
      onPeriod={period => update({ period: period as PublicFuelPeriod })} onRetry={state.retryTrend} /> : null}
    {/* 조건을 바꾼 뒤 새 값이 들어오면 한 번 읽어 준다(조회 중 안내는 시각 표시만 한다). */}
    <p className="sr-only" aria-live="polite">{settled ? `${selected.label} ${product} 평균 ${money(selected.average_price)}원` : ""}</p>
    <footer className="public-fuel-stats-notes">
      <p>가격은 오피넷(전국·시도·시군구)과 한국도로공사(고속도로 휴게소) 자료입니다. 평균은 주유소마다 한 번씩 센 판매 가격의 평균이며 할인·적립은 빼지 않았습니다.</p>
      <p>하루 값은 그날 마지막으로 모은 가격입니다. 기록이 없는 날은 선을 끊고 다른 값으로 채우지 않습니다.</p>
    </footer>
  </main>;
}

/**
 * 지도의 통계 단추로 연 화면(`from=map`, 첫 렌더에 읽음)이면 뒤로 가기(지도 위치·선택 유지), 아니면 지도를 새로 연다.
 * 새 탭·수정 키 누름은 브라우저 기본 동작에 맡긴다.
 */
function MapBackLink({ fromMap }: { fromMap: boolean }) {
  return <Link className={buttonVariants({ variant: "outline", size: "sm" })} href="/" onClick={event => {
    if (!fromMap || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    window.history.back();
  }}><ArrowLeft aria-hidden="true" size={16} />유가 지도</Link>;
}

/** 조건을 화면이 바꾼 경우의 안내(화면 읽기 프로그램에도 한 번 읽힌다). URL의 글자는 넣지 않고 앞서 받은 응답의 이름만 쓴다. */
function SubstitutionNotices({ replacedProduct, substitution, product, shown }: { replacedProduct: string | null; substitution: { name: string | null } | null; product: string; shown?: string }) {
  return <div role="status" className="public-fuel-stats-notices">
    {replacedProduct ? <p className="public-fuel-stats-notice" data-tone="warning">고속도로 휴게소에는 {fuelProductLabel(replacedProduct)} 가격이 없어 {product}(으)로 바꿨습니다.</p> : null}
    {substitution && shown ? <p className="public-fuel-stats-notice" data-tone="warning">
      {substitution.name ? `${substitution.name}에는 ${product} 통계가 없어 ${shown} 값을 보여 드립니다.` : `링크의 지역을 찾지 못해 ${shown} 값을 보여 드립니다.`}
    </p> : null}
  </div>;
}

function RegionPicker({ area, list, region, onChange }: { area: PublicFuelArea; list: ResourceView<PublicFuelStatistics>; region: string; onChange: (region: string) => void }) {
  // 유종을 바꿔 새 목록을 기다리는 동안에는 같은 범위의 직전 목록을 그대로 보인다(선택이 깜박이지 않게).
  const items = list.data?.items ?? (list.previous?.scope === listScope(area) ? list.previous.items : undefined);
  if (area === "nationwide") return null;
  const props = { items, pending: list.pending && !items, failed: Boolean(list.error) && !items, region, onChange };
  if (area === "sigungu") return <SigunguPicker {...props} />;
  return <SingleRegionPicker highway={area === "highway"} {...props} />;
}

type PickerProps = { items?: PublicFuelMetrics[]; pending: boolean; failed: boolean; region: string; onChange: (region: string) => void };
function placeholderOption({ pending, failed, items }: Pick<PickerProps, "pending" | "failed" | "items">) {
  if (pending) return <option value="">불러오는 중…</option>;
  if (failed) return <option value="">목록을 불러오지 못했습니다</option>;
  return items?.length ? null : <option value="">선택할 지역 없음</option>;
}

/** 시도 → 시군구 두 단계. 시도를 바꾸면 그 시도의 첫 시군구(이름순)를 고른다. */
function SigunguPicker({ items, pending, failed, region, onChange }: PickerProps) {
  const id = useId();
  const groups = useMemo(() => items ? sigunguGroups(items) : [], [items]);
  const placeholder = placeholderOption({ pending, failed, items });
  const sido = sidoOfSigungu(region);
  const group = groups.find(entry => entry.sido === sido);
  return <div className="public-fuel-stats-region">
    <label htmlFor={`${id}-sido`}>시도 선택</label>
    <NativeSelect id={`${id}-sido`} value={placeholder ? "" : sido ?? ""} disabled={Boolean(placeholder)}
      onChange={event => onChange(groups.find(entry => entry.sido === event.target.value)?.sigungu[0]?.key ?? "")}>
      {placeholder ?? groups.map(entry => <option key={entry.sido} value={entry.sido}>{entry.label}</option>)}
    </NativeSelect>
    <label htmlFor={`${id}-sigungu`}>시군구 선택</label>
    <NativeSelect id={`${id}-sigungu`} value={placeholder ? "" : region} disabled={Boolean(placeholder)} onChange={event => onChange(event.target.value)}>
      {placeholder ?? group?.sigungu.map(entry => <option key={entry.key} value={entry.key}>{entry.label}</option>)}
    </NativeSelect>
  </div>;
}

/** 시도 하나 또는 고속도로 노선 하나. 고속도로는 목록을 읽는 동안에도 "전체 노선"을 고를 수 있다. */
function SingleRegionPicker({ highway, items, pending, failed, region, onChange }: PickerProps & { highway: boolean }) {
  const id = useId();
  const options = useMemo(() => items ? regionOptions(items) : [], [items]);
  if (highway) {
    const value = region || ALL_ROUTES;
    // 링크로 연 노선을 목록이 오기 전에도 그대로 보인다("전체 노선"으로 잘못 보이지 않게).
    const waiting = value !== ALL_ROUTES && !options.some(entry => entry.key === value);
    return <div className="public-fuel-stats-region">
      <label htmlFor={`${id}-region`}>노선 선택</label>
      <NativeSelect id={`${id}-region`} value={value} onChange={event => onChange(event.target.value)}>
        <option value={ALL_ROUTES}>전체 노선</option>
        {waiting ? <option value={value}>{pending ? "노선 불러오는 중…" : "선택한 노선"}</option> : null}
        {options.map(entry => <option key={entry.key} value={entry.key}>{entry.label}</option>)}
        {failed ? <option value="" disabled>노선 목록을 불러오지 못했습니다</option> : null}
      </NativeSelect>
    </div>;
  }
  const placeholder = placeholderOption({ pending, failed, items });
  return <div className="public-fuel-stats-region">
    <label htmlFor={`${id}-region`}>시도 선택</label>
    <NativeSelect id={`${id}-region`} value={placeholder ? "" : region} disabled={Boolean(placeholder)} onChange={event => onChange(event.target.value)}>
      {placeholder ?? options.map(entry => <option key={entry.key} value={entry.key}>{entry.label}</option>)}
    </NativeSelect>
  </div>;
}

function CurrentStatistics({ resource, selected, product, area, scope, onRetry }: { resource: ResourceView<PublicFuelStatistics>; selected?: PublicFuelMetrics; product: string; area: PublicFuelArea; scope: string; onRetry: () => void }) {
  const headingId = useId();
  const heading = useRef<HTMLHeadingElement>(null);
  const data = resource.data;
  let body: ReactNode;
  if (resource.error) body = <RetryAlert error={resource.error} onRetry={onRetry} what="통계" focusTarget={heading} />;
  else if (resource.pending) body = <><Pending retrying={resource.retrying}>현재 통계를 불러오는 중…</Pending><StatStrip ariaLabel="현재 유가" isLoading items={[{ label: "평균 가격", value: null }, { label: "최저 가격", value: null }, { label: "최고 가격", value: null }, { label: "주유소", value: null }]} /></>;
  else if (!data?.generated_at) body = <EmptyState title="아직 공개된 유가 통계가 없습니다" description="첫 수집이 끝나면 통계가 생깁니다. 잠시 뒤 다시 확인해 주세요." />;
  else if (!selected) body = <EmptyState title={`이 범위에는 ${product} 통계가 없습니다`} description={area === "highway" ? "고속도로 휴게소는 휘발유·경유·LPG 가격만 있습니다. 다른 유종을 골라 보세요." : "다른 유종이나 지역을 골라 보세요."} />;
  else body = <CurrentValues data={data} selected={selected} highway={area === "highway"} scope={scope} />;
  return <section className="public-fuel-stats-card" aria-labelledby={headingId} aria-busy={resource.pending}>
    <h2 id={headingId} ref={heading} tabIndex={-1}>{selected && !resource.pending && !resource.error ? `${selected.label} · ${product} 현재 가격` : `현재 ${product} 가격`}</h2>
    {body}
  </section>;
}

function CurrentValues({ data, selected, highway, scope }: { data: PublicFuelStatistics; selected: PublicFuelMetrics; highway: boolean; scope: string }) {
  const suspicious = isImplausibleMinimum(selected.minimum_price, selected.average_price);
  return <>
    <StatStrip ariaLabel="현재 유가" items={[
      { label: "평균 가격", value: money(selected.average_price), unit: "원/L" },
      { label: "최저 가격", value: money(selected.minimum_price), unit: "원/L", caption: suspicious ? "평균보다 30% 넘게 낮음 · 입력 오류일 수 있음" : undefined },
      { label: "최고 가격", value: money(selected.maximum_price), unit: "원/L" },
      { label: "주유소", value: selected.station_count, unit: "곳", caption: highway ? "가격을 모은 휴게소" : "가격을 모은 곳" },
    ]} />
    <CheapestStation selected={selected} highway={highway} scope={scope} />
    <Freshness generatedAt={selected.generated_at ?? data.generated_at} updatePending={data.update_pending} />
  </>;
}

function CheapestStation({ selected, highway, scope }: { selected: PublicFuelMetrics; highway: boolean; scope: string }) {
  const station = selected.cheapest_station;
  const href = publicMapHref(station);
  const others = Math.max(0, (selected.cheapest_station_count ?? 1) - 1);
  return <div className="public-fuel-stats-cheapest">
    <h3>최저가 {highway ? "휴게소" : "주유소"}</h3>
    {station ? <p>
      <strong>{station.name}</strong>{others > 0 ? ` 외 같은 가격 ${others}곳` : ""} · {money(selected.minimum_price)}원/L
      {station.address ? <><br /><span className="public-fuel-stats-address">{station.address}</span></> : null}
      {/* 지도는 첫 렌더에 주소의 좌표를 읽는다. 앱 안 이동(next/link)은 그 전에 주소가 바뀌지 않아 전국 지도가 열리므로 새로 연다. */}
      {href ? <><br /><a className="public-fuel-stats-link" href={href}><MapPin aria-hidden="true" size={14} />지도에서 보기</a></>
        : <><br /><span className="public-fuel-stats-address">{highway ? "휴게소 위치 좌표가 없어 지도 링크는 없습니다." : "위치 좌표가 없어 지도 링크는 없습니다."}</span></>}
    </p> : <p>최저가 주유소 정보가 없습니다.</p>}
    {station && isImplausibleMinimum(selected.minimum_price, selected.average_price) ? <p className="public-fuel-stats-notice" data-tone="warning">이 최저가는 평균보다 30% 넘게 낮아 원천 입력 오류일 수 있습니다. 실제 판매 가격을 확인하세요.</p> : null}
    {others > 0 ? <TiedStations selected={selected} scope={scope} count={others + 1} /> : null}
  </div>;
}

type Tie = NonNullable<PublicFuelMetrics["cheapest_stations"]>[number];
/**
 * 같은 최저가 주유소 목록. 응답의 가격순 목록은 고른 범주에만 실려 오므로(그 밖은 빈 목록) 펼칠 때 그 범주로 한 번 더 읽는다(1분 재사용).
 * 목록은 최대 10곳이다 — 같은 가격이 더 많으면 그렇다고 쓴다.
 */
function TiedStations({ selected, scope, count }: { selected: PublicFuelMetrics; scope: string; count: number }) {
  const [open, setOpen] = useState(false);
  const inline = (selected.cheapest_stations ?? []).length > 0;
  const [loaded, setLoaded] = useState<{ key: string; rows?: Tie[]; failed?: boolean }>({ key: "" });
  const key = `${scope}:${selected.product_code ?? ""}:${selected.scope_key}`;
  useEffect(() => {
    if (!open || inline) return;
    const controller = new AbortController();
    const path = `fuel/statistics?${new URLSearchParams({ scope, product_code: selected.product_code ?? "B027", scope_key: selected.scope_key, include_history: "false" })}`;
    statisticsGet(path, controller.signal, { maxAgeMs: 60_000 }).then(value => {
      const items = (value as { items?: PublicFuelMetrics[] }).items ?? [];
      if (!controller.signal.aborted) setLoaded({ key, rows: items.find(item => item.scope_key === selected.scope_key)?.cheapest_stations ?? [] });
    }, () => { if (!controller.signal.aborted) setLoaded({ key, failed: true }); });
    return () => controller.abort();
  }, [open, inline, key, scope, selected.product_code, selected.scope_key]);
  const rows = (inline ? selected.cheapest_stations ?? [] : loaded.key === key ? loaded.rows ?? [] : []).filter(row => row.price === selected.minimum_price);
  const waiting = open && !inline && loaded.key !== key;
  return <details className="public-fuel-stats-ties" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>같은 최저가 {count}곳 보기</summary>
    {waiting ? <p className="public-fuel-stats-pending">불러오는 중…</p>
      : loaded.key === key && loaded.failed ? <p>목록을 불러오지 못했습니다. 닫았다 다시 펼쳐 보세요.</p>
      : <><ul>{rows.map(row => { const link = publicMapHref(row); return <li key={row.station_key}>
          <strong>{row.name}</strong>{row.address ? ` · ${row.address}` : ""}{link ? <> · <a className="public-fuel-stats-link" href={link}>지도</a></> : null}
        </li>; })}</ul>
        {count > rows.length ? <p className="public-fuel-stats-meta">가격순 목록은 최대 10곳이라 같은 가격 {count}곳 중 {rows.length}곳만 보입니다.</p> : null}</>}
  </details>;
}

function ageText(hours: number) {
  return hours >= 24 ? `${Math.floor(hours / 24)}일` : `${Math.floor(hours)}시간`;
}

function Freshness({ generatedAt, updatePending }: { generatedAt: string | null; updatePending: boolean }) {
  const generated = kstTimestamp(generatedAt);
  const age = statisticsAgeHours(generatedAt);
  return <>
    <p className="public-fuel-stats-freshness">
      {generated ? <><time dateTime={generatedAt ?? undefined}>{generated}</time> 기준</> : "기준 시각 미확인"}
    </p>
    {updatePending ? <p className="public-fuel-stats-notice">새로 모은 가격을 통계에 반영하는 중입니다. 잠시 뒤 다시 확인하면 최신 값이 보입니다.</p> : null}
    {age !== null && age >= STALE_STATISTICS_HOURS ? <p className="public-fuel-stats-notice" data-tone="warning">통계가 {ageText(age)} 전 기준입니다. 최근 가격 수집이 늦어지고 있어 지금 가격과 다를 수 있습니다.</p> : null}
  </>;
}
