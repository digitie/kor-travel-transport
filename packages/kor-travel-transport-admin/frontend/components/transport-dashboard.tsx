"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";

import { TransportBarChart } from "@/components/transport-bar-chart";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { fuelProductLabel, highwayRouteLabel } from "@/lib/transport-presentation";
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
const CARD_CLASS_NAME = "panel gap-3 px-0 py-5 [--card-spacing:--spacing(5)]";

function number(value: number | null) { return value === null ? "—" : new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 1 }).format(value); }
function readCache(): DashboardCache | null { try { const value = JSON.parse(window.sessionStorage.getItem(CACHE_KEY) ?? "null") as DashboardCache | null; return value && Date.now() - value.savedAt <= CACHE_MAX_AGE_MS ? value : null; } catch { return null; } }
function writeCache(status: Status, statistics: Statistics, traffic: Traffic, incidents: Incidents) { try { window.sessionStorage.setItem(CACHE_KEY, JSON.stringify({ savedAt: Date.now(), status, statistics, traffic, incidents } satisfies DashboardCache)); } catch { /* browser storage is optional */ } }
async function json<T>(response: Response): Promise<T> { if (!response.ok) throw new Error("저장된 교통정보를 불러오지 못했습니다."); return response.json() as Promise<T>; }

export function TransportDashboard() {
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
    let active = true;
    const load = <T,>(path: string, apply: (value: T) => void, failed?: (message: string) => void) => void fetch(path).then(json<T>).then((value) => { if (active) apply(value); }).catch((reason: unknown) => { if (active && failed) failed(reason instanceof Error ? reason.message : "저장된 정보를 불러오지 못했습니다."); });
    load<Status>("/api/transport/transport/collector-status", (value) => { refreshed.current.status = true; setStatus(value); setStatusError(""); }, setStatusError);
    load<Incidents>("/api/transport/transport/highways/incidents?days=1&limit=20", (value) => { refreshed.current.incidents = true; setIncidents(value); });
    load<Traffic>("/api/transport/transport/highways/traffic?days=7&limit=200", (value) => { refreshed.current.traffic = true; setTraffic(value); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/transport/transport/statistics?days=7", { signal: AbortSignal.any([controller.signal, AbortSignal.timeout(30_000)]) }).then(json<Statistics>)
      .then((value) => { if (!controller.signal.aborted) { refreshed.current.statistics = true; setStatistics(value); setStatisticsError(""); } })
      .catch(() => { if (!controller.signal.aborted) setStatisticsError("저장된 7일 통계 조회를 완료하지 못했습니다."); })
      .finally(() => { if (!controller.signal.aborted) setStatisticsLoading(false); });
    return () => controller.abort();
  }, [statisticsRetry]);

  useEffect(() => { if (status && statistics && traffic && incidents && Object.values(refreshed.current).every(Boolean)) writeCache(status, statistics, traffic, incidents); }, [status, statistics, traffic, incidents]);

  const routeNames = useMemo(() => new Map((traffic?.items ?? []).filter((item) => item.route_no).map((item) => [item.route_no as string, item.route_name])), [traffic]);
  if (statusError && !status) return <Alert variant="destructive" className="grid-cols-1"><AlertDescription>{statusError}</AlertDescription></Alert>;
  if (!status) return <div role="status" aria-label="저장된 교통정보 현황을 읽는 중입니다…" className="flex flex-col gap-4">
    <p className="quiet">저장된 교통정보 현황을 읽는 중입니다…</p>
    <div className="grid" aria-hidden="true">{DASHBOARD_TABS.map(([value]) => <Skeleton key={value} className="h-32 w-full" />)}</div>
  </div>;
  const statisticalMessage = statisticsError || "저장된 7일 통계를 집계하는 중입니다…";
  const trafficRows = statistics?.traffic.slice(0, 8) ?? [];
  const fuelRows = statistics?.fuel_prices ?? [];
  const fuelReadModel = status.sources.find((item) => item.source === "fuel_latest_prices");
  const speedChart = trafficRows.map((item) => ({ label: highwayRouteLabel(item.route_no, routeNames.get(item.route_no ?? "")), value: item.average_speed }));
  const fuelChart = fuelRows.map((item) => ({ label: fuelProductLabel(item.product_code), value: item.average_price }));
  const statisticsPlaceholder = <div className="flex flex-col gap-3" role={statisticsLoading ? "status" : undefined}>
    <p className="quiet">{statisticalMessage}</p>
    {statisticsLoading ? <Skeleton className="transport-chart" aria-hidden="true" /> : null}
  </div>;

  return <Tabs value={tab} onValueChange={(value) => { if (value === "overview" || value === "highway" || value === "fuel") setTab(value); }} className="min-w-0 gap-4">
    <TabsList aria-label="교통·유가 정보 보기" className="max-w-full flex-wrap group-data-[orientation=horizontal]/tabs:h-auto">
      {DASHBOARD_TABS.map(([value, label]) => <TabsTrigger value={value} key={value} className="min-h-11 flex-none px-3 py-2">{label}</TabsTrigger>)}
    </TabsList>
    {statisticsError ? <Alert variant="destructive" className="grid-cols-1">
      <AlertTitle>{statistics ? "통계 갱신에 실패해 이전 조회 결과를 표시합니다." : "통계를 아직 불러오지 못했습니다."}</AlertTitle>
      <AlertDescription className="flex flex-col items-start gap-3">
        <p>{statisticsError}</p>
        <Button variant="outline" type="button" disabled={statisticsLoading || statisticsRetry >= 3} onClick={() => { setStatisticsLoading(true); setStatisticsRetry((value) => value + 1); }}>
          {statisticsLoading ? <Spinner data-icon="inline-start" aria-hidden="true" /> : null}
          {statisticsLoading ? "통계 확인 중…" : "통계 다시 조회"}
        </Button>
        {statisticsRetry >= 3 ? <p>이 화면에서의 재시도 3회를 사용했습니다. 잠시 후 다시 방문해 주세요.</p> : null}
      </AlertDescription>
    </Alert> : null}
    {statusError ? <Alert variant="destructive" className="grid-cols-1"><AlertDescription>수집 상태 갱신 실패: {statusError}</AlertDescription></Alert> : null}
    {(status.fuel_prices_stale || Boolean(fuelReadModel?.last_error || fuelReadModel?.next_due_at)) ? <Alert variant="destructive" className="grid-cols-1">
      <AlertTitle>주유소별 최신 가격 반영 지연</AlertTitle>
      <AlertDescription>저장된 유가 원본과 주유소별 가격 지도가 다를 수 있습니다. <Link href="/collections">수집 상태 확인 →</Link></AlertDescription>
    </Alert> : null}
    {DASHBOARD_TABS.map(([value]) => <TabsContent key={value} value={value} keepMounted className="min-w-0 hidden:hidden">
      {tab === value ? <div className="grid">
        {value === "overview" ? <>
          <Card className={CARD_CLASS_NAME}>
            <CardHeader className="grid-cols-1"><CardTitle><span className="metric mb-0">수집 설정</span></CardTitle></CardHeader>
            <CardContent className="flex flex-col gap-3"><strong className="value">{status.scheduler_enabled ? "활성" : "중지"}</strong><CardDescription>실제 성공·실패는 수집 상태 메뉴에서 확인</CardDescription></CardContent>
            <CardFooter><Link href="/collections">전체 수집 상태 →</Link></CardFooter>
          </Card>
          <Card className={CARD_CLASS_NAME}>
            <CardHeader className="grid-cols-1"><CardTitle><span className="metric mb-0">도로·유가 연결 소스</span></CardTitle></CardHeader>
            <CardContent className="flex flex-col gap-3"><strong className="value">{status.enabled_sources.length}</strong><CardDescription>고속도로 소통·돌발·오피넷</CardDescription></CardContent>
          </Card>
          <Card className={CARD_CLASS_NAME}>
            <CardHeader className="grid-cols-1"><CardTitle><span className="metric mb-0">최근 24시간 도로 돌발</span></CardTitle></CardHeader>
            <CardContent className="flex flex-col gap-3"><strong className="value">{incidents?.items.length ?? "…"}</strong><CardDescription>저장된 돌발 정보 기준</CardDescription></CardContent>
          </Card>
          <Card className={cn(CARD_CLASS_NAME, "wide")}>
            <CardHeader className="grid-cols-1"><CardTitle><h2 className="m-0">고속도로 평균 속도</h2></CardTitle></CardHeader>
            <CardContent>{statistics ? <TransportBarChart ariaLabel="노선별 평균 속도 그래프" items={speedChart} unit="km/h" /> : statisticsPlaceholder}</CardContent>
          </Card>
          <Card className={CARD_CLASS_NAME}>
            <CardHeader className="grid-cols-1"><CardTitle><h2 className="m-0">주요 유종 평균 가격</h2></CardTitle></CardHeader>
            <CardContent>{statistics ? <TransportBarChart ariaLabel="유종별 평균 가격 그래프" items={fuelChart} unit="원/L" /> : statisticsPlaceholder}</CardContent>
          </Card>
        </> : null}
        {value === "highway" ? <>
          <Card className={cn(CARD_CLASS_NAME, "wide")}>
            <CardHeader className="grid-cols-1"><CardTitle><h2 className="m-0">노선별 평균 속도 (최근 7일)</h2></CardTitle></CardHeader>
            <CardContent>{statistics ? <TransportBarChart ariaLabel="노선별 평균 속도 그래프" items={speedChart} unit="km/h" /> : statisticsPlaceholder}</CardContent>
          </Card>
          <Card className={CARD_CLASS_NAME}>
            <CardHeader className="grid-cols-1"><CardTitle><h2 className="m-0">노선별 돌발 현황</h2></CardTitle></CardHeader>
            <CardContent>{statistics ? <ul className="row-list">{statistics.incidents.slice(0, 8).map((item, index) => <li key={`${item.route_no}-${index}`}><span>{highwayRouteLabel(item.route_no, routeNames.get(item.route_no ?? ""))}</span><strong>{item.incidents}건</strong></li>)}</ul> : statisticsPlaceholder}</CardContent>
          </Card>
        </> : null}
        {value === "fuel" ? <>
          <Card className={cn(CARD_CLASS_NAME, "wide")}>
            <CardHeader className="grid-cols-1"><CardTitle><h2 className="m-0">유종별 평균 가격 (최근 7일)</h2></CardTitle></CardHeader>
            <CardContent>{statistics ? <TransportBarChart ariaLabel="유종별 평균 가격 그래프" items={fuelChart} unit="원/L" /> : statisticsPlaceholder}</CardContent>
          </Card>
          <Card className={CARD_CLASS_NAME}>
            <CardHeader className="grid-cols-1"><CardTitle><h2 className="m-0">수집 주유소 수</h2></CardTitle></CardHeader>
            <CardContent>{statistics ? <ul className="row-list">{fuelRows.map((item) => <li key={item.product_code}><span>{fuelProductLabel(item.product_code)}</span><strong>{number(item.stations)}곳</strong></li>)}</ul> : statisticsPlaceholder}</CardContent>
          </Card>
        </> : null}
        <Card className={cn(CARD_CLASS_NAME, "wide")}>
          <CardHeader className="grid-cols-1"><CardTitle><h2 className="m-0">교통정보 찾아보기</h2></CardTitle></CardHeader>
          <CardContent><p className="m-0"><Link href="/map">주유소별 가격 지도 →</Link> · <Link href="/highways">고속도로 구간·돌발 검색 →</Link> · <Link href="/collections">제공기관별 수집 상태 →</Link></p></CardContent>
        </Card>
      </div> : null}
    </TabsContent>)}
  </Tabs>;
}
