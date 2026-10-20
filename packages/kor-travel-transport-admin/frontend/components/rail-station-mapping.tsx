"use client";

import { useEffect, useMemo, useState } from "react";

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

function stationKey(item: Pick<Station, "operator_code" | "line_code" | "station_code">) {
  return `${item.operator_code}\u0000${item.line_code}\u0000${item.station_code}`;
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
  const candidates = useMemo(() => {
    const terms = query.trim().toLocaleLowerCase("ko-KR").split(/\s+/).filter(Boolean);
    if (!terms.length) return [];
    return places.filter((place) => {
      const text = [place.station_name, place.operator_name, place.line_name, place.station_number, place.identity_key]
        .filter(Boolean).join(" ").toLocaleLowerCase("ko-KR");
      return terms.every((term) => text.includes(term));
    }).slice(0, 8);
  }, [places, query]);

  return <section className="rail-map-editor" aria-label={`${station.station_name} 역 매핑 편집`}>
    <div className="rail-map-editor-heading">
      <div><p className="eyebrow">KRIC 역 코드</p><h2>{station.station_name}</h2></div>
      <span className={`rail-map-badge ${station.match_method === "unmatched" ? "is-unmatched" : ""}`}>
        {station.match_method === "manual" ? "수동 연결" : station.match_method === "unmatched" ? "미연결" : "자동 연결"}
      </span>
    </div>
    <dl className="rail-map-code-grid">
      <div><dt>운영기관</dt><dd>{station.operator_name} · {station.operator_code}</dd></div>
      <div><dt>노선</dt><dd>{station.line_name} · {station.line_code}</dd></div>
      <div><dt>역 코드</dt><dd>{station.station_code}</dd></div>
    </dl>
    <div className="rail-map-current" aria-live="polite">
      <span>현재 연결</span>
      {currentPlace ? <strong>{currentPlace.station_name} · {currentPlace.line_name ?? "노선 미상"} · {currentPlace.operator_name ?? "운영기관 미상"}</strong> : <strong>연결된 역이 없습니다.</strong>}
    </div>
    <label className="rail-map-search-label" htmlFor="rail-place-search">연결할 KRIC 기준 역 검색</label>
    <input id="rail-place-search" type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="역명, 노선, 운영기관, 역 번호" autoComplete="off" />
    {query.trim() ? <div className="rail-map-candidates" role="listbox" aria-label="역 검색 결과">
      {candidates.length ? candidates.map((place) => <button key={place.identity_key} type="button" role="option" aria-selected={target === place.identity_key}
        className={target === place.identity_key ? "is-selected" : ""} onClick={() => setTarget(place.identity_key)}>
        <strong>{place.station_name ?? "이름 미상"}</strong><span>{[place.line_name, place.operator_name, place.station_number && `역 번호 ${place.station_number}`].filter(Boolean).join(" · ")}</span>
      </button>) : <p>일치하는 기준 역이 없습니다.</p>}
    </div> : <p className="quiet">역명만 다른 경우에도 KRIC 역 번호와 기준정보를 확인해 연결합니다.</p>}
    {target ? <label className="rail-map-note">수동 연결 근거 <input value={note} maxLength={500} onChange={(event) => setNote(event.target.value)} placeholder="예: 역 번호와 운영기관 자료 대조" /></label> : null}
    <div className="rail-map-actions">
      <button className="button" type="button" disabled={!target || saving || (target === station.rail_station_identity_key && manualMapping?.note === note)}
        onClick={() => void onSave(target, note)}>{saving ? "저장 중…" : manualMapping ? "수동 매핑 저장" : "수동으로 연결"}</button>
      {manualMapping ? <button className="secondary" type="button" disabled={saving} onClick={() => void onSave(null, "")}>수동 연결 해제</button> : null}
    </div>
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

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError("");
    fetch("/api/admin/rail-station-mappings", { cache: "no-store", signal: controller.signal })
      .then(async (response) => { if (!response.ok) throw new Error(await responseError(response)); return response.json() as Promise<MappingDocument>; })
      .then((value) => { if (!controller.signal.aborted) { setData(value); setError(""); } })
      .catch((reason: unknown) => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "역 목록을 불러오지 못했습니다."); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
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

  const selected = data?.stations.find((station) => stationKey(station) === selectedKey) ?? filtered[0];
  const currentPlace = selected?.rail_station_identity_key ? data?.places.find((place) => place.identity_key === selected.rail_station_identity_key) : undefined;
  const manualMapping = selected ? data?.mappings.find((item) => stationKey(item) === stationKey(selected)) : undefined;

  async function save(target: string | null, note: string) {
    if (!data || !selected) return;
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
    const body = JSON.stringify({ schema_version: data.schema_version, exported_at: new Date().toISOString(),
      catalog_sha256: data.catalog_sha256, stations: data.stations, manual_mappings: data.mappings }, null, 2);
    const url = URL.createObjectURL(new Blob([body], { type: "application/json" }));
    const anchor = document.createElement("a"); anchor.href = url; anchor.download = "kric-rail-station-mappings.json"; anchor.click();
    URL.revokeObjectURL(url);
  }

  return <section className="rail-map-workbench" data-slot="rail-station-mapping">
    <div className="rail-map-toolbar">
      <div><p className="eyebrow">KRIC · 역 코드 카탈로그</p><p className="quiet">최근 확인 {formatDate(data?.catalog_updated_at ?? null)} · 지문 {data?.catalog_sha256?.slice(0, 12) ?? "—"}</p></div>
      <div className="rail-map-toolbar-actions">
        <button className="secondary" type="button" disabled={loading} onClick={() => setReload((value) => value + 1)}>새로고침</button>
        <button className="secondary" type="button" disabled={!data} onClick={exportJson}>JSON 내보내기</button>
      </div>
    </div>
    {data ? <div className="rail-map-metrics" aria-label="역 매핑 요약">
      <div><span>전체 역</span><strong>{data.station_count.toLocaleString("ko-KR")}</strong></div>
      <div><span>자동 연결</span><strong>{data.automatic_mapped_count.toLocaleString("ko-KR")}</strong></div>
      <div><span>수동 연결</span><strong>{data.manual_mapped_count.toLocaleString("ko-KR")}</strong></div>
      <div><span>미연결</span><strong>{data.unmatched_count.toLocaleString("ko-KR")}</strong></div>
    </div> : null}
    {loading && !data ? <p className="loading" role="status">KRIC 역 코드와 매핑을 불러오는 중입니다…</p> : null}
    {error ? <p className="error" role="alert">{error}</p> : null}
    {notice ? <p className="rail-map-notice" role="status">{notice}</p> : null}
    {data ? <div className="rail-map-layout">
      <section className="rail-map-list" aria-label="KRIC 역 목록">
        <div className="rail-map-list-tools">
          <label htmlFor="rail-station-filter">역명·운영기관·노선·코드 검색</label>
          <input id="rail-station-filter" type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="예: 서울역, 공항철도, A01" />
          <label className="rail-map-checkbox"><input type="checkbox" checked={unmatchedOnly} onChange={(event) => setUnmatchedOnly(event.target.checked)} /> 미연결 우선 보기</label>
          <p className="quiet">{filtered.length.toLocaleString("ko-KR")}개 결과 · 목록 최대 100개 표시</p>
        </div>
        <div className="rail-map-station-list" role="listbox" aria-label="역 선택">
          {filtered.slice(0, 100).map((station) => <button key={stationKey(station)} type="button" role="option"
            aria-selected={selected ? stationKey(selected) === stationKey(station) : false}
            className={selected && stationKey(selected) === stationKey(station) ? "is-selected" : ""}
            onClick={() => setSelectedKey(stationKey(station))}>
            <span><strong>{station.station_name}</strong><small>{station.line_name} · {station.operator_name}</small></span>
            <span className={`rail-map-dot ${station.match_method === "unmatched" ? "is-unmatched" : ""}`} aria-label={station.match_method === "unmatched" ? "미연결" : "연결됨"} />
          </button>)}
          {!filtered.length ? <p className="quiet">조건에 맞는 역이 없습니다.</p> : null}
        </div>
      </section>
      {selected ? <StationEditor key={`${stationKey(selected)}:${data.revision}`} station={selected} currentPlace={currentPlace}
        manualMapping={manualMapping} places={data.places} saving={saving} onSave={save} /> : <div className="rail-map-editor"><p className="quiet">연결할 역을 선택해 주세요.</p></div>}
    </div> : null}
  </section>;
}
