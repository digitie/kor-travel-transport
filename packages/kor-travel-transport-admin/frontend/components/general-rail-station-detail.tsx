"use client";
import type { Place } from "@/lib/journey";
import { GeneralRailJourney } from "./general-rail-journey";

export function GeneralRailStationDetail({station}:{station:Place}) {
  return <section className="metro-station-sheet" aria-label={`${station.name} 역 정보`}>
    <header className="metro-station-heading"><span>{station.line_names.join(" · ")}</span><strong>{station.name}</strong><small>코레일</small></header>
    <GeneralRailJourney initialDepartureName={station.name} compact />
    <section className="metro-information"><h3>역 편의정보</h3><p className="quiet">제공기관의 편의시설 등록 정보가 없습니다.</p><dl className="metro-station-contact"><div><dt>역 주소</dt><dd>{station.address??"미제공"}</dd></div><div><dt>역 연락처</dt><dd>{station.phone??"미제공"}</dd></div></dl></section>
  </section>;
}
