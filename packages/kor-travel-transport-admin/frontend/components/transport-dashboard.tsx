"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import Link from "next/link";

import { SectionCard } from "@/components/section-card";
import { StatStrip } from "@/components/stat-strip";
import { TransportBarChart } from "@/components/transport-bar-chart";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardFooter } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { fuelProductLabel, highwayRouteLabel } from "@/lib/transport-presentation";
import { transportGet } from "@/lib/journey";
import { cn } from "@/lib/utils";

type Status = { scheduler_enabled: boolean; collection_enabled: boolean; client_mode: string; enabled_sources: string[]; fuel_prices_stale?: boolean; sources: { source: string; last_success_at: string | null; next_due_at: string | null; last_error: string | null }[] };
type Statistics = { traffic: { route_no: string | null; direction: string | null; observations: number; average_speed: number | null }[]; incidents: { route_no: string | null; incidents: number }[]; fuel_prices: { product_code: string; stations: number; average_price: number | null }[] };
type Traffic = { items: { route_no: string | null; route_name: string | null }[] };
type Incidents = { items: unknown[] };
type DashboardCache = { savedAt: number; status: Status; statistics: Statistics; traffic: Traffic; incidents: Incidents };
type DashboardTab = "overview" | "highway" | "fuel";

const CACHE_KEY = "kor-travel-transport-dashboard-v2";
const CACHE_MAX_AGE_MS = 60_000;
const DASHBOARD_TABS = [["overview", "통합 현황"], ["highway", "고속도로"], ["fuel", "유가"]] as const;
/** dashboard-resize.spec.ts가 차트 카드를 `.panel` 안에서 확인하므로 카드에 기존 클래스를 유지한다. */
const CARD_CLASS_NAME = "panel gap-3 px-0 py-5 [--card-spacing:--spacing(5)]";

const numberFormatter = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 1 });

function number(value: number | null) { return value === null ? "—" : numberFormatter.format(value); }
function readCache(): DashboardCache | null { try { const value = JSON.parse(window.sessionStorage.getItem(CACHE_KEY) ?? "null") as DashboardCache | null; return value && Date.now() - value.savedAt <= CACHE_MAX_AGE_MS ? value : null; } catch { return null; } }
function writeCache(status: Status, statistics: Statistics, traffic: Traffic, incidents: Incidents) { try { window.sessionStorage.setItem(CACHE_KEY, JSON.stringify({ savedAt: Date.now(), status, statistics, traffic, incidents } satisfies DashboardCache)); } catch { /* browser storage is optional */ } }

function ValueRows({ rows }: { rows: { key: string; label: string; value: string }[] }) {
  return <ul className="divide-y divide-border">
    {rows.map((row) => <li className="flex items-center justify-between gap-3 py-2 text-sm first:pt-0 last:pb-0" key={row.key}>
      <span className="min-w-0 truncate">{row.label}</span>
      <strong className="shrink-0 font-semibold tabular-nums">{row.value}</strong>
    </li>)}
  </ul>;
}

export function TransportDashboard() {
  const { tab, setTab, statisticsError, statistics, statisticsLoading, statisticsRetry, setStatisticsLoading, setStatisticsRetry, statusError, status, fuelReadModel, incidents, speedChart, fuelChart, routeNames, fuelRows, statisticalMessage } = useTransportDashboard();
  if (statusError && !status) return <Alert variant="destructive" className="grid-cols-1"><AlertDescription>{statusError}</AlertDescription></Alert>;
  if (!status) return <div role="status" aria-label="저장된 교통정보 현황을 읽는 중입니다…" className="flex flex-col gap-4">
    <p className="text-xs text-text-secondary">저장된 교통정보 현황을 읽는 중입니다…</p>
    <div className="grid gap-4 md:grid-cols-3" aria-hidden="true">{DASHBOARD_TABS.map(([value]) => <Skeleton key={value} className="h-32 w-full" />)}</div>
  </div>;
  const statisticsPlaceholder = <div className="flex flex-col gap-3" role={statisticsLoading ? "status" : undefined}>
    <p className="text-xs text-text-secondary">{statisticalMessage}</p>
    {statisticsLoading ? <Skeleton className="h-[260px] w-full" aria-hidden="true" /> : null}
  </div>;
  return <Tabs value={tab} onValueChange={(value) => { if (value === "overview" || value === "highway" || value === "fuel") setTab(value); }} className="min-w-0 gap-4">
    <TabsList aria-label="교통·유가 정보 보기" className="max-w-full flex-wrap group-data-[orientation=horizontal]/tabs:h-auto">
      {DASHBOARD_TABS.map(([value, label]) => <TabsTrigger value={value} key={value} className="min-h-11 flex-none px-3 py-2">{label}</TabsTrigger>)}
    </TabsList>
    {statisticsError ? <StatisticsRetryNotice statistics={statistics} statisticsError={statisticsError} statisticsLoading={statisticsLoading} statisticsRetry={statisticsRetry} setStatisticsLoading={setStatisticsLoading} setStatisticsRetry={setStatisticsRetry} /> : null}
    {statusError ? <Alert variant="destructive" className="grid-cols-1"><AlertDescription>수집 상태 갱신 실패: {statusError}</AlertDescription></Alert> : null}
    {(status.fuel_prices_stale || Boolean(fuelReadModel?.last_error || fuelReadModel?.next_due_at)) ? <Alert variant="destructive" className="grid-cols-1">
      <AlertTitle>주유소별 최신 가격 반영 지연</AlertTitle>
      <AlertDescription>저장된 유가 원본과 주유소별 가격 지도가 다를 수 있습니다. <Link href="/collections">수집 상태 확인 →</Link></AlertDescription>
    </Alert> : null}
    {DASHBOARD_TABS.map(([value]) => <DashboardPanels key={value} value={value} tab={tab} status={status} incidents={incidents} statistics={statistics} speedChart={speedChart} statisticsPlaceholder={statisticsPlaceholder} fuelChart={fuelChart} routeNames={routeNames} fuelRows={fuelRows} />)}
  </Tabs>;
}


// 조회·선택·요청 수명은 이 도메인 훅이, 아래 컴포넌트는 표현을 소유한다.
function useTransportDashboard() {
  const [cached] = useState<DashboardCache | null>(() => typeof window === "undefined" ? null : readCache());
  const [status, setStatus] = useState<Status | null>(() => cached?.status ?? null);
  const [incidents, setIncidents] = useState<Incidents | null>(() => cached?.incidents ?? null);
  const [statistics, setStatistics] = useState<Statistics | null>(() => cached?.statistics ?? null);
  const [traffic, setTraffic] = useState<Traffic | null>(() => cached?.traffic ?? null);
  const [statusError, setStatusError] = useState("");
  const [statisticsError, setStatisticsError] = useState("");
  const [statisticsRetry, setStatisticsRetry] = useState(0);
  const [statisticsLoading, setStatisticsLoading] = useState(true);
  const [tab, setTab] = useState<DashboardTab>("overview");
  const refreshed = useRef({ status: false, incidents: false, statistics: false, traffic: false });

  useEffect(() => {
    const controller = new AbortController();
    const load = <T,>(path: string, apply: (value: T) => void, failed?: (message: string) => void) => void transportGet<T>(path, controller.signal).then((value) => { if (!controller.signal.aborted) apply(value); }).catch((reason: unknown) => { if (!controller.signal.aborted && failed) failed(reason instanceof Error ? reason.message : "저장된 정보를 불러오지 못했습니다."); });
    load<Status>("transport/collector-status", (value) => { refreshed.current.status = true; setStatus(value); setStatusError(""); }, setStatusError);
    load<Incidents>("transport/highways/incidents?days=1&limit=20", (value) => { refreshed.current.incidents = true; setIncidents(value); });
    load<Traffic>("transport/highways/traffic?days=7&limit=200", (value) => { refreshed.current.traffic = true; setTraffic(value); });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    transportGet<Statistics>("transport/statistics?days=7", AbortSignal.any([controller.signal, AbortSignal.timeout(30_000)]))
      .then((value) => { if (!controller.signal.aborted) { refreshed.current.statistics = true; setStatistics(value); setStatisticsError(""); } })
      .catch(() => { if (!controller.signal.aborted) setStatisticsError("저장된 7일 통계 조회를 완료하지 못했습니다."); })
      .finally(() => { if (!controller.signal.aborted) setStatisticsLoading(false); });
    return () => controller.abort();
  }, [statisticsRetry]);

  useEffect(() => { if (status && statistics && traffic && incidents && Object.values(refreshed.current).every(Boolean)) writeCache(status, statistics, traffic, incidents); }, [status, statistics, traffic, incidents]);

  const routeNames = useMemo(() => new Map((traffic?.items ?? []).filter((item) => item.route_no).map((item) => [item.route_no as string, item.route_name])), [traffic]);
  const statisticalMessage = statisticsError || "저장된 7일 통계를 집계하는 중입니다…";
  const trafficRows = statistics?.traffic.slice(0, 8) ?? [];
  const fuelRows = statistics?.fuel_prices ?? [];
  const fuelReadModel = status?.sources.find((item) => item.source === "fuel_latest_prices");
  const speedChart = trafficRows.map((item) => ({ label: highwayRouteLabel(item.route_no, routeNames.get(item.route_no ?? "")), value: item.average_speed }));
  const fuelChart = fuelRows.map((item) => ({ label: fuelProductLabel(item.product_code), value: item.average_price }));
  return { tab, setTab, statisticsError, statistics, statisticsLoading, statisticsRetry, setStatisticsLoading, setStatisticsRetry, statusError, status, fuelReadModel, incidents, speedChart, fuelChart, routeNames, fuelRows, statisticalMessage };
}


function DashboardPanels({ value, tab, status, incidents, statistics, speedChart, statisticsPlaceholder, fuelChart, routeNames, fuelRows }: { statisticsPlaceholder: import("react").ReactNode } & Pick<ReturnType<typeof useTransportDashboard>, "tab" | "incidents" | "statistics" | "speedChart" | "fuelChart" | "routeNames" | "fuelRows"> & { value: DashboardTab; status: Status }) {
  const speedChartNode = statistics ? <TransportBarChart ariaLabel="노선별 평균 속도 그래프" items={speedChart} unit="km/h" /> : statisticsPlaceholder;
  const fuelChartNode = statistics ? <TransportBarChart ariaLabel="유종별 평균 가격 그래프" items={fuelChart} unit="원/L" /> : statisticsPlaceholder;
  return (<TabsContent key={value} value={value} forceMount className="min-w-0 data-[state=inactive]:hidden hidden:hidden">
      {tab === value ? <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        {value === "overview" ? <DashboardOverviewCards status={status} incidents={incidents} speedChartNode={speedChartNode} fuelChartNode={fuelChartNode} /> : null}
        {value === "highway" ? <DashboardHighwayCards statistics={statistics} speedChartNode={speedChartNode} statisticsPlaceholder={statisticsPlaceholder} routeNames={routeNames} /> : null}
        {value === "fuel" ? <DashboardFuelCards statistics={statistics} fuelChartNode={fuelChartNode} statisticsPlaceholder={statisticsPlaceholder} fuelRows={fuelRows} /> : null}
        <SectionCard className={cn(CARD_CLASS_NAME, "col-span-full")} title="교통정보 찾아보기">
          <div className="flex flex-wrap gap-x-4 gap-y-2 text-sm">
            <Link className="text-brand underline-offset-4 hover:underline" href="/fuel">주유소별 가격 지도 →</Link>
            <Link className="text-brand underline-offset-4 hover:underline" href="/map">교통 장소 지도 →</Link>
            <Link className="text-brand underline-offset-4 hover:underline" href="/highways">고속도로 구간·돌발 검색 →</Link>
            <Link className="text-brand underline-offset-4 hover:underline" href="/collections">제공기관별 수집 상태 →</Link>
          </div>
        </SectionCard>
      </div> : null}
    </TabsContent>);
}


type ChartNodes = { speedChartNode: ReactNode; fuelChartNode: ReactNode; statisticsPlaceholder: ReactNode };

function DashboardOverviewCards({ status, incidents, speedChartNode, fuelChartNode }: Pick<NonNullable<Parameters<typeof DashboardPanels>[0]>, "status" | "incidents"> & Pick<ChartNodes, "speedChartNode" | "fuelChartNode">) {
  return (<>
          <Card className={cn(CARD_CLASS_NAME, "col-span-full")} size="sm">
            <CardContent>
              <StatStrip ariaLabel="교통 수집 요약" items={[
                { key: "scheduler", label: "수집 설정", value: status.scheduler_enabled ? "활성" : "중지", caption: "실제 성공·실패는 수집 상태 메뉴에서 확인" },
                { key: "sources", label: "도로·유가 연결 소스", value: status.enabled_sources.length, unit: "개", caption: "고속도로 소통·돌발·오피넷" },
                { key: "incidents", label: "최근 24시간 도로 돌발", value: incidents?.items.length, unit: "건", loading: !incidents, caption: "저장된 돌발 정보 기준" },
              ]} />
            </CardContent>
            <CardFooter><Link className="text-sm text-brand underline-offset-4 hover:underline" href="/collections">전체 수집 상태 →</Link></CardFooter>
          </Card>
          <SectionCard className={cn(CARD_CLASS_NAME, "md:col-span-2")} title="고속도로 평균 속도">{speedChartNode}</SectionCard>
          <SectionCard className={CARD_CLASS_NAME} title="주요 유종 평균 가격">{fuelChartNode}</SectionCard>
        </>);
}


function DashboardHighwayCards({ statistics, speedChartNode, statisticsPlaceholder, routeNames }: Pick<NonNullable<Parameters<typeof DashboardPanels>[0]>, "statistics" | "routeNames"> & Pick<ChartNodes, "speedChartNode" | "statisticsPlaceholder">) {
  return (<>
          <SectionCard className={cn(CARD_CLASS_NAME, "md:col-span-2")} title="노선별 평균 속도 (최근 7일)">{speedChartNode}</SectionCard>
          <SectionCard className={CARD_CLASS_NAME} title="노선별 돌발 현황">
            {statistics ? <ValueRows rows={statistics.incidents.slice(0, 8).map((item, index) => ({ key: `${item.route_no}-${index}`, label: highwayRouteLabel(item.route_no, routeNames.get(item.route_no ?? "")), value: `${item.incidents}건` }))} /> : statisticsPlaceholder}
          </SectionCard>
        </>);
}


function DashboardFuelCards({ statistics, fuelChartNode, statisticsPlaceholder, fuelRows }: Pick<NonNullable<Parameters<typeof DashboardPanels>[0]>, "statistics" | "fuelRows"> & Pick<ChartNodes, "fuelChartNode" | "statisticsPlaceholder">) {
  return (<>
          <SectionCard className={cn(CARD_CLASS_NAME, "md:col-span-2")} title="유종별 평균 가격 (최근 7일)">{fuelChartNode}</SectionCard>
          <SectionCard className={CARD_CLASS_NAME} title="수집 주유소 수">
            {statistics ? <ValueRows rows={fuelRows.map((item) => ({ key: item.product_code, label: fuelProductLabel(item.product_code), value: `${number(item.stations)}곳` }))} /> : statisticsPlaceholder}
          </SectionCard>
        </>);
}


function StatisticsRetryNotice({ statistics, statisticsError, statisticsLoading, statisticsRetry, setStatisticsLoading, setStatisticsRetry }: Pick<ReturnType<typeof useTransportDashboard>, "statistics" | "statisticsError" | "statisticsLoading" | "statisticsRetry" | "setStatisticsLoading" | "setStatisticsRetry">) {
  return (<Alert variant="destructive" className="grid-cols-1">
      <AlertTitle>{statistics ? "통계 갱신에 실패해 이전 조회 결과를 표시합니다." : "통계를 아직 불러오지 못했습니다."}</AlertTitle>
      <AlertDescription className="flex flex-col items-start gap-3">
        <p>{statisticsError}</p>
        <Button variant="outline" type="button" disabled={statisticsLoading || statisticsRetry >= 3} onClick={() => { setStatisticsLoading(true); setStatisticsRetry((value) => value + 1); }}>
          {statisticsLoading ? <Spinner data-icon="inline-start" aria-hidden="true" /> : null}
          {statisticsLoading ? "통계 확인 중…" : "통계 다시 조회"}
        </Button>
        {statisticsRetry >= 3 ? <p>이 화면에서의 재시도 3회를 사용했습니다. 잠시 후 다시 방문해 주세요.</p> : null}
      </AlertDescription>
    </Alert>);
}
