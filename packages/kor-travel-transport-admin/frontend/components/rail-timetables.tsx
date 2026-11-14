"use client";

import { useEffect, useState } from "react";
import { dateTime, serviceTime, transportGet } from "@/lib/journey";
import { EmptyState } from "@/components/empty-state";
import { FilterActions, FilterBar, FilterField } from "@/components/filter-bar";
import { InfoButton } from "./info-button";
import { SectionCard } from "./section-card";
import { Alert, AlertDescription } from "./ui/alert";
import { Button } from "./ui/button";
import { NativeSelect } from "./ui/native-select";
import { NativeSelectOption } from "./ui/native-select-option";

type Departure = { train_number: string | null; departure_time: string | null; arrival_time: string | null; origin_name: string | null; destination_name: string | null };
type Table = { place_id: number; station_name: string; line_name: string | null; status: "unlinked" | "day_unresolved" | "not_collected" | "stored"; collected_at: string | null; stale: boolean; next_departure: Departure | null; upcoming_departures?: Departure[]; items: Departure[] };
type Response = { generated_at: string; day_code: "7" | "8" | "9" | null; basis: "calendar" | "selected_period" | "calendar_unavailable" | "overnight_unresolved"; items: Table[] };
const dayNames = { "7": "토요일", "8": "평일", "9": "휴일" };
const departureRow = "departure-row grid gap-3 border-b border-border py-3 last:border-b-0 sm:grid-cols-[8rem_minmax(0,1fr)_minmax(0,1fr)] sm:items-center";
const caveat = "rounded-control border border-warning bg-warning-tint px-3 py-2 text-sm text-text-primary";
function railTime(value: string | null) {
  const formatted = serviceTime(value);
  return formatted === "시각 확인 필요" ? `${formatted} (${value})` : formatted;
}

export function RailTimetables({ placeIds }: { placeIds: number[] }) {
  const ids = placeIds.join(",");
  const [period, setPeriod] = useState("");
  const [reload, setReload] = useState(0);
  const [state, setState] = useState<{ key: string; selection: string; data?: Response; error?: boolean }>({ key: "", selection: "" });
  const selection = `${ids}/${period}`;
  const key = `${selection}/${reload}`;
  useEffect(() => {
    if (!ids) return;
    const controller = new AbortController();
    const params = new URLSearchParams({ place_ids: ids });
    if (period) params.set("day_code", period);
    transportGet<Response>(`transport/rail/timetables?${params}`, controller.signal)
      .then((data) => { if (!controller.signal.aborted) setState({ key, selection, data }); })
      .catch(() => { if (!controller.signal.aborted) setState((previous) => ({ key, selection, error: true, data: previous.selection === selection ? previous.data : undefined })); });
    return () => controller.abort();
  }, [ids, period, selection, key]);
  // 다음 예정은 저장 시간표를 현재 시각과 비교한 값이다. 외부 KRIC 호출은 발생하지 않는다.
  useEffect(() => {
    const timer = setInterval(() => { if (document.visibilityState === "visible") setReload((value) => value + 1); }, 60_000);
    return () => clearInterval(timer);
  }, []);
  if (!ids) return null;
  const current = state.selection === selection ? state : null;
  const pending = current?.key !== key;
  const data = current?.data;
  return <section aria-label="도시철도 예정 시간표" aria-busy={pending} className="flex flex-col gap-4">
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div className="flex items-center gap-2"><h3 className="text-sm font-semibold text-text-primary">예정 시간표</h3><InfoButton label="예정 시간표">KRIC 제공 예정 시각입니다. 실시간 도착·변경·지연 정보는 반영되지 않을 수 있습니다. 오늘 기준으로 확인 가능한 이후 출발부터 표시합니다.</InfoButton></div>
      <FilterBar>
        <FilterField label="시간표 기준"><NativeSelect value={period} onChange={(event) => setPeriod(event.target.value)}><NativeSelectOption value="">오늘 · 공휴일 확인</NativeSelectOption><NativeSelectOption value="8">평일</NativeSelectOption><NativeSelectOption value="7">토요일</NativeSelectOption><NativeSelectOption value="9">휴일</NativeSelectOption></NativeSelect></FilterField>
        <FilterActions><Button type="button" variant="outline" disabled={pending} onClick={() => setReload((value) => value + 1)}>시간표 새로고침</Button></FilterActions>
      </FilterBar>
    </div>
    {pending ? <p role="status" className="text-sm text-text-secondary">{data ? "최신 예정 시각을 확인하는 중입니다…" : "저장된 예정 시간표를 확인하는 중입니다…"}</p> : null}
    {current?.error && !pending ? <Alert variant="destructive"><AlertDescription>{data ? "최신 조회에 실패해 이전 저장 조회 결과를 표시합니다. 다음 예정 시각은 다시 확인해 주세요." : "시간표를 불러오지 못했습니다. 시간표 새로고침으로 다시 확인해 주세요."}</AlertDescription></Alert> : null}
    {data?.basis === "calendar_unavailable" ? <p className={caveat}>공휴일을 확인하지 못했습니다. 평일·토요일·휴일을 직접 선택해 저장 시간표를 확인해 주세요.</p> : null}
    {data?.basis === "overnight_unresolved" ? <p className={caveat}>새벽 운행일은 확인이 필요합니다. 평일·토요일·휴일 시간표를 선택해 참고해 주세요.</p> : null}
    {data?.items.map((table) => <section key={table.place_id} aria-label={`${table.station_name} 예정 출발`}>
      <SectionCard headingLevel={3} title={`${table.station_name} · ${table.line_name}`} description={`${data.day_code ? dayNames[data.day_code] : "운행일 미확정"} 기준`}>
        {table.status === "unlinked" ? <EmptyState size="sm" title="공식 역사 코드와 위치 정보가 아직 연결되지 않았습니다. 역명만으로 시간표를 추정하지 않습니다." /> : table.status === "day_unresolved" ? <EmptyState size="sm" title="운행일 기준을 결정하지 못해 저장본을 선택할 수 없습니다. 위에서 요일을 선택해 주세요." /> : table.status === "not_collected" ? <EmptyState size="sm" title="선택한 기준의 저장 시간표가 아직 없습니다. 운행편이 없다는 뜻은 아닙니다." /> : <>
          {table.stale ? <p className={caveat}>48시간이 지난 저장본입니다. 다음 열차로 표시하지 않으며 아래 계획 시간표만 제공합니다.</p> : null}
          {!pending && !current?.error ? table.next_departure ? <div className={departureRow}><strong className="text-sm tabular-nums">다음 예정 {railTime(table.next_departure.departure_time)}</strong><span className="text-sm text-text-secondary">{table.next_departure.destination_name ? `${table.next_departure.destination_name}행` : "행선지 미제공"}</span><span className="text-sm text-text-secondary">{table.next_departure.train_number} 열차</span></div> : data.basis === "calendar" && !table.stale && table.items.length ? <p className="text-sm text-text-secondary">지금 이후의 당일 예정 시각이 확인되지 않습니다. 막차 운행 여부는 운영기관에 확인해 주세요.</p> : null : null}
          {!pending && !current?.error && data.basis === "calendar" && !table.stale && (table.upcoming_departures?.length ?? 0) > 1 ? <div aria-label="지금 이후 예정 출발" className="grid">{table.upcoming_departures!.slice(1).map((row) => <article className={departureRow} key={`${row.train_number}/${row.departure_time}/${row.destination_name}`}><strong className="text-sm tabular-nums">{railTime(row.departure_time)}</strong><span className="text-sm text-text-secondary">{row.destination_name ? `${row.destination_name}행` : "행선지 미제공"}</span><small className="text-xs text-text-secondary">{row.train_number ?? "열차번호 미제공"}</small></article>)}</div> : null}
          {!table.items.length ? <EmptyState size="sm" title="제공기관의 마지막 정상 응답에 시간표가 없습니다. 운행 중단을 의미하지 않습니다." /> : <details className="rounded-control border border-border px-4 py-3"><summary className="cursor-pointer text-sm font-medium text-text-primary">전체 예정 시간표 {table.items.length}편</summary><div className="mt-3 grid">{table.items.map((row) => <article className={departureRow} key={`${row.train_number}/${row.departure_time}/${row.destination_name}`}><div className="flex flex-col gap-0.5"><strong className="text-sm tabular-nums">{railTime(row.departure_time)}</strong><span className="text-xs text-text-secondary">{row.train_number ?? "열차번호 미제공"}</span></div><div className="flex flex-col gap-0.5"><strong className="text-sm">{row.destination_name ? `${row.destination_name}행` : "행선지 미제공"}</strong><small className="text-xs text-text-secondary">{row.origin_name ? `${row.origin_name} 출발 열차` : "기점 미제공"}</small></div></article>)}</div></details>}
          <p className="text-xs text-text-secondary">저장 시각 {dateTime(table.collected_at)}</p>
        </>}
      </SectionCard>
    </section>)}
    {data ? <p className="text-sm text-text-secondary">조회 {dateTime(data.generated_at)}</p> : null}
  </section>;
}
