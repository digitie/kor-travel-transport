"use client";

import Link from "next/link";
import { X } from "lucide-react";
import { useEffect, useId, useState } from "react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button, buttonVariants } from "@/components/ui/button";
import { Empty, EmptyDescription, EmptyHeader } from "@/components/ui/empty";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { dateTime, transportGet, type Place, type StoredFerry } from "@/lib/journey";
import { useSeoulToday } from "@/lib/journey-hooks";
import { collectionSourceLabel, placeKindLabel } from "@/lib/transport-presentation";
import { FerryDepartures, PlaceDetails, PlaceIcon } from "./journey-controls";
import { AirportDetails } from "./airport-details";

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
  if (!place.provider_id) return <Empty><EmptyHeader><EmptyDescription>공식 항구 코드가 없어 시간표를 연결할 수 없습니다.</EmptyDescription></EmptyHeader></Empty>;
  return <section className="inspector-section" aria-label="항구 출도착" aria-busy={!current}>
    <h3>출발·도착 예정</h3>
    <FieldGroup>
      <Field>
        <FieldLabel htmlFor={serviceDateId}>운항일</FieldLabel>
        <NativeSelect id={serviceDateId} value={offset} onChange={(event) => setOffset(Number(event.target.value))}>
          {Array.from({ length: 10 }, (_, index) => <NativeSelectOption key={index} value={index}>{index === 0 ? "오늘" : `${index}일 뒤`}</NativeSelectOption>)}
        </NativeSelect>
      </Field>
    </FieldGroup>
    <p className="quiet">{serviceDate} · 저장 시간표만 조회합니다.</p>
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
      <Empty><EmptyHeader><EmptyDescription>이 항구·날짜의 시간표가 아직 저장되지 않았습니다. 운항편이 없다는 뜻은 아닙니다.</EmptyDescription></EmptyHeader></Empty>
    )}
    <Link data-slot="button" className={buttonVariants({ variant: "link" })} href={`/ferry?port=${encodeURIComponent(place.provider_id)}`}>여러 항구 운항 비교</Link>
  </section>;
}

export function PlaceInspector({ place, onClose }: { place: Place; onClose: () => void }) {
  return <>
    <header className="inspector-heading"><div><span className="place-title"><PlaceIcon kind={place.kind} />{placeKindLabel(place.kind)}</span><h2>{place.name}</h2><p>{collectionSourceLabel(place.source)}</p><p>기준정보 반영 {dateTime(place.updated_at)}</p></div><Button type="button" variant="outline" size="icon" aria-label="장소 상세 닫기" onClick={onClose}><X data-icon="inline-start" aria-hidden="true" /></Button></header>
    {place.kind === "ferry_port" ? <PortDepartures key={place.id} place={place} /> : null}
    {place.kind === "airport" ? <AirportDetails key={place.id} place={place} /> : null}
    <section className="inspector-section" aria-label="장소 정보"><PlaceDetails place={place} showHeading={false} /></section>
  </>;
}
