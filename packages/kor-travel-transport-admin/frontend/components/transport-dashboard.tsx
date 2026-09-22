"use client";

import { useEffect, useRef, useState } from "react";

type Status = { scheduler_enabled: boolean; collection_enabled: boolean; client_mode: string; enabled_sources: string[]; sources: { source: string; last_success_at: string | null; next_due_at: string | null; last_error: string | null }[] };
type Statistics = { traffic: { route_no: string | null; direction: string | null; observations: number; average_speed: number | null }[]; incidents: { route_no: string | null; incidents: number }[]; fuel_prices: { product_code: string; stations: number; average_price: number | null }[] };
type Incidents = { items: unknown[] };
type DashboardCache = { savedAt: number; status: Status; statistics: Statistics; incidents: Incidents };

const CACHE_KEY = "kor-travel-transport-dashboard-v1";
const CACHE_MAX_AGE_MS = 60_000;

function moment(value: string | null) { return value ? new Intl.DateTimeFormat("ko-KR", { dateStyle: "short", timeStyle: "short", timeZone: "Asia/Seoul" }).format(new Date(value)) : "없음"; }
function number(value: number | null) { return value === null ? "-" : new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 1 }).format(value); }

function readCache(): DashboardCache | null {
  if (typeof window === "undefined") return null;
  try {
    const value = JSON.parse(window.sessionStorage.getItem(CACHE_KEY) ?? "null") as DashboardCache | null;
    return value && Date.now() - value.savedAt <= CACHE_MAX_AGE_MS ? value : null;
  } catch { return null; }
}

function writeCache(status: Status, statistics: Statistics, incidents: Incidents) {
  try { window.sessionStorage.setItem(CACHE_KEY, JSON.stringify({ savedAt: Date.now(), status, statistics, incidents } satisfies DashboardCache)); } catch { /* private browsing storage is optional */ }
}

async function json<T>(response: Response): Promise<T> {
  if (!response.ok) throw new Error("일부 transport API가 응답하지 않았습니다.");
  return response.json() as Promise<T>;
}

export function TransportDashboard() {
  const [status, setStatus] = useState<Status | null>(null);
  const [incidents, setIncidents] = useState<Incidents | null>(null);
  const [statistics, setStatistics] = useState<Statistics | null>(null);
  const [coreError, setCoreError] = useState("");
  const [statisticsError, setStatisticsError] = useState("");
  const refreshed = useRef({ status: false, incidents: false, statistics: false });

  useEffect(() => {
    let active = true;
    const cached = readCache();
    if (cached) {
      setStatus(cached.status);
      setIncidents(cached.incidents);
      setStatistics(cached.statistics);
    }
    void Promise.all([fetch("/api/transport/transport/collector-status"), fetch("/api/transport/transport/highways/incidents?days=1&limit=20")])
      .then(async ([statusResponse, incidentResponse]) => [await json<Status>(statusResponse), await json<Incidents>(incidentResponse)] as const)
      .then(([nextStatus, nextIncidents]) => { if (active) { refreshed.current.status = true; refreshed.current.incidents = true; setStatus(nextStatus); setIncidents(nextIncidents); setCoreError(""); } })
      .catch((reason) => active && setCoreError(reason instanceof Error ? reason.message : "현황을 불러오지 못했습니다."));
    void fetch("/api/transport/transport/statistics?days=7")
      .then(json<Statistics>)
      .then((nextStatistics) => { if (active) { refreshed.current.statistics = true; setStatistics(nextStatistics); setStatisticsError(""); } })
      .catch((reason) => active && setStatisticsError(reason instanceof Error ? reason.message : "통계를 불러오지 못했습니다."));
    return () => { active = false; };
  }, []);

  useEffect(() => { if (status && statistics && incidents && refreshed.current.status && refreshed.current.incidents && refreshed.current.statistics) writeCache(status, statistics, incidents); }, [status, statistics, incidents]);

  if (coreError && !status) return <p className="error">{coreError}</p>;
  if (!status) return <p className="loading">저장된 수집 상태를 읽는 중입니다…</p>;

  const statisticsMessage = statisticsError || "저장된 7일 통계를 집계하는 중입니다…";
  return <div className="grid">
    {coreError ? <p className="error wide">저장된 현황을 갱신하지 못했습니다. 이전 저장 상태를 표시합니다: {coreError}</p> : null}
    {statisticsError ? <p className="error wide">7일 통계를 갱신하지 못했습니다. 이전 저장 통계를 표시합니다: {statisticsError}</p> : null}
    <section className="panel"><span className="metric">Dagster scheduler</span><strong className="value">{status.scheduler_enabled ? "활성" : "중지"}</strong><p className="quiet">수집 {status.collection_enabled ? "허용" : "비활성"} · {status.client_mode}</p></section>
    <section className="panel"><span className="metric">활성 provider</span><strong className="value">{status.enabled_sources.length}</strong><p className="quiet">{status.enabled_sources.join(", ") || "없음"}</p></section>
    <section className="panel"><span className="metric">최근 24시간 돌발</span><strong className="value">{incidents?.items.length ?? "…"}</strong><p className="quiet">저장된 고속도로 돌발 기준</p></section>
    <section className="panel wide"><h2>수집 소스</h2><ul className="status-list">{status.sources.map((source) => <li key={source.source}><span><strong>{source.source}</strong>{source.last_error ? <small className="error"> · {source.last_error}</small> : null}</span><span className="quiet">성공 {moment(source.last_success_at)} · 다음 {moment(source.next_due_at)}</span></li>)}</ul></section>
    <section className="panel"><h2>유가 통계 (7일)</h2>{statistics ? <ul className="row-list">{statistics.fuel_prices.map((item) => <li key={item.product_code}><span>{item.product_code} · {item.stations}개</span><strong>{item.average_price === null ? "-" : `${number(item.average_price)}원`}</strong></li>)}</ul> : <p className={statisticsError ? "error" : "quiet"}>{statisticsMessage}</p>}</section>
    <section className="panel wide"><h2>고속도로 속도 (7일)</h2>{statistics ? <ul className="row-list">{statistics.traffic.slice(0, 8).map((item, index) => <li key={`${item.route_no}-${item.direction}-${index}`}><span>{item.route_no ?? "노선 미상"} {item.direction ?? ""} · {item.observations}건</span><strong>{item.average_speed === null ? "-" : `${number(item.average_speed)} km/h`}</strong></li>)}</ul> : <p className={statisticsError ? "error" : "quiet"}>{statisticsMessage}</p>}</section>
    <section className="panel"><h2>노선별 돌발</h2>{statistics ? <ul className="row-list">{statistics.incidents.slice(0, 8).map((item, index) => <li key={`${item.route_no}-${index}`}><span>{item.route_no ?? "노선 미상"}</span><strong>{item.incidents}건</strong></li>)}</ul> : <p className={statisticsError ? "error" : "quiet"}>{statisticsMessage}</p>}</section>
  </div>;
}
