"use client";

import { useEffect, useState, type ReactNode } from "react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { dateTime, hasCoordinates, TransportError, transportGet } from "@/lib/journey";
import { parkingHours, parkingNumber, type PublicParkingItem } from "@/lib/public-parking";
import { collectionSourceLabel } from "@/lib/transport-presentation";

export function PublicParkingDetails({ id, onShowMap }: { id: number; onShowMap?: () => void }) {
  const [reload, setReload] = useState(0);
  const key = `${id}:${reload}`;
  const [state, setState] = useState<{ key: string; data?: PublicParkingItem; error?: string }>();
  useEffect(() => {
    const controller = new AbortController();
    transportGet<PublicParkingItem>(`transport/parking-lots/${id}`,
      AbortSignal.any([controller.signal, AbortSignal.timeout(30_000)]))
      .then(data => { if (!controller.signal.aborted) setState({ key, data }); })
      .catch(error => { if (!controller.signal.aborted) setState({ key, error: error instanceof TransportError ? error.message : "주차장 정보를 불러오지 못했습니다. 잠시 후 다시 조회해 주세요." }); });
    return () => controller.abort();
  }, [id, key]);
  const current = state?.key === key ? state : undefined;
  if (!current) return <section className="inspector-section" aria-label="주차장 상세" aria-busy="true"><p role="status">주차장 기준정보 확인 중…</p><Skeleton className="h-24 w-full" aria-hidden="true" /></section>;
  if (!current.data) return <section className="inspector-section"><Alert variant="destructive"><AlertDescription><p>{current.error}</p><Button variant="outline" type="button" onClick={() => setReload(value => value + 1)}>주차장 정보 다시 조회</Button></AlertDescription></Alert></section>;
  const item = current.data;
  const phone = item.phone?.replace(/[^+\d]/g, "");
  const row = (label: string, value: ReactNode) => <div key={label}><dt>{label}</dt><dd>{value == null || value === "" ? "미제공" : value}</dd></div>;
  const rate = (minutes: number | null, fee: number | null) => `${parkingNumber(minutes, "분")} / ${parkingNumber(fee, "원")}`;
  return <section className="inspector-section public-parking-details" aria-label="주차장 상세">
    <Alert><AlertDescription>총 주차면수는 정적 기준정보입니다. 실시간 잔여면·혼잡도는 제공하지 않습니다.</AlertDescription></Alert>
    {!item.is_current ? <Alert><AlertDescription>현재 완료된 수집본에 포함되지 않은 이전 저장 정보입니다.</AlertDescription></Alert> : null}
    <h3>주차장 안내</h3>
    <dl className="public-parking-data">
      {row("총 주차면수", parkingNumber(item.capacity, "면"))}
      {row("구분·유형", [item.category, item.parking_type].filter(Boolean).join(" · ") || null)}
      {row("도로명 주소", item.road_address)}{row("지번 주소", item.land_address)}
      {row("전화", phone ? <a className="inline-link" href={`tel:${phone}`}>{item.phone}</a> : item.phone)}
      {row("관리기관", item.institution_name)}{row("장애인 주차", item.disabled_parking)}
    </dl>
    {hasCoordinates(item) && onShowMap ? <Button type="button" variant="outline" onClick={onShowMap}>지도에서 위치 보기</Button> : !hasCoordinates(item) ? <p className="quiet">좌표 미등록 · 목록에서 기준정보를 확인할 수 있습니다.</p> : null}
    <h3>요금</h3>
    <dl className="public-parking-data">
      {row("요금 안내", item.fee_info)}{row("기본", rate(item.basic_minutes, item.basic_fee))}
      {row("추가 단위", rate(item.additional_minutes, item.additional_fee))}
      {row("일 주차", rate(item.daily_minutes, item.daily_fee))}
      {row("월 정기권", parkingNumber(item.monthly_fee, "원"))}{row("결제 방법", item.payment_methods)}
    </dl>
    <h3>운영시간</h3>
    <dl className="public-parking-data">
      {row("운영 요일", item.operating_days)}
      {row("평일", parkingHours(item.opening_hours.weekday_open, item.opening_hours.weekday_close))}
      {row("토요일", parkingHours(item.opening_hours.saturday_open, item.opening_hours.saturday_close))}
      {row("공휴일", parkingHours(item.opening_hours.holiday_open, item.opening_hours.holiday_close))}
      {row("이용 안내", item.notes)}
    </dl>
    <p className="quiet">자료 기준일 {item.reference_date ?? "미제공"} · 저장 {dateTime(item.collected_at)}</p>
    <p className="quiet">출처 {collectionSourceLabel(item.source)}{item.provider_id ? ` · 관리번호 ${item.provider_id}` : ""}</p>
  </section>;
}
