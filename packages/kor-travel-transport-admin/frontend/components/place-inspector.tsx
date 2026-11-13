"use client";

import Link from "next/link";
import { X } from "lucide-react";
import { useEffect, useId, useState, type FormEvent } from "react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { buttonVariants } from "@/components/ui/button-variants";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { NativeSelectOption } from "@/components/ui/native-select-option";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { EmptyState } from "@/components/empty-state";
import { dateTime, transportGet, type Place, type StoredFerry } from "@/lib/journey";
import { useSeoulToday } from "@/lib/journey-hooks";
import { collectionSourceLabel, placeKindLabel } from "@/lib/transport-presentation";
import { FerryDepartures, PlaceDetails, PlaceIcon } from "./journey-controls";
import { AirportDetails } from "./airport-details";

// 상세 패널 안의 구획: 위 구획과 hairline으로 나누고 제목은 본문보다 한 단계 크다(Map 상세 패널과 같은 리듬).
const SECTION = "flex min-w-0 flex-col gap-3 border-t border-border pt-4";
const SECTION_TITLE = "text-sm font-semibold text-text-primary";

function PortDepartures({ place }: { place: Place }) {
  const serviceDateId = useId();
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
  if (!place.provider_id) return <EmptyState title="공식 항구 코드가 없어 시간표를 연결할 수 없습니다." />;
  return <section className={SECTION} aria-label="항구 출도착" aria-busy={!current}>
    <h3 className={SECTION_TITLE}>출발·도착 예정</h3>
    <FieldGroup>
      <Field>
        <FieldLabel htmlFor={serviceDateId}>운항일</FieldLabel>
        <NativeSelect id={serviceDateId} value={offset} onChange={(event) => setOffset(Number(event.target.value))}>
          {Array.from({ length: 10 }, (_, index) => <NativeSelectOption key={index} value={index}>{index === 0 ? "오늘" : `${index}일 뒤`}</NativeSelectOption>)}
        </NativeSelect>
      </Field>
    </FieldGroup>
    <p className="text-xs text-text-secondary">{serviceDate} · 저장 시간표만 조회합니다.</p>
    {!current ? (
      <div className="flex flex-col gap-3" role="status">
        <p className="flex items-center gap-2"><Spinner aria-hidden="true" />저장 시간표 확인 중…</p>
        <Skeleton className="h-16 w-full" aria-hidden="true" />
      </div>
    ) : current.error ? (
      <Alert variant="destructive">
        <AlertDescription className="flex flex-col items-start gap-3">
          <p>시간표를 불러오지 못했습니다.</p>
          <Button variant="outline" type="button" onClick={() => setReload((value) => value + 1)}>다시 조회</Button>
        </AlertDescription>
      </Alert>
    ) : table ? <FerryDepartures timetable={table} name={place.name} /> : (
      <EmptyState title="이 항구·날짜의 시간표가 아직 저장되지 않았습니다. 운항편이 없다는 뜻은 아닙니다." />
    )}
    <Link data-slot="button" className={buttonVariants({ variant: "link" })} href={`/ferry?port=${encodeURIComponent(place.provider_id)}`}>여러 항구 운항 비교</Link>
  </section>;
}

function ManualLocationEditor({ place, onSaved, onReload }: { place: Place; onSaved: (updated: Place) => void; onReload: () => void }) {
  const id = useId();
  const [latitude, setLatitude] = useState(String(place.latitude ?? ""));
  const [longitude, setLongitude] = useState(String(place.longitude ?? ""));
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [conflict, setConflict] = useState(false);
  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const lat = Number(latitude); const lon = Number(longitude);
    if (!latitude.trim() || !longitude.trim() || !Number.isFinite(lat) || !Number.isFinite(lon) || lat < 32 || lat > 39.5 || lon < 124 || lon > 132 || note.trim().length < 5) {
      setMessage("위도 32~39.5, 경도 124~132와 5자 이상의 확인 근거를 입력해 주세요."); return;
    }
    setSaving(true); setMessage(""); setConflict(false);
    try {
      const response = await fetch("/api/admin/place-locations", { method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ kind: place.kind, id: place.id, source: place.source, provider_id: place.provider_id,
          expected_name: place.name, expected_city_name: place.city_name ?? null,
          expected_latitude: place.latitude, expected_longitude: place.longitude,
          expected_location_source: place.location_source ?? null, expected_manual_revision: place.manual_location_revision ?? null,
          latitude: lat, longitude: lon, note: note.trim() }) });
      const result = await response.json() as Partial<Place> & { detail?: string };
      if (!response.ok) { if (response.status === 409) setConflict(true); throw new Error(result.detail || "좌표를 저장하지 못했습니다."); }
      onSaved({ ...place, ...result, latitude: lat, longitude: lon, location_source: "admin_manual" });
      setMessage("좌표를 저장했습니다. 지도에서 위치를 확인해 주세요."); setNote("");
    } catch (error) { setMessage(error instanceof Error ? error.message : "좌표를 저장하지 못했습니다."); }
    finally { setSaving(false); }
  };
  return <section className={SECTION} aria-label="좌표 수동 보정">
    <h3 className={SECTION_TITLE}>좌표 수동 보정</h3>
    <p className="text-xs text-text-secondary">공식 {place.kind === "ferry_port" ? "항구" : "터미널"} 코드 {place.provider_id}의 위치만 수정합니다. 근거를 확인한 뒤 입력하세요.</p>
    <form onSubmit={save}><FieldGroup className="gap-3">
      <Field><FieldLabel htmlFor={`${id}-lat`}>위도</FieldLabel><Input id={`${id}-lat`} type="number" min="32" max="39.5" step="any" required value={latitude} onChange={(event) => setLatitude(event.target.value)} /></Field>
      <Field><FieldLabel htmlFor={`${id}-lon`}>경도</FieldLabel><Input id={`${id}-lon`} type="number" min="124" max="132" step="any" required value={longitude} onChange={(event) => setLongitude(event.target.value)} /></Field>
      <Field><FieldLabel htmlFor={`${id}-note`}>확인 근거</FieldLabel><Input id={`${id}-note`} maxLength={500} minLength={5} required value={note} onChange={(event) => setNote(event.target.value)} placeholder="예: 공식 터미널 주소와 지도 시설점 대조" /></Field>
      <Button type="submit" className="w-fit" disabled={saving}>{saving ? "저장 중…" : "좌표 저장"}</Button>
  </FieldGroup></form><p className="text-xs text-text-secondary" role="status" aria-live="polite">{message}</p>
    {conflict ? <Button type="button" variant="outline" className="w-fit" onClick={onReload}>목록 새로 조회</Button> : null}
  </section>;
}

export function PlaceInspector({ place, onClose, onSaved, onReload, onShowMap }: { place: Place; onClose: () => void; onSaved?: (updated: Place) => void; onReload?: () => void; onShowMap?: () => void }) {
  return <>
    <header className="flex items-start justify-between gap-3 border-b border-border pb-3">
      <div className="flex min-w-0 flex-col gap-1">
        <span className="flex items-center gap-2 text-2xs font-medium text-text-secondary"><PlaceIcon kind={place.kind} />{placeKindLabel(place.kind)}</span>
        <h2 className="text-md leading-snug font-semibold break-words text-text-primary">{place.name}</h2>
        <p className="text-xs text-text-secondary">{collectionSourceLabel(place.source)}</p>
        <p className="text-2xs text-text-tertiary">기준정보 반영 {dateTime(place.updated_at)}</p>
      </div>
      <Button type="button" variant="ghost" size="icon-sm" aria-label="장소 상세 닫기" onClick={onClose}><X aria-hidden="true" /></Button>
    </header>
    {place.kind === "ferry_port" ? <PortDepartures key={place.id} place={place} /> : null}
    {place.kind === "airport" ? <AirportDetails key={place.id} place={place} /> : null}
    <section className={SECTION} aria-label="장소 정보"><PlaceDetails place={place} showHeading={false} onShowMap={onShowMap} /></section>
    {((place.kind === "ferry_port" && place.source === "data_go_kr_maritime") ||
      (place.kind === "bus_terminal" && place.source === "data_go_kr_tago")) && place.provider_id && onSaved
      ? <ManualLocationEditor key={`${place.kind}:${place.id}`} place={place} onSaved={onSaved} onReload={onReload ?? onClose} /> : null}
  </>;
}
