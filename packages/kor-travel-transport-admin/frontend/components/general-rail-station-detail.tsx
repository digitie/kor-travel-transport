"use client";
import { hasCoordinates, type Place } from "@/lib/journey";
import { Button } from "@kor-travel/ui/button";
import { GeneralRailJourney } from "./general-rail-journey";

export function GeneralRailStationDetail({ station, onShowMap }: { station: Place; onShowMap?: () => void }) {
  return <section className="metro-station-sheet" aria-label={station.name + " 역 정보"}>
    <header className="metro-station-heading"><span>{station.line_names.join(" · ")}</span><strong>{station.name}</strong><small>코레일</small></header>
    <GeneralRailJourney initialDepartureName={station.name} compact />
    <section className="metro-information"><h3>역 편의정보</h3><p className="quiet">제공기관의 편의시설 등록 정보가 없습니다. 코레일 공개 역 안내에서 확인해 주세요.</p>
      <dl className="metro-station-contact"><div><dt>역 주소</dt><dd>{station.address && onShowMap
        ? <Button type="button" variant="link" className="inline-link station-address" disabled={!hasCoordinates(station)} onClick={onShowMap}>{station.address}{hasCoordinates(station) ? " · 지도에서 보기" : ""}</Button>
        : station.address ?? "미제공"}</dd></div><div><dt>역 연락처</dt><dd>{station.phone ? <a className="inline-link" href={"tel:" + station.phone.replace(/[^+\d]/g, "")}>{station.phone}</a> : "미제공"}</dd></div></dl>
      {station.provider_id ? <a className="inline-link" target="_blank" rel="noreferrer" href={"https://www.korail.com/ticket/train/stationGuide/station/view?stationSeq=" + encodeURIComponent(station.provider_id)}>공식 역 안내 ↗</a> : null}
    </section>
  </section>;
}
