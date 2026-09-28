"use client";

import { useEffect, useId, useRef, useState } from "react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Empty, EmptyDescription, EmptyHeader } from "@/components/ui/empty";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { dateTime, seoulDate, TransportError, transportGet, type Place } from "@/lib/journey";
import { useSeoulToday } from "@/lib/journey-hooks";

type Flight = { flight_number: string; direction: string; airline: string | null; scheduled_at: string; estimated_at: string | null; origin_airport: string; destination_airport: string; status: string | null };
type Parking = { parking_lot_name: string; available_spaces: number | null; total_spaces: number | null; observed_at: string };
type FlightResult = { items: Flight[]; status: string; error_message: string | null };
// 패널을 닫고 다시 열어도 제공기관 대기를 잃지 않는다. 브라우저 탭 수명 동안 공유한다.
let flightRetryAt = 0;

// 항공편은 provider 호출 가능 경로이므로 선택만으로 호출하지 않는다.
export function AirportDetails({ place }: { place: Place }) {
  const directionId = useId();
  const today = useSeoulToday();
  const [parking, setParking] = useState<{ items?: Parking[]; error?: boolean }>({});
  const [result, setResult] = useState<{ date: string; data: FlightResult }>();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [direction, setDirection] = useState("");
  const request = useRef<AbortController | null>(null);
  const data = result?.date === today ? result.data : undefined;
  useEffect(() => {
    const controller = new AbortController();
    if (place.provider_id) transportGet<{ items: Parking[] }>(`parking/current?airport_code=${encodeURIComponent(place.provider_id)}`, AbortSignal.any([controller.signal, AbortSignal.timeout(25_000)]))
      .then((value) => { if (!controller.signal.aborted) setParking(value); })
      .catch(() => { if (!controller.signal.aborted) setParking({ error: true }); });
    return () => { controller.abort(); request.current?.abort(); };
  }, [place.provider_id]);
  async function load() {
    if (!place.provider_id || loading) return;
    if (flightRetryAt > Date.now()) { setError(`다음 조회 가능 시각은 ${dateTime(new Date(flightRetryAt).toISOString())}입니다.`); return; }
    request.current?.abort(); const controller = new AbortController(); request.current = controller;
    const date = seoulDate();
    setLoading(true); setError(""); setResult(undefined);
    try {
      const value = await transportGet<FlightResult>(`flights/status?${new URLSearchParams({ airport_code: place.provider_id, local_date: date })}`, AbortSignal.any([controller.signal, AbortSignal.timeout(25_000)]));
      if (!controller.signal.aborted) {
        if (!["success", "sample"].includes(value.status) || value.error_message) {
          if (value.status === "rate_limited") flightRetryAt = Date.now() + 60_000;
          setError(({ disabled: "항공편 조회가 비활성화되어 있습니다.", config_error: "항공편 조회 설정을 확인해야 합니다.", rate_limited: "제공기관 호출 제한으로 조회를 보류했습니다. 1분 뒤 다시 확인해 주세요.", upstream_error: "제공기관의 항공편 정보를 확인하지 못했습니다." } as Record<string, string>)[value.status] ?? "항공편 응답 상태를 확인하지 못했습니다.");
        } else setResult({ date, data: value });
      }
    } catch (reason) {
      if (!controller.signal.aborted) {
        if (reason instanceof TransportError && reason.status === 429) flightRetryAt = Date.now() + Math.max(30, reason.retryAfter) * 1000;
        setError(reason instanceof TransportError ? reason.message : "항공편 조회가 완료되지 않았습니다. 잠시 후 다시 확인해 주세요.");
      }
    } finally { if (!controller.signal.aborted) setLoading(false); }
  }
  const rows = data?.items.filter((row) => !direction || row.direction === direction);
  return <section className="inspector-section" aria-label="공항 출도착·주차">
    <h3>오늘 출발·도착</h3>
    <FieldGroup className="gap-3">
      <Field data-disabled={!place.provider_id || loading}>
        <Button className="w-fit" variant="outline" type="button" disabled={!place.provider_id || loading} onClick={() => void load()}>
          {loading ? <Spinner data-icon="inline-start" aria-hidden="true" /> : null}
          {loading ? "항공편 확인 중…" : "오늘 출도착 조회"}
        </Button>
      </Field>
      <Field>
        <FieldLabel htmlFor={directionId}>운항 방향</FieldLabel>
        <NativeSelect id={directionId} value={direction} onChange={(event) => setDirection(event.target.value)}>
          <NativeSelectOption value="">전체</NativeSelectOption>
          <NativeSelectOption value="departure">출발</NativeSelectOption>
          <NativeSelectOption value="arrival">도착</NativeSelectOption>
        </NativeSelect>
      </Field>
    </FieldGroup>
    {!place.provider_id ? <Empty><EmptyHeader><EmptyDescription>공항 코드가 없어 출도착을 조회할 수 없습니다.</EmptyDescription></EmptyHeader></Empty> : null}
    {error ? <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert> : null}
    {data?.status === "sample" ? <Alert><AlertDescription>예시 항공편입니다. 실제 운항 정보가 아닙니다.</AlertDescription></Alert> : null}
    {loading ? <div className="flex flex-col gap-3" role="status"><p>제공기관 항공편 확인 중…</p><Skeleton className="h-16 w-full" aria-hidden="true" /></div> : null}
    <div aria-live="polite">{rows ? <><p className="quiet">{result?.date} · {rows.length}편 · 예정 시각은 변경될 수 있습니다.</p>{rows.slice(0, 20).map((row, index) => <article className="departure-row" key={index}><div className="departure-time"><strong>{new Date(row.estimated_at ?? row.scheduled_at).toLocaleTimeString("ko-KR", { timeZone: "Asia/Seoul", hour: "2-digit", minute: "2-digit", hour12: false })}</strong><span>{row.direction === "arrival" ? "도착" : row.direction === "departure" ? "출발" : "방향 미제공"} · {row.flight_number}</span></div><div className="departure-route"><strong>{row.origin_airport} → {row.destination_airport}</strong><small>{row.airline}</small></div><div className="departure-meta"><span>{row.status ?? "상태 미제공"}</span><small>예정 {dateTime(row.scheduled_at)}</small></div></article>)}{!rows.length ? <Empty><EmptyHeader><EmptyDescription>등록된 항공편이 없습니다. 미운항을 확정하는 정보는 아닙니다.</EmptyDescription></EmptyHeader></Empty> : null}{rows.length > 20 ? <p className="quiet">상위 20편을 표시합니다. 전체 항공편은 비행·공항 메뉴에서 확인하세요.</p> : null}</> : !loading && place.provider_id ? <Empty><EmptyHeader><EmptyDescription>출도착 조회를 누르면 제공기관의 오늘 운항편을 확인합니다.</EmptyDescription></EmptyHeader></Empty> : null}</div>
    <h3>저장된 주차 현황</h3>
    {!place.provider_id ? (
      <Empty><EmptyHeader><EmptyDescription>공항 코드가 없어 주차 현황을 조회할 수 없습니다.</EmptyDescription></EmptyHeader></Empty>
    ) : parking.error ? (
      <Alert variant="destructive"><AlertDescription>주차 현황 조회에 실패했습니다.</AlertDescription></Alert>
    ) : !parking.items ? (
      <div className="flex flex-col gap-3" role="status">
        <p className="flex items-center gap-2"><Spinner aria-hidden="true" />주차 현황 확인 중…</p>
        <Skeleton className="h-16 w-full" aria-hidden="true" />
      </div>
    ) : parking.items.length ? parking.items.map((row) => <div className="parking-detail-row" key={row.parking_lot_name}><strong>{row.parking_lot_name}</strong><span>여유 {row.available_spaces?.toLocaleString("ko-KR") ?? "미제공"} / {row.total_spaces?.toLocaleString("ko-KR") ?? "미제공"}면</span><small>{dateTime(row.observed_at)}</small></div>) : (
      <Empty><EmptyHeader><EmptyDescription>저장된 주차 관측이 없습니다.</EmptyDescription></EmptyHeader></Empty>
    )}
  </section>;
}
