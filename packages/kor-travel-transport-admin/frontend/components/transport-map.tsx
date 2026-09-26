"use client";

import { ClusterLayer, Marker, PriceMarker, VWorldMapView } from "vworld-map-web";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { clusterAtScale, hasCoordinates, transportGet, type Place, type PlaceKind } from "@/lib/journey";
import { collectionSourceLabel, fuelProductLabel, placeKindLabel } from "@/lib/transport-presentation";
import { PlaceDetails, PlaceIcon, ViewSwitch } from "./journey-controls";

type MapPoint = { id: string; lngLat: [number, number]; place: Place };
type Bounds = { getWest: () => number; getSouth: () => number; getEast: () => number; getNorth: () => number };
type Viewport = { min_longitude: string; min_latitude: string; max_longitude: string; max_latitude: string };
type PlaceResponse = { items: Place[]; total: number; truncated: boolean };
const KINDS: PlaceKind[] = ["fuel_station", "rail_station", "ferry_port", "airport", "rest_area"];
const DEFAULT_VIEWPORT: Viewport = { min_longitude: "124", min_latitude: "32", max_longitude: "132", max_latitude: "39" };
const keyOf = (place: Place) => `${place.kind}:${place.id}`;

function MapMarker({ point, onSelect, selected, product }: { point: MapPoint; onSelect: (place: Place) => void; selected: boolean; product: string }) {
  const place = point.place;
  const prices = (place.prices ?? []).filter((row) => row.price != null && (!product || row.product_code === product));
  const props = { ariaLabel: `${placeKindLabel(place.kind)} ${place.name} 상세 보기`, interactionId: point.id, lngLat: point.lngLat, onClick: () => onSelect(place), selected, className: `transport-map-marker ${place.kind}` };
  if (place.kind === "fuel_station" && prices.length) return <PriceMarker {...props} lodThresholds={[0, 0]} price={prices.map((row) => ({ label: `${place.brand_name ?? "주유소"} · ${fuelProductLabel(row.product_code)}`, price: `${row.price?.toLocaleString("ko-KR")}원/L` }))} />;
  return <Marker {...props}><span className={`journey-marker ${place.kind}`}><PlaceIcon kind={place.kind} /><span><strong>{place.name}</strong><small>{place.line_names.length ? place.line_names.join(" · ") : place.subtitle ?? placeKindLabel(place.kind)}</small>{place.kind === "rail_station" ? <small>다음 열차 · 시간표 미연결</small> : null}</span></span></Marker>;
}

export function TransportMap({ places, selectedPlace, onSelectPlace }: { places?: Place[]; selectedPlace?: Place | null; onSelectPlace?: (place: Place) => void }) {
  const embedded = places !== undefined;
  const [loaded, setLoaded] = useState<Record<string, PlaceResponse>>({});
  const [kinds, setKinds] = useState<PlaceKind[]>(KINDS);
  const [source, setSource] = useState("");
  const [product, setProduct] = useState("");
  const [query, setQuery] = useState("");
  const [view, setView] = useState<"map" | "list">("map");
  const [selected, setSelected] = useState<Place | null>(null);
  const [viewport, setViewport] = useState(DEFAULT_VIEWPORT);
  const [zoom, setZoom] = useState(7);
  const [cluster, setCluster] = useState(true);
  const [pending, setPending] = useState<string[]>([]);
  const [failed, setFailed] = useState<string[]>([]);
  const [mapError, setMapError] = useState("");
  const [reload, setReload] = useState(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const current = selectedPlace === undefined ? selected : selectedPlace;
  const kindsKey = kinds.join(",");
  const perKindLimit = Math.min(300, Math.floor(900 / Math.max(1, kinds.length)));
  const sources = useMemo(() => [...new Set((places ?? Object.values(loaded).flatMap((row) => row.items)).map((item) => item.source))], [places, loaded]);
  const all = useMemo(() => places ?? kinds.flatMap((kind) => loaded[kind]?.items ?? []), [places, kinds, loaded]);
  const items = useMemo(() => all.filter((item) => (!source || item.source === source) && (!query || [item.name, item.brand_name, item.address, ...item.line_names].join(" ").includes(query)) && (!product || item.kind !== "fuel_station" || item.prices?.some((row) => row.product_code === product))), [all, source, query, product]);
  const points = useMemo<MapPoint[]>(() => items.filter(hasCoordinates).map((place) => ({ id: keyOf(place), lngLat: [place.longitude, place.latitude], place })), [items]);
  const selectPlace = (place: Place) => { setSelected(place); onSelectPlace?.(place); };

  useEffect(() => {
    if (embedded) return;
    const controller = new AbortController();
    const selectedKinds = kindsKey ? kindsKey.split(",") : [];
    // 외부 조회 조건이 바뀌면 이전 영역의 결과를 제거하고 요청 상태를 초기화한다.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setPending(selectedKinds); setFailed([]); setLoaded({});
    // 각 종류가 끝나는 즉시 표시한다. 느린 유가 조회가 역·항구를 가리지 않는다.
    selectedKinds.forEach((kind) => {
      const search = new URLSearchParams({ kind, limit: String(perKindLimit), ...viewport });
      transportGet<PlaceResponse>(`transport/features/places?${search}`, controller.signal).then((payload) => {
        if (!controller.signal.aborted) setLoaded((value) => ({ ...value, [kind]: payload }));
      }).catch(() => { if (!controller.signal.aborted) setFailed((value) => [...value, kind]); })
        .finally(() => { if (!controller.signal.aborted) setPending((value) => value.filter((entry) => entry !== kind)); });
    });
    return () => controller.abort();
  }, [embedded, kindsKey, perKindLimit, viewport, reload]);

  useEffect(() => {
    const handleError = () => setMapError("VWorld 지도 타일을 불러오지 못했습니다. 목록 보기에서 장소를 확인할 수 있습니다.");
    window.addEventListener("vworld-tile-error", handleError);
    return () => { window.removeEventListener("vworld-tile-error", handleError); if (timer.current) clearTimeout(timer.current); };
  }, []);

  const moved = useCallback((bounds: Bounds, nextZoom: number) => {
    setZoom(nextZoom);
    setCluster(clusterAtScale(nextZoom, (bounds.getNorth() + bounds.getSouth()) / 2));
    if (embedded) return;
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setViewport({
      min_longitude: Math.max(-180, bounds.getWest()).toFixed(4), min_latitude: Math.max(-90, bounds.getSouth()).toFixed(4),
      max_longitude: Math.min(180, bounds.getEast()).toFixed(4), max_latitude: Math.min(90, bounds.getNorth()).toFixed(4),
    }), 250);
  }, [embedded]);
  const truncated = Object.entries(loaded).filter(([, row]) => row.truncated).map(([kind]) => placeKindLabel(kind));
  const camera = useMemo(() => current && hasCoordinates(current) ? { center: [current.longitude, current.latitude] as [number, number], zoom: Math.max(zoom, 11) } : undefined, [current]); // eslint-disable-line react-hooks/exhaustive-deps

  return <section className="map-workbench" aria-label="교통 장소 지도">
    {!embedded ? <div className="map-filter-bar">
      <div className="kind-filters" role="group" aria-label="장소 종류">{KINDS.map((kind) => <button type="button" key={kind} aria-pressed={kinds.includes(kind)} onClick={() => { setKinds((value) => value.includes(kind) ? value.filter((entry) => entry !== kind) : [...value, kind]); setSelected(null); }}><PlaceIcon kind={kind} />{placeKindLabel(kind)}</button>)}</div>
      <div className="journey-toolbar"><label>장소 검색<input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="이름·브랜드·노선" /></label>
      <label>데이터 출처<select value={source} onChange={(event) => { setSource(event.target.value); setSelected(null); }}><option value="">모든 출처</option>{sources.map((value) => <option key={value} value={value}>{collectionSourceLabel(value)}</option>)}</select></label>
      <label>표시 유종<select value={product} onChange={(event) => setProduct(event.target.value)}><option value="">전체 유종</option>{["B027", "D047", "B034", "K015", "C004"].map((code) => <option key={code} value={code}>{fuelProductLabel(code)}</option>)}</select></label>
      <ViewSwitch value={view} onChange={setView} /></div>
    </div> : <ViewSwitch value={view} onChange={setView} />}
    <div className="map-feedback" role="status">
      {pending.length ? <span>{pending.map(placeKindLabel).join("·")} 조회 중… </span> : null}
      <span>{items.length}곳 표시 · {cluster ? "넓은 축척에서 묶음 표시" : "30km 이하 축척 · 개별 마커"}</span>
      {truncated.length ? <p>{truncated.join("·")} 일부를 표시합니다(종류별 최대 {perKindLimit}곳). 확대해 주세요. 묶음 수는 현재 불러온 장소 수입니다.</p> : null}
      {failed.length ? <p className="error">{failed.map(placeKindLabel).join("·")} 조회 실패 <button type="button" onClick={() => setReload((value) => value + 1)}>다시 조회</button></p> : null}
      {mapError ? <p className="error">{mapError}</p> : null}
      {!items.length && !pending.length ? <p>표시할 장소가 없습니다. 종류·출처·검색 조건을 확인해 주세요.</p> : null}
    </div>
    <div className={embedded ? "embedded-map" : "transport-map-layout"}>
      {view === "map" ? <VWorldMapView apiKey={process.env.NEXT_PUBLIC_VWORLD_API_KEY ?? ""} cameraTarget={camera} center={[127.8, 36.2]} className="transport-map-canvas"
        fallback={() => <p className="empty-state">지도 키가 없어 지도를 표시하지 못합니다. 위의 목록 보기에서 장소를 선택해 주세요.</p>}
        geolocate={false} layerType="Base" lazy loadingSkeleton={<p className="loading">지도를 준비하는 중입니다…</p>} minZoom={5} navigation scale
        onLoad={(map) => moved(map.getBounds(), map.getZoom())}
        onMoveEnd={(event) => { const map = event.target as { getBounds: () => Bounds; getZoom: () => number }; moved(map.getBounds(), map.getZoom()); }}
        unsupportedTileFallback={{ label: "지도를 불러오지 못했습니다." }} zoom={7}>
        {cluster ? <ClusterLayer points={points} radius={50} renderMarker={(point) => <MapMarker key={point.id} point={point as MapPoint} product={product} onSelect={selectPlace} selected={current ? keyOf(current) === point.id : false} />} /> : points.map((point) => <MapMarker key={point.id} point={point} product={product} onSelect={selectPlace} selected={current ? keyOf(current) === point.id : false} />)}
      </VWorldMapView> : <div className="map-place-list">{items.map((place) => <button type="button" className="place-row" key={keyOf(place)} aria-pressed={current ? keyOf(current) === keyOf(place) : false} onClick={() => selectPlace(place)}><PlaceIcon kind={place.kind} /><span><strong>{place.name}</strong><small>{place.line_names.join(" · ") || place.brand_name || place.subtitle || placeKindLabel(place.kind)}</small>{!hasCoordinates(place) ? <small>좌표 미등록</small> : null}</span></button>)}</div>}
      {!embedded ? <aside className="transport-map-detail">
        <label className="transport-map-picker">장소 목록에서 선택<select value={current ? keyOf(current) : ""} onChange={(event) => { const place = items.find((item) => keyOf(item) === event.target.value); if (place) selectPlace(place); }}><option value="">장소 선택</option>{items.map((place) => <option key={keyOf(place)} value={keyOf(place)}>{placeKindLabel(place.kind)} · {place.name}</option>)}</select></label>
        {current ? <><PlaceDetails place={current} />{current.kind === "ferry_port" ? <Link className="button" href={`/ferry?port=${encodeURIComponent(current.provider_id ?? "")}`}>운항 시간표 비교</Link> : null}{current.kind === "airport" ? <Link className="button" href="/flights">출도착·주차 보기</Link> : null}</> : <p className="empty-state">지도나 목록에서 장소를 선택하면 가격·노선·편의정보를 확인할 수 있습니다.</p>}
      </aside> : null}
    </div>
  </section>;
}
