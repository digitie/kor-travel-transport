"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Dialog } from "@base-ui/react/dialog";
import { InfoButton } from "./info-button";
import { applyAutomaticMappings, MappingRequestError, previewAutomaticMappings, readMappings, saveMappings,
  type AutomaticMappingPreview, type MappingCode, type MappingDocument, type MappingPlace as Place,
  type MappingStation as Station, type ManualMapping } from "@/lib/rail-station-mappings";

function stationKey(item: Pick<Station, "operator_code" | "line_code" | "station_code">) {
  return JSON.stringify([item.operator_code, item.line_code, item.station_code]);
}
function formatDate(value: string | null) {
  return value ? new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Seoul" }).format(new Date(value)) : "아직 수집 전";
}

function StationEditor({
  station, currentPlace, manualMapping, places, saving, readOnly, busy, onSave, onDirtyChange, onDiscard,
}: {
  station: Station; currentPlace: Place | undefined; manualMapping: ManualMapping | undefined;
  places: Place[]; saving: boolean; readOnly: boolean; busy: boolean;
  onSave: (target: string | null, note: string) => Promise<void>; onDirtyChange: (dirty: boolean) => void; onDiscard: () => void;
}) {
  const [query, setQuery] = useState("");
  const [target, setTarget] = useState(station.rail_station_identity_key ?? "");
  const [note, setNote] = useState(manualMapping?.note ?? "");
  const dirty = target !== (station.rail_station_identity_key ?? "") || note !== (manualMapping?.note ?? "");
  useEffect(() => { onDirtyChange(dirty); return () => onDirtyChange(false); }, [dirty, onDirtyChange]);
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
    <input id="rail-place-search" type="search" disabled={readOnly} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="역명, 노선, 운영기관, 역 번호" autoComplete="off" />
    {query.trim() ? <div className="rail-map-candidates" role="listbox" aria-label="역 검색 결과">
      {candidates.length ? candidates.map((place) => <button key={place.identity_key} type="button" role="option" aria-selected={target === place.identity_key}
        className={target === place.identity_key ? "is-selected" : ""} disabled={readOnly} onClick={() => setTarget(place.identity_key)}>
        <strong>{place.station_name ?? "이름 미상"}</strong><span>{[place.line_name, place.operator_name, place.station_number && `역 번호 ${place.station_number}`].filter(Boolean).join(" · ")}</span>
      </button>) : <p>일치하는 기준 역이 없습니다.</p>}
    </div> : <p className="quiet">역명만 다른 경우에도 KRIC 역 번호와 기준정보를 확인해 연결합니다.</p>}
    {target ? <label className="rail-map-note">수동 연결 근거 <input disabled={readOnly} value={note} maxLength={500} onChange={(event) => setNote(event.target.value)} placeholder="예: 역 번호와 운영기관 자료 대조" /></label> : null}
    <div className="rail-map-actions">
      <button className="button" type="button" disabled={!target || readOnly || (target === station.rail_station_identity_key && manualMapping?.note === note)}
        onClick={() => void onSave(target, note)}>{saving ? "저장 중…" : manualMapping ? "수동 매핑 저장" : "수동으로 연결"}</button>
      {manualMapping ? <button className="secondary" type="button" disabled={readOnly} onClick={() => void onSave(null, "")}>수동 연결 해제</button> : null}
      {dirty ? <button className="secondary" type="button" disabled={busy} onClick={onDiscard}>초안 취소 후 새로고침</button> : null}
    </div>
  </section>;
}

function AutomaticPreviewContent({ preview }: { preview: AutomaticMappingPreview }) {
  const codeText = (code: MappingCode) => [code.operator_code, code.line_code, code.station_code].join(" / ");
  const labels = { added: "연결 추가", removed: "연결 해제", retargeted: "대상 변경", method_changed: "연결 기준 변경" };
  const methods = { manual: "수동 연결", exact_identity: "기준정보 일치", station_number_and_name: "역 번호·이름 일치", unmatched: "미연결" };
  return <>
    <table className="w-full text-sm" aria-label="연결 변경 건수"><thead><tr><th className="text-left">공식 역 코드 기준</th><th>현재 → 적용 후</th></tr></thead><tbody>
      {([ ["전체 역", "station_count"], ["연결", "mapped_count"], ["자동 연결", "automatic_mapped_count"], ["수동 연결", "manual_mapped_count"], ["미연결", "unmatched_count"] ] as const).map(([label, key]) => <tr key={key}><th className="text-left font-normal">{label}</th><td className="text-center">{preview.before[key].toLocaleString("ko-KR")} → {preview.after[key].toLocaleString("ko-KR")}</td></tr>)}
    </tbody></table>
    {preview.has_changes && !preview.changes.length ? <p>연결 대상 변경 없이 자동 후보를 갱신합니다.</p> : null}
    {preview.has_changes && preview.changes.length ? <section aria-label="변경할 연결"><h3>변경 {preview.changes.length.toLocaleString("ko-KR")}건</h3><ul className="flex flex-col gap-2">
      {preview.changes.map(change => <li key={stationKey(change)} className="break-words"><strong>{change.station_name} · {change.line_name}</strong><small className="block">{change.operator_name} · {codeText(change)} · {labels[change.change_type]}</small><span className="block break-all">{change.before.rail_station_identity_key ?? "미연결"} → {change.after.rail_station_identity_key ?? "미연결"}</span>{change.change_type === "method_changed" ? <small>{methods[change.before.match_method]} → {methods[change.after.match_method]}</small> : null}</li>)}
    </ul></section> : !preview.has_changes ? <p>변경할 연결이 없습니다.</p> : null}
    {preview.manual_conflicts.length ? <section aria-label="수동 연결 충돌"><h3>수동 충돌 {preview.manual_conflicts.length.toLocaleString("ko-KR")}건</h3><ul className="flex flex-col gap-2">{preview.manual_conflicts.map(item => <li key={stationKey(item)} className="break-all">{codeText(item)} · {item.reason === "manual_target_reserved" ? "수동 대상 예약" : "수동 코드 우선"}<small className="block">{item.rail_station_identity_key} · 수동 코드 {codeText(item.reserved_by)}</small></li>)}</ul></section> : null}
    {preview.blockers.length ? <section aria-label="적용 차단 사유"><h3>적용 차단</h3><ul>{preview.blockers.map((item, index) => <li key={index} className="break-words">{item.message}{item.station_code ? ` · ${[item.operator_code, item.line_code, item.station_code].filter(Boolean).join(" / ")}` : ""}</li>)}</ul></section> : null}
  </>;
}

export function RailStationMapping() {
  const [data, setData] = useState<MappingDocument | null>(null);
  const [loading, setLoading] = useState(true);
  const [documentReady, setDocumentReady] = useState(false);
  const [editorReset, setEditorReset] = useState(0);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [query, setQuery] = useState("");
  const [unmatchedOnly, setUnmatchedOnly] = useState(true);
  const [selectedKey, setSelectedKey] = useState("");
  const [reload, setReload] = useState(0);
  const [dirty, setDirty] = useState(false);
  const [automaticOpen, setAutomaticOpen] = useState(false);
  const [preview, setPreview] = useState<AutomaticMappingPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [automaticError, setAutomaticError] = useState("");
  const [applying, setApplying] = useState(false);
  const requestSequence = useRef(0);
  const previewSequence = useRef(0);
  const documentRequest = useRef<AbortController | null>(null);
  const previewRequest = useRef<AbortController | null>(null);
  const mutationRequest = useRef<AbortController | null>(null);
  const automaticTrigger = useRef<HTMLButtonElement>(null);
  const noticeRef = useRef<HTMLParagraphElement>(null);
  const workbenchRef = useRef<HTMLElement>(null);

  useEffect(() => () => { documentRequest.current?.abort(); previewRequest.current?.abort(); mutationRequest.current?.abort(); }, []);

  useEffect(() => {
    if (notice) noticeRef.current?.focus();
  }, [notice]);

  useEffect(() => {
    const controller = new AbortController();
    documentRequest.current = controller;
    const requestId = ++requestSequence.current;
    // 새 서버 조회마다 대기/오류 상태를 초기화한다.
    setLoading(true); setDocumentReady(false); setError("");
    readMappings(controller.signal)
      .then((value) => { if (!controller.signal.aborted && requestSequence.current === requestId) { setData(value); setDocumentReady(true); setError(""); } })
      .catch((reason: unknown) => { if (!controller.signal.aborted && requestSequence.current === requestId) setError(`${reason instanceof Error ? reason.message : "역 목록을 불러오지 못했습니다."} 최신 역 목록을 확인한 뒤 편집할 수 있습니다. 새로고침해 주세요.`); })
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
  const editorBlocked = loading || !documentReady || saving || applying;

  function reloadDocument() {
    requestSequence.current++; documentRequest.current?.abort();
    // 모달을 닫는 같은 렌더부터 보호한다. effect가 실행되기 전 편집 가능 틈도 만들지 않는다.
    setDocumentReady(false); setLoading(true); setReload(value => value + 1);
  }
  function discardAndReload() {
    if (saving || applying || loading) return;
    workbenchRef.current?.focus({ preventScroll: true });
    setDirty(false); setEditorReset(value => value + 1); reloadDocument();
  }

  async function save(target: string | null, note: string) {
    if (!data || !selected || saving || applying || loading || !documentReady) return;
    setSelectedKey(stationKey(selected));
    // 진행 중인 GET이 저장 응답보다 늦게 도착해 새 revision을 덮지 않게 무효화한다.
    requestSequence.current += 1;
    documentRequest.current?.abort();
    const controller = new AbortController(); mutationRequest.current = controller;
    setLoading(false);
    setSaving(true); setError(""); setNotice("");
    const mappings = data.mappings.filter((item) => stationKey(item) !== stationKey(selected));
    if (target) mappings.push({ operator_code: selected.operator_code, line_code: selected.line_code,
      station_code: selected.station_code, rail_station_identity_key: target, note });
    try {
      const updated = await saveMappings(data.revision, mappings, controller.signal);
      if (controller.signal.aborted) return;
      setData(updated);
      setNotice(target ? "수동 매핑을 저장했습니다." : "수동 매핑을 해제했습니다. 자동 기준과 다시 대조합니다.");
    } catch (reason) { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "역 매핑을 저장하지 못했습니다."); }
    finally { if (!controller.signal.aborted) setSaving(false); }
  }

  async function loadPreview() {
    if (dirty || saving || applying || loading || !documentReady) return;
    previewRequest.current?.abort();
    const controller = new AbortController(); previewRequest.current = controller;
    const sequence = ++previewSequence.current;
    setPreview(null); setAutomaticError(""); setPreviewLoading(true);
    try {
      const value = await previewAutomaticMappings(controller.signal);
      if (!controller.signal.aborted && sequence === previewSequence.current) setPreview(value);
    } catch (reason) {
      if (!controller.signal.aborted && sequence === previewSequence.current) setAutomaticError(reason instanceof Error ? reason.message : "미리보기를 불러오지 못했습니다.");
    } finally { if (!controller.signal.aborted && sequence === previewSequence.current) setPreviewLoading(false); }
  }
  function changeAutomaticOpen(open: boolean) {
    if (applying) return;
    setAutomaticOpen(open);
    if (open) { setNotice(""); void loadPreview(); }
    else { previewSequence.current++; previewRequest.current?.abort(); setPreview(null); setPreviewLoading(false); }
  }
  async function applyAutomatic() {
    if (!preview?.can_apply || !preview.has_changes || applying || dirty || saving || !documentReady) return;
    const controller = new AbortController(); mutationRequest.current = controller;
    requestSequence.current++; documentRequest.current?.abort();
    previewSequence.current++; previewRequest.current?.abort();
    setApplying(true); setAutomaticError("");
    try {
      const result = await applyAutomaticMappings(preview, controller.signal);
      if (controller.signal.aborted) return;
      setAutomaticOpen(false); setPreview(null);
      setNotice(result.status === "unchanged" ? "자동 연결은 변경 없이 확인됐습니다." : `자동 연결을 적용했습니다. 실제 역 연결 ${result.changed_link_count.toLocaleString("ko-KR")}건 변경.`);
      reloadDocument();
    } catch (reason) {
      if (controller.signal.aborted) return;
      const message = reason instanceof Error ? reason.message : "자동 연결의 적용 결과를 확인하지 못했습니다.";
      setAutomaticError(reason instanceof MappingRequestError && reason.status === 409 ? `${message} 새 미리보기를 확인해 주세요.` : `${message} 새 미리보기에서 현재 연결 상태를 확인해 주세요.`);
      // 실패한 후보를 재사용하지 않는다. 자동 재시도·POST 재실행은 없다.
      setPreview(null);
    } finally { if (!controller.signal.aborted) setApplying(false); }
  }

  function exportJson() {
    if (!data) return;
    const { mappings, ...catalog } = data;
    const body = JSON.stringify({ ...catalog, exported_at: new Date().toISOString(), manual_mappings: mappings }, null, 2);
    const url = URL.createObjectURL(new Blob([body], { type: "application/json" }));
    const anchor = document.createElement("a"); anchor.href = url; anchor.download = "kric-rail-station-mappings.json"; anchor.click();
    URL.revokeObjectURL(url);
  }

  return <section className="rail-map-workbench" data-slot="rail-station-mapping" aria-busy={loading || saving || applying} ref={workbenchRef} tabIndex={-1}>
    <div className="rail-map-toolbar">
      <div><p className="eyebrow">KRIC · 역 코드 카탈로그</p><p className="quiet">최근 확인 {formatDate(data?.catalog_updated_at ?? null)} · 지문 {data?.catalog_sha256?.slice(0, 12) ?? "—"}</p></div>
      <div className="rail-map-toolbar-actions">
        <button className="secondary" type="button" disabled={loading || saving || applying || dirty} onClick={reloadDocument}>새로고침</button>
        <Dialog.Root open={automaticOpen} onOpenChange={changeAutomaticOpen}>
          <Dialog.Trigger ref={automaticTrigger} className="secondary" disabled={!data || !documentReady || loading || saving || applying || dirty} title={dirty ? "수동 편집을 저장하거나 초안을 취소한 뒤 미리보기를 확인하세요." : undefined}>자동 연결 미리보기</Dialog.Trigger>
          <Dialog.Portal><Dialog.Backdrop className="fixed inset-0 bg-background/80" />
            <Dialog.Viewport className="info-positioner fixed inset-0 flex items-center justify-center p-3">
              <Dialog.Popup className="info-popup flex min-h-0 flex-col gap-3" style={{ width: "min(42rem, calc(100vw - 24px))", maxHeight: "calc(100dvh - 24px)" }} finalFocus={() => noticeRef.current ?? automaticTrigger.current}>
                <div className="info-popup-heading"><Dialog.Title>자동 연결 미리보기</Dialog.Title><InfoButton label="자동 연결 기준"><p>저장된 공식 역 코드와 기준 역을 대조합니다. 수동 연결과 근거는 보존하며, 수동 편집 초안은 먼저 저장하거나 취소해 주세요.</p><p>건수는 장소 수가 아닌 공식 역 코드 기준입니다. 수동 연결로 억제된 후보 갱신이나 연결 기준만 바뀌면 실제 역 연결 변경은 0건일 수 있습니다. 적용은 시간표 수집을 실행하지 않습니다.</p></InfoButton></div>
                <Dialog.Description className="sr-only">연결 건수와 변경행을 확인한 뒤 적용하거나 돌아갑니다.</Dialog.Description>
                <div className="min-h-0 overflow-auto" aria-busy={previewLoading || applying}>
                  {previewLoading ? <p role="status">자동 연결을 확인하는 중…</p> : null}
                  {automaticError ? <p className="error" role="alert">{automaticError}</p> : null}
                  {preview ? <AutomaticPreviewContent preview={preview} /> : null}
                </div>
                <div className="flex shrink-0 flex-wrap justify-end gap-2">
                  <Dialog.Close className="secondary" disabled={applying}>돌아가기</Dialog.Close>
                  {automaticError ? <button className="secondary" type="button" disabled={previewLoading || applying} onClick={() => void loadPreview()}>새 미리보기</button> : null}
                  <button className="button" type="button" disabled={!preview?.can_apply || !preview?.has_changes || previewLoading || applying || dirty || saving} onClick={() => void applyAutomatic()}>{applying ? "적용 중…" : "적용"}</button>
                </div>
              </Dialog.Popup>
            </Dialog.Viewport>
          </Dialog.Portal>
        </Dialog.Root>
        <button className="secondary" type="button" disabled={!data || !documentReady} onClick={exportJson}>JSON 내보내기</button>
      </div>
    </div>
    {data ? <div className="rail-map-metrics" aria-label="역 매핑 요약">
      <div><span>전체 역</span><strong>{data.station_count.toLocaleString("ko-KR")}</strong></div>
      <div><span>자동 연결</span><strong>{data.automatic_mapped_count.toLocaleString("ko-KR")}</strong></div>
      <div><span>수동 연결</span><strong>{data.manual_mapped_count.toLocaleString("ko-KR")}</strong></div>
      <div><span>미연결</span><strong>{data.unmatched_count.toLocaleString("ko-KR")}</strong></div>
    </div> : null}
    {loading && !data ? <p className="loading" role="status">KRIC 역 코드와 매핑을 불러오는 중입니다…</p> : null}
    {loading && data ? <p className="quiet" role="status">최신 역 목록을 확인하는 중…</p> : null}
    {error ? <p className="error" role="alert">{error}</p> : null}
    {notice ? <p className="rail-map-notice" role="status" tabIndex={-1} ref={noticeRef}>{notice}</p> : null}
    {data ? <div className="rail-map-layout">
      <section className="rail-map-list" aria-label="KRIC 역 목록">
        <div className="rail-map-list-tools">
          <label htmlFor="rail-station-filter">역명·운영기관·노선·코드 검색</label>
          <input id="rail-station-filter" type="search" disabled={editorBlocked} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="예: 서울역, 공항철도, A01" />
          <label className="rail-map-checkbox"><input type="checkbox" disabled={editorBlocked} checked={unmatchedOnly} onChange={(event) => setUnmatchedOnly(event.target.checked)} /> 미연결 우선 보기</label>
          <p className="quiet">{filtered.length.toLocaleString("ko-KR")}개 결과 · 목록 최대 100개 표시</p>
        </div>
        <div className="rail-map-station-list" role="listbox" aria-label="역 선택">
          {visibleStations.map((station) => <button key={stationKey(station)} type="button" role="option" disabled={editorBlocked}
            aria-selected={selected ? stationKey(selected) === stationKey(station) : false}
            className={selected && stationKey(selected) === stationKey(station) ? "is-selected" : ""}
            onClick={() => setSelectedKey(stationKey(station))}>
            <span><strong>{station.station_name}</strong><small>{station.line_name} · {station.operator_name}</small></span>
            <span className={`rail-map-dot ${station.match_method === "unmatched" ? "is-unmatched" : ""}`} aria-label={station.match_method === "unmatched" ? "미연결" : "연결됨"} />
          </button>)}
          {!filtered.length ? <p className="quiet">조건에 맞는 역이 없습니다.</p> : null}
        </div>
      </section>
      {selected ? <StationEditor key={`${stationKey(selected)}:${editorReset}`} station={selected} currentPlace={currentPlace}
        manualMapping={manualMapping} places={data.places} saving={saving || applying} readOnly={editorBlocked} busy={loading || saving || applying} onSave={save} onDirtyChange={setDirty} onDiscard={discardAndReload} /> : <div className="rail-map-editor"><p className="quiet">연결할 역을 선택해 주세요.</p></div>}
    </div> : null}
  </section>;
}
