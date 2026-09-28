"use client";

import Link from "next/link";
import { X } from "lucide-react";
import { useEffect, useState } from "react";
import { dateTime, transportGet, type Place, type StoredFerry } from "@/lib/journey";
import { useSeoulToday } from "@/lib/journey-hooks";
import { collectionSourceLabel, placeKindLabel } from "@/lib/transport-presentation";
import { FerryDepartures, PlaceDetails, PlaceIcon } from "./journey-controls";
import { AirportDetails } from "./airport-details";

function PortDepartures({ place }: { place: Place }) {
  const today = useSeoulToday();
  const [offset, setOffset] = useState(0);
  const date = new Date(`${today}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + offset);
  const serviceDate = date.toISOString().slice(0, 10);
  const [reload, setReload] = useState(0);
  const key = `${place.provider_id}/${serviceDate}/${reload}`;
  const [state, setState] = useState<{ key: string; data?: StoredFerry; error?: boolean }>();
  useEffect(() => {
    if (!place.provider_id) return;
    const controller = new AbortController();
    transportGet<StoredFerry>(`transport/ports/timetables?${new URLSearchParams({ port_ids: place.provider_id, date: serviceDate })}`, AbortSignal.any([controller.signal, AbortSignal.timeout(25_000)]))
      .then((data) => { if (!controller.signal.aborted) setState({ key, data }); })
      .catch(() => { if (!controller.signal.aborted) setState({ key, error: true }); });
    return () => controller.abort();
  }, [key, place.provider_id, serviceDate]);
  const current = state?.key === key ? state : undefined;
  const table = current?.data?.items.find((item) => item.port_id === place.provider_id);
  if (!place.provider_id) return <p className="empty-state">공식 항구 코드가 없어 시간표를 연결할 수 없습니다.</p>;
  return <section className="inspector-section" aria-label="항구 출도착" aria-busy={!current}>
    <div className="journey-toolbar"><h3>출발·도착 예정</h3><label>운항일<select value={offset} onChange={(event) => setOffset(Number(event.target.value))}>{Array.from({ length: 10 }, (_, index) => <option key={index} value={index}>{index === 0 ? "오늘" : `${index}일 뒤`}</option>)}</select></label></div>
    <p className="quiet">{serviceDate} · 저장 시간표만 조회합니다.</p>
    {!current ? <p role="status">저장 시간표 확인 중…</p> : current.error ? <p className="error" role="alert">시간표를 불러오지 못했습니다. <button className="secondary" type="button" onClick={() => setReload((value) => value + 1)}>다시 조회</button></p> : table ? <FerryDepartures timetable={table} name={place.name} /> : <p className="empty-state">이 항구·날짜의 시간표가 아직 저장되지 않았습니다. 운항편이 없다는 뜻은 아닙니다.</p>}
    <Link className="inline-link" href={`/ferry?port=${encodeURIComponent(place.provider_id)}`}>여러 항구 운항 비교</Link>
  </section>;
}

export function PlaceInspector({ place, onClose }: { place: Place; onClose: () => void }) {
  return <>
    <header className="inspector-heading"><div><span className="place-title"><PlaceIcon kind={place.kind} />{placeKindLabel(place.kind)}</span><h2>{place.name}</h2><p>{collectionSourceLabel(place.source)}</p><p>기준정보 반영 {dateTime(place.updated_at)}</p></div><button type="button" className="secondary icon-button" aria-label="장소 상세 닫기" onClick={onClose}><X size={18} aria-hidden="true" /></button></header>
    {place.kind === "ferry_port" ? <PortDepartures key={place.id} place={place} /> : null}
    {place.kind === "airport" ? <AirportDetails key={place.id} place={place} /> : null}
    <section className="inspector-section" aria-label="장소 정보"><PlaceDetails place={place} showHeading={false} /></section>
  </>;
}
