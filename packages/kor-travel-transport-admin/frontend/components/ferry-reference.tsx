"use client";

import { useEffect, useState } from "react";
import { transportGet, dateTime } from "@/lib/journey";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";

type ReferenceRow = {
  record_id: string; kind: "route" | "facility" | "terminal"; name: string | null;
  departure: string | null; arrival: string | null; calls: string | null; segment: string | null;
  address: string | null; telephone: string | null; source_year: string | null;
};
type ReferenceState = {
  dataset: string; title: string; last_attempt_at: string | null; last_error: string | null;
  data: null | { source: string; source_url: string; source_version: string; source_sha256: string;
    collected_at: string; items: ReferenceRow[] };
};
export type FerryReferencePayload = { items: ReferenceState[] };

export function FerryReference() {
  const [payload, setPayload] = useState<FerryReferencePayload | null>(null);
  const [query, setQuery] = useState("");
  const [error, setError] = useState(false);
  const [reload, setReload] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    transportGet<FerryReferencePayload>("transport/ferry/reference", controller.signal)
      .then((data) => { if (!controller.signal.aborted) { setPayload(data); setError(false); } })
      .catch(() => { if (!controller.signal.aborted) setError(true); });
    return () => controller.abort();
  }, [reload]);
  return <section aria-labelledby="ferry-reference-title" className="flex min-w-0 flex-col gap-4">
    <h2 id="ferry-reference-title">항로·터미널 찾아보기</h2>
    <p className="quiet">VadaHub의 여객항로·도선항로·여객선 시설과 공식 터미널 보완 자료입니다. 과거 조사자료로 현재 운항 여부나 시간표를 뜻하지 않습니다. 실제 운항편은 위 항구 검색에서 확인하세요.</p>
    <FieldGroup><Field><FieldLabel htmlFor="ferry-reference-search">항로·시설 검색</FieldLabel>
      <Input id="ferry-reference-search" type="search" placeholder="예: 제주, 목포, 터미널" value={query} onChange={(event) => setQuery(event.target.value)} />
    </Field></FieldGroup>
    <div><Button variant="outline" onClick={() => setReload((value) => value + 1)}>기준자료 다시 조회</Button></div>
    {error ? <Alert variant="destructive"><AlertDescription>기준자료를 불러오지 못했습니다. 다시 조회해 주세요.</AlertDescription></Alert> : null}
    {!payload && !error ? <Skeleton className="h-32 w-full" aria-label="배편 기준자료를 읽는 중" /> : null}
    {payload?.items.map((state) => <ReferenceDataset key={state.dataset} state={state} query={query} />)}
  </section>;
}

export function ReferenceDataset({ state, query }: { state: ReferenceState; query: string }) {
  const terms = query.trim().split(/\s+/).filter(Boolean);
  const rows = state.data?.items.filter((row) => terms.every((term) =>
    [row.name, row.departure, row.arrival, row.segment, row.calls, row.address, row.telephone, row.source_year, row.record_id].join(" ").includes(term))) ?? [];
  // 검색 조건이 바뀌면 별도 key로 페이지를 초기화한다.
  return <Card className="min-w-0">
    <CardHeader><CardTitle role="heading" aria-level={3}>{state.title}</CardTitle><CardDescription>
      {state.data ? <><p>{rows.length.toLocaleString("ko-KR")}건 · 원천 이력/기준일 {state.data.source_version}</p>
        <p>원문 수집 {dateTime(state.data.collected_at)} · 최근 확인 {state.last_attempt_at ? dateTime(state.last_attempt_at) : "미확인"}</p></> : "아직 저장된 자료가 없습니다."}
    </CardDescription></CardHeader>
    <CardContent className="min-w-0">
      {state.last_error ? <Alert><AlertDescription>최근 수집에 실패했습니다. {state.data ? "마지막 정상 저장본을 표시합니다." : "다음 정기 수집에서 다시 확인합니다."}</AlertDescription></Alert> : null}
      {state.data ? <DatasetRows key={query} rows={rows} /> : <Empty><EmptyHeader><EmptyTitle>수집 대기</EmptyTitle><EmptyDescription>자료 미확보는 항로나 시설이 없다는 뜻이 아닙니다.</EmptyDescription></EmptyHeader></Empty>}
    </CardContent>
    <CardFooter className="flex-wrap gap-2">
      {state.data ? <a href={state.data.source_url} target="_blank" rel="noreferrer">원문 출처 · {state.data.source}</a> : <span>출처별 수집 상태를 확인 중입니다.</span>}
      <span className="quiet">좌표가 확인되지 않은 자료는 지도에 표시하지 않습니다.</span>
    </CardFooter>
  </Card>;
}

function DatasetRows({ rows }: { rows: ReferenceRow[] }) {
  const [page, setPage] = useState(0);
  const last = Math.max(0, Math.ceil(rows.length / 20) - 1);
  const current = Math.min(page, last);
  if (!rows.length) return <Empty><EmptyHeader><EmptyTitle>검색 결과 없음</EmptyTitle><EmptyDescription>다른 항로명이나 시설명으로 검색해 주세요.</EmptyDescription></EmptyHeader></Empty>;
  return <div className="flex min-w-0 flex-col gap-4">
    <ul className="flex min-w-0 flex-col gap-3">
      {rows.slice(current * 20, current * 20 + 20).map((row) => <li key={row.record_id} className="min-w-0 break-words">
        <strong>{row.name || (row.departure || row.arrival ? `${row.departure ?? "출발지 미제공"} → ${row.arrival ?? "도착지 미제공"}` : `${row.kind === "route" ? "원천 항로" : "이름 미제공 시설"} ${row.record_id}`)}</strong>
        {row.kind === "route" ? <p>{row.departure ?? "출발지 미제공"} → {row.arrival ?? "도착지 미제공"}{row.segment ? ` · 구간 ${row.segment}` : ""}{row.calls ? ` · 기항 ${row.calls}` : ""}</p> : <p>{row.address ?? "주소 미제공"}{row.telephone ? ` · ${row.telephone}` : ""}{row.source_year ? ` · 조사 ${row.source_year}년` : ""}</p>}
        <small className="quiet">원천 ID {row.record_id}{row.kind === "facility" ? " · 시설 자료(승선 선착장 미확정)" : ""}</small>
      </li>)}
    </ul>
    {last > 0 ? <div className="flex flex-wrap items-center gap-2">
      <Button variant="outline" disabled={current === 0} onClick={() => setPage(current - 1)}>이전</Button>
      <span>{current + 1} / {last + 1} 페이지</span>
      <Button variant="outline" disabled={current >= last} onClick={() => setPage(current + 1)}>다음</Button>
    </div> : null}
  </div>;
}
