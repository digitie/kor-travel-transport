"use client";

import { useEffect, useId, useMemo, useState, type FormEvent } from "react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Empty, EmptyDescription, EmptyHeader } from "@/components/ui/empty";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { dateTime, hasCoordinates, TransportError, transportGet } from "@/lib/journey";
import { parkingNumber, parkingPagePath, publicParkingPlace, type PublicParkingItem, type PublicParkingPage } from "@/lib/public-parking";
import { PlaceIcon } from "./journey-controls";
import { PublicParkingDetails } from "./public-parking-details";
import { TransportMap } from "./transport-map";

type Result = { key: string; query: string; data?: PublicParkingPage; error?: string };

export function PublicParkingLots() {
  const inputId = useId();
  const [query, setQuery] = useState("");
  const [request, setRequest] = useState({ query: "", cursor: "", revision: 0 });
  const key = JSON.stringify(request);
  const [result, setResult] = useState<Result>();
  const [selected, setSelected] = useState<PublicParkingItem | null>(null);
  const [view, setView] = useState<"map" | "list">("map");
  const [focusRevision, setFocusRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    transportGet<PublicParkingPage>(parkingPagePath(request.query, request.cursor),
      AbortSignal.any([controller.signal, AbortSignal.timeout(30_000)]))
      .then(data => {
        if (controller.signal.aborted) return;
        setResult(previous => ({ key, query: request.query, data: {
          ...data,
          items: request.cursor && previous?.query === request.query
            ? [...new Map([...(previous.data?.items ?? []), ...data.items].map(item => [item.id, item])).values()]
            : data.items,
        } }));
      })
      .catch(error => {
        if (controller.signal.aborted) return;
        setResult(previous => ({ key, query: request.query,
          data: previous?.query === request.query ? previous.data : undefined,
          error: error instanceof TransportError ? error.message : "주차장 목록을 불러오지 못했습니다. 잠시 후 다시 조회해 주세요.",
        }));
      });
    return () => controller.abort();
  }, [key, request.query, request.cursor]);
  const data = result?.query === request.query ? result.data : undefined;
  const error = result?.key === key ? result.error : undefined;
  const loading = result?.key !== key;
  const items = data?.items;
  const places = useMemo(() => (items ?? []).map(publicParkingPlace), [items]);
  const reset = () => { setSelected(null); setRequest(value => ({ query: value.query, cursor: "", revision: value.revision + 1 })); };
  const search = (event: FormEvent) => {
    event.preventDefault(); setSelected(null);
    setRequest(value => ({ query: query.trim(), cursor: "", revision: value.revision + 1 }));
  };
  const inspect = (item: PublicParkingItem) => { setSelected(item); setFocusRevision(value => value + 1); };
  return <TransportMap places={places} selectedPlace={selected ? publicParkingPlace(selected) : null}
    view={view} onViewChange={setView} focusRevision={focusRevision}
    onSelectPlace={place => { const item = items?.find(row => row.id === place.id); if (item) inspect(item); }}
    detailTitle={selected?.name} onCloseDetails={() => setSelected(null)}
    details={selected ? <PublicParkingDetails key={selected.id} id={selected.id} onShowMap={() => { setView("map"); setFocusRevision(value => value + 1); }} /> : undefined}
    filterSummary={request.query || "주차장 이름·주소 검색"}
    toolbar={<form onSubmit={search} aria-label="일반 주차장 검색"><FieldGroup className="public-parking-search">
      <Field><FieldLabel htmlFor={inputId}>주차장 이름·주소</FieldLabel><Input id={inputId} type="search" maxLength={100} value={query} onChange={event => setQuery(event.target.value)} placeholder="예: 수지구, 중앙공영주차장" /></Field>
      <Button type="submit">검색</Button><Button type="button" variant="outline" disabled={loading} onClick={reset}>첫 페이지 새로고침</Button>
    </FieldGroup></form>}
    feedback={<div className="public-parking-feedback">
      <p className="quiet">정적 총면수·요금·운영시간 기준정보입니다. 실시간 잔여면은 제공하지 않습니다.</p>
      {data ? <p className="quiet">불러온 {data.items.length.toLocaleString("ko-KR")}곳 · 지도 좌표 {data.items.filter(hasCoordinates).length.toLocaleString("ko-KR")}곳 · 마지막 완료 {dateTime(data.collection.last_success_at)}{data.has_more ? " · 목록에서 더 불러올 수 있습니다." : ""}</p> : null}
      {data?.collection.last_attempt_failed ? <Alert><AlertDescription>최근 수집 시도가 실패해 마지막 완료된 저장 정보를 표시합니다.</AlertDescription></Alert> : null}
      {data?.collection.stale && data.collection.last_success_at ? <Alert><AlertDescription>마지막 완료 수집이 오래된 기준정보입니다. 자료 기준일과 관리기관 안내를 확인해 주세요.</AlertDescription></Alert> : null}
      {error ? <Alert variant="destructive"><AlertDescription><p>{error}</p><Button type="button" variant="outline" onClick={() => setRequest(value => ({ ...value, revision: value.revision + 1 }))}>목록 다시 조회</Button><Button type="button" variant="outline" onClick={reset}>첫 페이지부터 조회</Button></AlertDescription></Alert> : null}
      {loading ? <div role="status"><p>저장된 주차장 목록 확인 중…</p><Skeleton className="h-10 w-full" aria-hidden="true" /></div> : null}
    </div>}
    listPlaces={false} listCount={places.length}
    listContent={<div className="public-parking-list" aria-label="일반 주차장 목록" aria-busy={loading}>
      {items?.map(item => <button key={item.id} type="button" className="place-row" aria-pressed={selected?.id === item.id} onClick={() => inspect(item)}>
        <PlaceIcon kind="public_parking_lot" /><span><strong>{item.name}</strong>
          <small>{item.road_address || item.land_address || "주소 미제공"}</small>
          <small>총 {parkingNumber(item.capacity, "면")} · {item.fee_info || "요금 미제공"}</small>
          {!hasCoordinates(item) ? <small>좌표 미등록 · 목록에서 상세 확인</small> : null}
        </span>
      </button>)}
      {!loading && !error && !items?.length ? <Empty><EmptyHeader><EmptyDescription>{data?.collection.last_success_at ? "조건에 맞는 저장 주차장이 없습니다. 이름이나 주소를 바꿔 검색해 주세요." : "완료된 주차장 기준정보가 아직 없습니다. 수집 상태에서 마지막 완료 여부를 확인해 주세요."}</EmptyDescription></EmptyHeader></Empty> : null}
      {data?.has_more && data.next_cursor ? <Button type="button" variant="outline" disabled={loading} onClick={() => setRequest(value => ({ ...value, cursor: data.next_cursor!, revision: value.revision + 1 }))}>주차장 100곳 더 불러오기</Button> : null}
    </div>} />;
}
