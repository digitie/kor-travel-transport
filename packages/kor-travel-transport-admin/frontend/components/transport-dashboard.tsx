"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";

import { TransportBarChart } from "@/components/transport-bar-chart";
import { fuelProductLabel, highwayRouteLabel } from "@/lib/transport-presentation";

type Status = { scheduler_enabled: boolean; collection_enabled: boolean; client_mode: string; enabled_sources: string[]; sources: { source: string; last_success_at: string | null; next_due_at: string | null; last_error: string | null }[] };
type Statistics = { traffic: { route_no: string | null; direction: string | null; observations: number; average_speed: number | null }[]; incidents: { route_no: string | null; incidents: number }[]; fuel_prices: { product_code: string; stations: number; average_price: number | null }[] };
type Traffic = { items: { route_no: string | null; route_name: string | null }[] };
type Incidents = { items: unknown[] };
type DashboardCache = { savedAt: number; status: Status; statistics: Statistics; traffic: Traffic; incidents: Incidents };
type DashboardTab = "overview" | "highway" | "fuel";

const CACHE_KEY = "kor-travel-transport-dashboard-v2";
const CACHE_MAX_AGE_MS = 60_000;

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
  const [tab, setTab] = useState<DashboardTab>("overview");
  const refreshed = useRef({ status: false, incidents: false, statistics: false, traffic: false });

  useEffect(() => {
    let active = true;
    const load = <T,>(path: string, apply: (value: T) => void, failed?: (message: string) => void) => void fetch(path).then(json<T>).then((value) => { if (active) apply(value); }).catch((reason: unknown) => { if (active && failed) failed(reason instanceof Error ? reason.message : "저장된 정보를 불러오지 못했습니다."); });
    load<Status>("/api/transport/transport/collector-status", (value) => { refreshed.current.status = true; setStatus(value); setStatusError(""); }, setStatusError);
    load<Incidents>("/api/transport/transport/highways/incidents?days=1&limit=20", (value) => { refreshed.current.incidents = true; setIncidents(value); });
    load<Statistics>("/api/transport/transport/statistics?days=7", (value) => { refreshed.current.statistics = true; setStatistics(value); setStatisticsError(""); }, setStatisticsError);
    load<Traffic>("/api/transport/transport/highways/traffic?days=7&limit=200", (value) => { refreshed.current.traffic = true; setTraffic(value); });
    return () => { active = false; };
  }, []);

  useEffect(() => { if (status && statistics && traffic && incidents && Object.values(refreshed.current).every(Boolean)) writeCache(status, statistics, traffic, incidents); }, [status, statistics, traffic, incidents]);

  const routeNames = useMemo(() => new Map((traffic?.items ?? []).filter((item) => item.route_no).map((item) => [item.route_no as string, item.route_name])), [traffic]);
  if (statusError && !status) return <p className="error">{statusError}</p>;
  if (!status) return <p className="loading">저장된 교통정보 현황을 읽는 중입니다…</p>;
  const statisticalMessage = statisticsError || "저장된 7일 통계를 집계하는 중입니다…";
  const trafficRows = statistics?.traffic.slice(0, 8) ?? [];
  const fuelRows = statistics?.fuel_prices ?? [];
  const speedChart = trafficRows.map((item) => ({ label: highwayRouteLabel(item.route_no, routeNames.get(item.route_no ?? "")), value: item.average_speed }));
  const fuelChart = fuelRows.map((item) => ({ label: fuelProductLabel(item.product_code), value: item.average_price }));

  return <>
    <div className="transport-tabs" role="group" aria-label="교통·유가 정보 보기">
      {([ ["overview", "통합 현황"], ["highway", "고속도로"], ["fuel", "유가"] ] as const).map(([value, label]) => <button aria-controls={`transport-panel-${value}`} aria-pressed={tab === value} className={tab === value ? "active" : ""} key={value} onClick={() => setTab(value)} type="button">{label}</button>)}
    </div>
    {statisticsError ? <p className="error">통계 갱신에 실패해 이전 저장 정보를 표시합니다: {statisticsError}</p> : null}
    {statusError ? <p className="error" role="alert">수집 상태 갱신 실패: {statusError}</p> : null}
    <div className="grid" id={`transport-panel-${tab}`}>
      {tab === "overview" ? <>
        <section className="panel"><span className="metric">수집 설정</span><strong className="value">{status.scheduler_enabled ? "활성" : "중지"}</strong><p className="quiet">실제 성공·실패는 수집 상태 메뉴에서 확인</p><Link href="/collections">전체 수집 상태 →</Link></section>
        <section className="panel"><span className="metric">도로·유가 연결 소스</span><strong className="value">{status.enabled_sources.length}</strong><p className="quiet">고속도로 소통·돌발·오피넷</p></section>
        <section className="panel"><span className="metric">최근 24시간 도로 돌발</span><strong className="value">{incidents?.items.length ?? "…"}</strong><p className="quiet">저장된 돌발 정보 기준</p></section>
        <section className="panel wide"><h2>고속도로 평균 속도</h2>{statistics ? <TransportBarChart ariaLabel="노선별 평균 속도 그래프" items={speedChart} unit="km/h" /> : <p className="quiet">{statisticalMessage}</p>}</section>
        <section className="panel"><h2>주요 유종 평균 가격</h2>{statistics ? <TransportBarChart ariaLabel="유종별 평균 가격 그래프" items={fuelChart} unit="원/L" /> : <p className="quiet">{statisticalMessage}</p>}</section>
      </> : null}
      {tab === "highway" ? <>
        <section className="panel wide"><h2>노선별 평균 속도 (최근 7일)</h2>{statistics ? <TransportBarChart ariaLabel="노선별 평균 속도 그래프" items={speedChart} unit="km/h" /> : <p className="quiet">{statisticalMessage}</p>}</section>
        <section className="panel"><h2>노선별 돌발 현황</h2>{statistics ? <ul className="row-list">{statistics.incidents.slice(0, 8).map((item, index) => <li key={`${item.route_no}-${index}`}><span>{highwayRouteLabel(item.route_no, routeNames.get(item.route_no ?? ""))}</span><strong>{item.incidents}건</strong></li>)}</ul> : <p className="quiet">{statisticalMessage}</p>}</section>
      </> : null}
      {tab === "fuel" ? <>
        <section className="panel wide"><h2>유종별 평균 가격 (최근 7일)</h2>{statistics ? <TransportBarChart ariaLabel="유종별 평균 가격 그래프" items={fuelChart} unit="원/L" /> : <p className="quiet">{statisticalMessage}</p>}</section>
        <section className="panel"><h2>수집 주유소 수</h2>{statistics ? <ul className="row-list">{fuelRows.map((item) => <li key={item.product_code}><span>{fuelProductLabel(item.product_code)}</span><strong>{number(item.stations)}곳</strong></li>)}</ul> : <p className="quiet">{statisticalMessage}</p>}</section>
      </> : null}
      <section className="panel wide"><h2>교통정보 찾아보기</h2><p><Link href="/map">주유소별 가격 지도 →</Link> · <Link href="/highways">고속도로 구간·돌발 검색 →</Link> · <Link href="/collections">제공기관별 수집 상태 →</Link></p></section>
    </div>
  </>;
}
