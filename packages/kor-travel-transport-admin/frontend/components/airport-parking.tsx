"use client";

import Link from "next/link";
import { useEffect, useId, useState } from "react";
import { RefreshCw } from "lucide-react";
import { MapFilterBar, MapFilterField } from "@kor-travel/ui/map-controls";
import { DashboardProvider, useDashboard } from "@kor-travel/parking-ui/context";
import { buildApiClient } from "@kor-travel/parking-ui/api";
import { CurrentStatusView } from "@kor-travel/parking-ui/current";
import { AnalyticsView } from "@kor-travel/parking-ui/analytics";
import { HistoryView } from "@kor-travel/parking-ui/history";
import { FeesView } from "@kor-travel/parking-ui/fees";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./ui/tabs";
import { Button } from "./ui/button";
import { InfoButton } from "./info-button";
import { dagsterJobRunsUrl } from "@/lib/dagster-scope";

const parkingApi = buildApiClient("/api/transport", "");
export type ParkingView = "current" | "analytics" | "history" | "fees";
type View = ParkingView;

export function AirportParking({ initialSelection = null, initialView = "current" }: { initialSelection?: { airportCode: string; parkingLotId: number | null } | null; initialView?: ParkingView }) {
  return <DashboardProvider apiClient={parkingApi} initialSelection={initialSelection}><ParkingWorkspace initialView={initialView} /></DashboardProvider>;
}

function ParkingWorkspace({ initialView }: { initialView: View }) {
  const id = useId();
  const { airports, selectedAirportCode, selectedParkingLotId, selectedAirportLots, onAirportChange, onParkingLotChange, onRefresh, loading, collectorStatus, error } = useDashboard();
  const [view, setView] = useState<View>(initialView);
  const [visited, setVisited] = useState<Set<View>>(() => new Set([initialView]));
  useEffect(() => {
    if (!selectedAirportCode) return;
    const url = new URL(window.location.href);
    url.searchParams.set("airport", selectedAirportCode);
    if (selectedParkingLotId !== null) url.searchParams.set("lot", String(selectedParkingLotId)); else url.searchParams.delete("lot");
    if (view !== "current") url.searchParams.set("view", view); else url.searchParams.delete("view");
    window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}${url.hash}`);
  }, [selectedAirportCode, selectedParkingLotId, view]);
  const unavailable = loading ? <p role="status" className="notice">공항 자료를 불러오는 중입니다.</p> : error ? null : <p className="notice">저장된 공항이 없습니다.</p>;
  const flightsParams = new URLSearchParams({ airport: selectedAirportCode });
  if (selectedParkingLotId !== null) flightsParams.set("lot", String(selectedParkingLotId));
  return <section className="parking-radar parking-admin" aria-label="공항 주차장" aria-busy={loading}>
    <MapFilterBar>
      <MapFilterField label="공항 선택" htmlFor={`${id}-airport`}><select id={`${id}-airport`} value={selectedAirportCode} disabled={!airports.length} onChange={(event) => onAirportChange(event.target.value)}>{!airports.length ? <option value="">{error ? "조회 실패" : loading ? "공항 조회 중" : "저장된 공항 없음"}</option> : null}{airports.map((airport) => <option key={airport.code} value={airport.code}>{airport.name_ko}</option>)}</select></MapFilterField>
      <MapFilterField label="세부 주차장" htmlFor={`${id}-lot`}><select id={`${id}-lot`} value={selectedParkingLotId ?? (view === "fees" ? selectedAirportLots[0]?.id ?? "" : "all")} disabled={!selectedAirportCode || !selectedAirportLots.length} onChange={(event) => onParkingLotChange(event.target.value === "all" ? null : Number(event.target.value))}>{view !== "fees" ? <option value="all">전체 주차장</option> : null}{view === "fees" && !selectedAirportLots.length ? <option value="">활성 주차장 없음</option> : null}{selectedAirportLots.map((lot) => <option key={lot.id} value={lot.id}>{lot.name}</option>)}</select></MapFilterField>
      <Button variant="outline" disabled={loading} onClick={onRefresh}><RefreshCw data-icon="inline-start" />새로고침</Button>
      {selectedAirportCode ? <Link className="parking-flight-link" href={`/flights?${flightsParams}`}>선택 공항의 항공편·지도</Link> : null}
      <InfoButton label="주차 자료 갱신"><p>화면이 열려 있는 동안 15초마다 저장 상태를 확인하고 새 관측이 저장됐을 때 갱신합니다. 관측 시각과 주차장별 자료 지연을 함께 확인하세요.</p><p><Link href="/collections">수집 상태·이력</Link> · <a href={dagsterJobRunsUrl("airport_collection_job")} target="_blank" rel="noreferrer">공항 주차·요금 수집 실행 ↗</a></p></InfoButton>
    </MapFilterBar>
    {collectorStatus?.upstream_rate_limited ? <p role="status" className="quiet">제공기관 호출 제한 · 마지막 저장 관측을 표시합니다.</p> : null}
    {error && (view === "analytics" || view === "history") ? <p role="alert" className="error">{error}</p> : null}
    <Tabs value={view} onValueChange={(next) => { const value = next as View; setView(value); setVisited((current) => new Set([...current, value])); }} className="parking-views">
      <TabsList variant="line" aria-label="주차장 보기"><TabsTrigger value="current">현황</TabsTrigger><TabsTrigger value="analytics">분석</TabsTrigger><TabsTrigger value="history">과거조회</TabsTrigger><TabsTrigger value="fees">요금계산</TabsTrigger></TabsList>
      <TabsContent keepMounted value="current">{visited.has("current") ? <CurrentStatusView /> : null}</TabsContent>
      <TabsContent keepMounted value="analytics">{visited.has("analytics") ? airports.length ? <AnalyticsView active={view === "analytics"} /> : unavailable : null}</TabsContent>
      <TabsContent keepMounted value="history">{visited.has("history") ? airports.length ? <HistoryView active={view === "history"} /> : unavailable : null}</TabsContent>
      <TabsContent keepMounted value="fees">{visited.has("fees") ? <FeesView scopeControls={false} help={<InfoButton label="주차요금 기준">요금의 ‘휴일’은 현재 토·일요일 기준이며 공휴일과 할인 조건은 별도로 계산하지 않습니다. 공항별 공개 요금 규칙이 없는 경우에는 미지원으로 표시합니다.</InfoButton>} /> : null}</TabsContent>
    </Tabs>
  </section>;
}
