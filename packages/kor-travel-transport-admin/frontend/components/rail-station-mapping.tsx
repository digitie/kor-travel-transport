"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { DetailList } from "@/components/detail-list";
import { FilterField } from "@/components/filter-bar";
import { StatStrip } from "@/components/stat-strip";
import { SectionCard } from "@/components/section-card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type Station = {
  operator_code: string; operator_name: string; line_code: string; line_name: string;
  station_code: string; station_name: string; rail_station_id: number | null;
  rail_station_identity_key: string | null;
  match_method: "manual" | "exact_identity" | "station_number_and_name" | "unmatched";
};
type Place = { id: number; identity_key: string; operator_name: string | null; line_name: string | null; station_number: string | null; station_name: string | null };
type ManualMapping = { operator_code: string; line_code: string; station_code: string; rail_station_identity_key: string; note: string };
type MappingDocument = {
  schema_version: 1; revision: string; catalog_sha256: string | null;
  catalog_updated_at: string | null; mappings_updated_at: string | null;
  station_count: number; mapped_count: number; automatic_mapped_count: number;
  manual_mapped_count: number; unmatched_count: number;
  stations: Station[]; places: Place[]; mappings: ManualMapping[];
};
const resultButton = "flex min-w-0 flex-col items-start gap-0.5 rounded-control border border-border bg-card px-3 py-2 text-left hover:bg-surface-subtle aria-selected:border-brand aria-selected:bg-brand-tint focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";
const stationButton = "flex w-full min-w-0 items-center justify-between gap-3 rounded-control border border-transparent px-3 py-2 text-left hover:bg-surface-subtle aria-selected:border-brand aria-selected:bg-brand-tint focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";

function stationKey(item: Pick<Station, "operator_code" | "line_code" | "station_code">) {
  return JSON.stringify([item.operator_code, item.line_code, item.station_code]);
}
function formatDate(value: string | null) {
  return value ? new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Seoul" }).format(new Date(value)) : "아직 수집 전";
}
async function responseError(response: Response) {
  try { const body = await response.json() as { detail?: string }; return body.detail ?? `요청에 실패했습니다 (${response.status}).`; }
  catch { return `요청에 실패했습니다 (${response.status}).`; }
}

function StationEditor({
  station, currentPlace, manualMapping, places, saving, onSave,
}: {
  station: Station; currentPlace: Place | undefined; manualMapping: ManualMapping | undefined;
  places: Place[]; saving: boolean; onSave: (target: string | null, note: string) => Promise<void>;
}) {
  const [query, setQuery] = useState("");
  const [target, setTarget] = useState(station.rail_station_identity_key ?? "");
  const [note, setNote] = useState(manualMapping?.note ?? "");
  useEffect(() => {
    // 선택 역 또는 저장된 연결이 바뀌면 편집 초안을 해당 서버 값으로 복원한다.
    setTarget(station.rail_station_identity_key ?? "");
    setNote(manualMapping?.note ?? "");
  }, [station.operator_code, station.line_code, station.station_code,
    station.rail_station_identity_key, manualMapping?.note]);
  const candidates = useMemo(() => {
    const terms = query.trim().toLocaleLowerCase("ko-KR").split(/\s+/).filter(Boolean);
    if (!terms.length) return [];
    return places.filter((place) => {
      const text = [place.station_name, place.operator_name, place.line_name, place.station_number, place.identity_key]
        .filter(Boolean).join(" ").toLocaleLowerCase("ko-KR");
      return terms.every((term) => text.includes(term));
    }).slice(0, 8);
  }, [places, query]);

  return <section aria-label={`${station.station_name} 역 매핑 편집`} className="min-w-0">
    <SectionCard
      title={station.station_name}
      description="KRIC 역 코드"
      actions={<Badge className="rail-map-badge" variant={station.match_method === "unmatched" ? "warning" : station.match_method === "manual" ? "info" : "success"}>
        {station.match_method === "manual" ? "수동 연결" : station.match_method === "unmatched" ? "미연결" : "자동 연결"}
      </Badge>}
    >
      <DetailList columns="auto" items={[
        { label: "운영기관", value: `${station.operator_name} · ${station.operator_code}` },
        { label: "노선", value: `${station.line_name} · ${station.line_code}` },
        { label: "역 코드", value: station.station_code, mono: true },
      ]} />
      <div className="flex flex-col gap-1 text-sm" aria-live="polite">
        <span className="text-xs font-medium text-text-secondary">현재 연결</span>
        {currentPlace ? <strong>{currentPlace.station_name} · {currentPlace.line_name ?? "노선 미상"} · {currentPlace.operator_name ?? "운영기관 미상"}</strong> : <strong>연결된 역이 없습니다.</strong>}
      </div>
      <FilterField label="연결할 KRIC 기준 역 검색" htmlFor="rail-place-search">
        <Input id="rail-place-search" type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="역명, 노선, 운영기관, 역 번호" autoComplete="off" />
      </FilterField>
      {query.trim() ? <div className="grid gap-2 sm:grid-cols-2" role="listbox" aria-label="역 검색 결과">
        {candidates.length ? candidates.map((place) => <button key={place.identity_key} type="button" role="option" aria-selected={target === place.identity_key} className={resultButton} onClick={() => setTarget(place.identity_key)}>
          <strong className="text-sm">{place.station_name ?? "이름 미상"}</strong><span className="text-xs text-text-secondary">{[place.line_name, place.operator_name, place.station_number && `역 번호 ${place.station_number}`].filter(Boolean).join(" · ")}</span>
        </button>) : <p className="text-sm text-text-secondary">일치하는 기준 역이 없습니다.</p>}
      </div> : <p className="text-sm text-text-secondary">역명만 다른 경우에도 KRIC 역 번호와 기준정보를 확인해 연결합니다.</p>}
      {target ? <FilterField label="수동 연결 근거"><Input value={note} maxLength={500} onChange={(event) => setNote(event.target.value)} placeholder="예: 역 번호와 운영기관 자료 대조" /></FilterField> : null}
      <div className="flex flex-wrap gap-2">
        <Button type="button" disabled={!target || saving || (target === station.rail_station_identity_key && manualMapping?.note === note)}
          onClick={() => void onSave(target, note)}>{saving ? "저장 중…" : manualMapping ? "수동 매핑 저장" : "수동으로 연결"}</Button>
        {manualMapping ? <Button type="button" variant="outline" disabled={saving} onClick={() => void onSave(null, "")}>수동 연결 해제</Button> : null}
      </div>
    </SectionCard>
  </section>;
}

export function RailStationMapping() {
  const [data, setData] = useState<MappingDocument | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [query, setQuery] = useState("");
  const [unmatchedOnly, setUnmatchedOnly] = useState(true);
  const [selectedKey, setSelectedKey] = useState("");
  const [reload, setReload] = useState(0);
  const requestSequence = useRef(0);
  const noticeRef = useRef<HTMLParagraphElement>(null);

  useEffect(() => {
    if (notice) noticeRef.current?.focus();
  }, [notice]);

  useEffect(() => {
    const controller = new AbortController();
    const requestId = ++requestSequence.current;
    // 새 서버 조회마다 대기/오류 상태를 초기화한다.
    setLoading(true); setError("");
    fetch("/api/admin/rail-station-mappings", { cache: "no-store", signal: controller.signal })
      .then(async (response) => { if (!response.ok) throw new Error(await responseError(response)); return response.json() as Promise<MappingDocument>; })
      .then((value) => { if (!controller.signal.aborted && requestSequence.current === requestId) { setData(value); setError(""); } })
      .catch((reason: unknown) => { if (!controller.signal.aborted && requestSequence.current === requestId) setError(reason instanceof Error ? reason.message : "역 목록을 불러오지 못했습니다."); })
      .finally(() => { if (!controller.signal.aborted && requestSequence.current === requestId) setLoading(false); });
    return () => controller.abort();
  }, [reload]);

  const filtered = useMemo(() => {
    if (!data) return [];
    const terms = query.trim().toLocaleLowerCase("ko-KR").split(/\s+/).filter(Boolean);
    const placesByIdentity = new Map(data.places.map((place) => [place.identity_key, place]));
    return data.stations.filter((station) => {
      if (unmatchedOnly && station.match_method !== "unmatched") return false;
      const place = station.rail_station_identity_key ? placesByIdentity.get(station.rail_station_identity_key) : undefined;
      const text = [station.operator_name, station.operator_code, station.line_name, station.line_code,
        station.station_name, station.station_code, place?.station_name, place?.line_name].filter(Boolean).join(" ").toLocaleLowerCase("ko-KR");
      return terms.every((term) => text.includes(term));
    });
  }, [data, query, unmatchedOnly]);

  const visibleStations = useMemo(() => filtered.slice(0, 100), [filtered]);

  useEffect(() => {
    if (visibleStations.some((station) => stationKey(station) === selectedKey)) return;
    // 필터로 선택 행이 사라지면 실제 보이는 첫 행으로 상세 대상을 맞춘다.
    setSelectedKey(visibleStations[0] ? stationKey(visibleStations[0]) : "");
  }, [visibleStations, selectedKey]);

  const selected = visibleStations.find((station) => stationKey(station) === selectedKey) ?? visibleStations[0];
  const currentPlace = selected?.rail_station_identity_key ? data?.places.find((place) => place.identity_key === selected.rail_station_identity_key) : undefined;
  const manualMapping = selected ? data?.mappings.find((item) => stationKey(item) === stationKey(selected)) : undefined;

  async function save(target: string | null, note: string) {
    if (!data || !selected) return;
    setSelectedKey(stationKey(selected));
    // 진행 중인 GET이 저장 응답보다 늦게 도착해 새 revision을 덮지 않게 무효화한다.
    requestSequence.current += 1;
    setLoading(false);
    setSaving(true); setError(""); setNotice("");
    const mappings = data.mappings.filter((item) => stationKey(item) !== stationKey(selected));
    if (target) mappings.push({ operator_code: selected.operator_code, line_code: selected.line_code,
      station_code: selected.station_code, rail_station_identity_key: target, note });
    try {
      const response = await fetch("/api/admin/rail-station-mappings", { method: "POST", cache: "no-store",
        headers: { "content-type": "application/json" }, body: JSON.stringify({ expected_revision: data.revision, mappings }) });
      if (!response.ok) throw new Error(await responseError(response));
      const updated = await response.json() as MappingDocument;
      setData(updated);
      setNotice(target ? "수동 매핑을 저장했습니다." : "수동 매핑을 해제했습니다. 자동 기준과 다시 대조합니다.");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "역 매핑을 저장하지 못했습니다."); }
    finally { setSaving(false); }
  }

  function exportJson() {
    if (!data) return;
    const { mappings, ...catalog } = data;
    const body = JSON.stringify({ ...catalog, exported_at: new Date().toISOString(), manual_mappings: mappings }, null, 2);
    const url = URL.createObjectURL(new Blob([body], { type: "application/json" }));
    const anchor = document.createElement("a"); anchor.href = url; anchor.download = "kric-rail-station-mappings.json"; anchor.click();
    URL.revokeObjectURL(url);
  }

  return <section className="flex flex-col gap-6" data-slot="rail-station-mapping">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="flex flex-col gap-1"><p className="text-xs font-medium text-text-secondary">KRIC · 역 코드 카탈로그</p><p className="text-sm text-text-secondary">최근 확인 {formatDate(data?.catalog_updated_at ?? null)} · 지문 {data?.catalog_sha256?.slice(0, 12) ?? "—"}</p></div>
      <div className="flex flex-wrap gap-2">
        <Button type="button" variant="outline" disabled={loading || saving} onClick={() => setReload((value) => value + 1)}>새로고침</Button>
        <Button type="button" variant="outline" disabled={!data} onClick={exportJson}>JSON 내보내기</Button>
      </div>
    </div>
    {data ? <div className="rail-map-metrics rounded-panel border border-border bg-card p-4">
      <StatStrip ariaLabel="역 매핑 요약" items={[
        { label: "전체 역", value: data.station_count.toLocaleString("ko-KR") },
        { label: "자동 연결", value: data.automatic_mapped_count.toLocaleString("ko-KR") },
        { label: "수동 연결", value: data.manual_mapped_count.toLocaleString("ko-KR") },
        { label: "미연결", value: data.unmatched_count.toLocaleString("ko-KR") },
      ]} />
    </div> : null}
    {loading && !data ? <p role="status" className="text-sm text-text-secondary">KRIC 역 코드와 매핑을 불러오는 중입니다…</p> : null}
    {error ? <p className="text-sm text-destructive" role="alert">{error}</p> : null}
    {notice ? <p className="text-sm text-text-primary" role="status" tabIndex={-1} ref={noticeRef}>{notice}</p> : null}
    {data ? <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
      <section aria-label="KRIC 역 목록" className="min-w-0">
        <SectionCard title="KRIC 역 목록" description={`${filtered.length.toLocaleString("ko-KR")}개 결과 · 목록 최대 100개 표시`}>
          <div className="grid gap-3">
            <FilterField label="역명·운영기관·노선·코드 검색" htmlFor="rail-station-filter">
              <Input id="rail-station-filter" type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="예: 서울역, 공항철도, A01" />
            </FilterField>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" className="size-4 accent-brand" checked={unmatchedOnly} onChange={(event) => setUnmatchedOnly(event.target.checked)} /> 미연결 우선 보기</label>
          </div>
          <div className="grid max-h-[32rem] gap-1 overflow-y-auto" role="listbox" aria-label="역 선택">
            {visibleStations.map((station) => <button key={stationKey(station)} type="button" role="option"
              aria-selected={selected ? stationKey(selected) === stationKey(station) : false}
              className={stationButton}
              onClick={() => setSelectedKey(stationKey(station))}>
              <span className="flex min-w-0 flex-col"><strong className="truncate text-sm">{station.station_name}</strong><small className="truncate text-xs text-text-secondary">{station.line_name} · {station.operator_name}</small></span>
              <span className={`size-2.5 shrink-0 rounded-full ${station.match_method === "unmatched" ? "bg-warning" : "bg-success"}`} aria-label={station.match_method === "unmatched" ? "미연결" : "연결됨"} />
            </button>)}
            {!filtered.length ? <p className="text-sm text-text-secondary">조건에 맞는 역이 없습니다.</p> : null}
          </div>
        </SectionCard>
      </section>
      {selected ? <StationEditor key={stationKey(selected)} station={selected} currentPlace={currentPlace}
        manualMapping={manualMapping} places={data.places} saving={saving} onSave={save} /> : <section aria-label="역 매핑 편집" className="rounded-panel border border-border bg-card p-4"><p className="text-sm text-text-secondary">연결할 역을 선택해 주세요.</p></section>}
    </div> : null}
  </section>;
}
