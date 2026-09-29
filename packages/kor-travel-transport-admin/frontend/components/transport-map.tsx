"use client";

import { ClusterLayer, ClusterMarker, Marker, VWorldMapView } from "vworld-map-web";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { clusterAtScale, hasCoordinates, hasFuelPrice, transportGet, type Place, type PlaceKind } from "@/lib/journey";
import { collectionSourceLabel, fuelProductLabel, placeKindLabel } from "@/lib/transport-presentation";
import { MAP_FALLBACK_IMAGE } from "@/lib/map-fallback";
import { PlaceIcon, ViewSwitch } from "./journey-controls";
import { PlaceInspector } from "./place-inspector";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { FilterCombobox } from "./filter-combobox";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Empty, EmptyHeader, EmptyDescription } from "@/components/ui/empty";

type MapPoint = { id: string; lngLat: [number, number]; place: Place };
type Bounds = { getWest: () => number; getSouth: () => number; getEast: () => number; getNorth: () => number };
type Viewport = { min_longitude: string; min_latitude: string; max_longitude: string; max_latitude: string };
type PlaceResponse = { items: Place[]; total: number; truncated: boolean; available_sources?: string[] };
const KINDS: PlaceKind[] = ["fuel_station", "rail_station", "ferry_port", "bus_terminal", "airport", "rest_area", "highway_incident"];
const DEFAULT_VIEWPORT: Viewport = { min_longitude: "124", min_latitude: "32", max_longitude: "132", max_latitude: "39" };
const keyOf = (place: Place) => `${place.kind}:${place.id}`;

function MapMarker({ point, onSelect, selected, products }: { point: MapPoint; onSelect: (place: Place) => void; selected: boolean; products: string[] }) {
  const place = point.place;
  const prices = (place.prices ?? []).filter((row) => hasFuelPrice(row) && (!products.length || products.includes(row.product_code)));
  const props = { ariaLabel: `${placeKindLabel(place.kind)} ${place.name} ${place.line_names.join(" · ")} 상세 보기`, interactionId: point.id, lngLat: point.lngLat, onClick: () => onSelect(place), selected, className: `transport-map-marker ${place.kind}` };
  return <Marker {...props}><span className={`journey-marker compact-marker ${place.kind}`} title={`${place.name}${place.brand_name ? ` · ${place.brand_name}` : ""}`}><PlaceIcon kind={place.kind} />{place.kind === "fuel_station" && prices.length ? <span className="marker-prices">{prices.map((row) => <span key={row.product_code}><span>{fuelProductLabel(row.product_code)}</span><strong>{row.price?.toLocaleString("ko-KR")}</strong></span>)}</span> : <strong>{[place.name, place.kind === "rail_station" ? place.line_names.join("·") : null].filter(Boolean).join(" ")}</strong>}</span></Marker>;
}

export function TransportMap({ places, selectedPlace, onSelectPlace }: { places?: Place[]; selectedPlace?: Place | null; onSelectPlace?: (place: Place) => void }) {
  const controlId = useId();
  const embedded = places !== undefined;
  const [loaded, setLoaded] = useState<Record<string, PlaceResponse>>({});
  const [kinds, setKinds] = useState<PlaceKind[]>(KINDS);
  const [selectedSources, setSelectedSources] = useState<string[]>([]);
  const [knownSources, setKnownSources] = useState<string[]>([]);
  const [products, setProducts] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [clusterPlaces, setClusterPlaces] = useState<Place[]>([]);
  const [clusterCamera, setClusterCamera] = useState<{ center: [number, number]; zoom: number }>();
  const clusterList = useRef<HTMLElement | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [view, setView] = useState<"map" | "list">("map");
  const [selected, setSelected] = useState<Place | null>(null);
  const [viewport, setViewport] = useState(DEFAULT_VIEWPORT);
  const [zoom, setZoom] = useState(7);
  const [mapSize, setMapSize] = useState({ width: 800, height: 540 });
  const mapContainer = useRef<HTMLDivElement | null>(null);
  const queryInput = useRef<HTMLInputElement | null>(null);
  const [pending, setPending] = useState<string[]>([]);
  const [failed, setFailed] = useState<string[]>([]);
  const [mapError, setMapError] = useState("");
  const [reload, setReload] = useState(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const current = selectedPlace === undefined ? selected : selectedPlace;
  const kindsKey = kinds.join(",");
  const sourcesKey = selectedSources.join(",");
  const productsKey = products.join(",");
  const perKindLimit = Math.min(300, Math.floor(900 / Math.max(1, kinds.length)));
  const sources = useMemo(() => [...new Set([...knownSources, ...(places ?? []).map((item) => item.source)])], [places, knownSources]);
  const all = useMemo(() => places ?? kinds.flatMap((kind) => loaded[kind]?.items ?? []), [places, kinds, loaded]);
  const items = useMemo(() => all.filter((item) => (!selectedSources.length || selectedSources.includes(item.source)) && (!embedded || !query || [item.name, item.brand_name, item.address, item.subtitle, item.provider_id, ...item.line_names].join(" ").toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())) && (!products.length || item.kind !== "fuel_station" || item.prices?.some((row) => hasFuelPrice(row) && products.includes(row.product_code)))), [all, embedded, selectedSources, query, products]);
  const points = useMemo<MapPoint[]>(() => items.filter(hasCoordinates).map((place) => ({ id: keyOf(place), lngLat: [place.longitude, place.latitude], place })), [items]);
  const visiblePoints = points.filter((point) =>
    point.lngLat[0] >= Number(viewport.min_longitude) && point.lngLat[0] <= Number(viewport.max_longitude)
    && point.lngLat[1] >= Number(viewport.min_latitude) && point.lngLat[1] <= Number(viewport.max_latitude));
  const cluster = clusterAtScale(zoom, (Number(viewport.min_latitude) + Number(viewport.max_latitude)) / 2, visiblePoints.length, mapSize.width, mapSize.height);
  const groupedPoints = useMemo(() => current ? points.filter((point) => point.id !== keyOf(current)) : points, [points, current]);
  const selectedPoint = points.find((point) => current && point.id === keyOf(current));
  const detail = useRef<HTMLElement | null>(null);
  const selectPlace = (place: Place) => {
    setClusterPlaces([]); setClusterCamera(undefined);
    setSelected(place); onSelectPlace?.(place);
    if (!embedded) requestAnimationFrame(() => detail.current?.focus({ preventScroll: true }));
  };

  useEffect(() => {
    if (!mapContainer.current) return;
    const observer = new ResizeObserver(([entry]) => setMapSize({ width: entry.contentRect.width, height: entry.contentRect.height }));
    observer.observe(mapContainer.current);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (query === searchQuery) return;
    const debounce = setTimeout(() => { setSearchQuery(query); setSelected(null); }, 250);
    return () => clearTimeout(debounce);
  }, [query, searchQuery]);

  useEffect(() => {
    // 지도 이동·크기 변경으로 DB 결과가 갱신되어도 열어 둔 선택 목록은 유지한다.
    // 검색 조건을 바꾸거나 명시적으로 선택/닫기한 경우에만 목록을 닫는다.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setClusterPlaces([]);
  }, [kindsKey, sourcesKey, searchQuery, productsKey, view]);

  useEffect(() => {
    if (embedded) return;
    const controller = new AbortController();
    const selectedKinds = kindsKey ? kindsKey.split(",") : [];
    // 외부 조회 조건이 바뀌면 이전 영역의 결과를 제거하고 요청 상태를 초기화한다.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setPending(selectedKinds); setFailed([]); setLoaded({});
    // 각 종류가 끝나는 즉시 표시한다. 느린 유가 조회가 역·항구를 가리지 않는다.
    selectedKinds.forEach((kind) => {
      // 좌표 없는 항구·터미널도 목록에서 코드/이름으로 찾되 지도에는 검증된 위치만 놓는다.
      const referenceList = view === "list" && (kind === "ferry_port" || kind === "bus_terminal");
      const search = new URLSearchParams({ kind, limit: String(referenceList && searchQuery.trim() ? 5000 : perKindLimit),
        ...(referenceList ? { include_unlocated: "true" } : viewport) });
      if (sourcesKey) search.set("sources", sourcesKey);
      if (searchQuery.trim()) search.set("query", searchQuery.trim());
      if (productsKey && kind === "fuel_station") search.set("product_codes", productsKey);
      transportGet<PlaceResponse>(`transport/features/places?${search}`, controller.signal).then((payload) => {
        if (!controller.signal.aborted) {
          setLoaded((value) => ({ ...value, [kind]: payload }));
          setKnownSources((value) => [...new Set([...value, ...(payload.available_sources ?? payload.items.map((item) => item.source))])]);
        }
      }).catch(() => { if (!controller.signal.aborted) setFailed((value) => [...value, kind]); })
        .finally(() => { if (!controller.signal.aborted) setPending((value) => value.filter((entry) => entry !== kind)); });
    });
    return () => controller.abort();
  }, [embedded, kindsKey, perKindLimit, viewport, reload, sourcesKey, searchQuery, productsKey, view]);

  useEffect(() => {
    const handleError = () => setMapError("VWorld 지도 타일을 불러오지 못했습니다. 목록 보기에서 장소를 확인할 수 있습니다.");
    window.addEventListener("vworld-tile-error", handleError);
    return () => { window.removeEventListener("vworld-tile-error", handleError); if (timer.current) clearTimeout(timer.current); };
  }, []);

  const moved = useCallback((bounds: Bounds, nextZoom: number) => {
    setZoom(nextZoom);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setViewport((previous) => {
      const next = {
        min_longitude: Math.max(-180, bounds.getWest()).toFixed(4), min_latitude: Math.max(-90, bounds.getSouth()).toFixed(4),
        max_longitude: Math.min(180, bounds.getEast()).toFixed(4), max_latitude: Math.min(90, bounds.getNorth()).toFixed(4),
      };
      // 패널 높이/스크롤 변화로 같은 bounds의 moveend가 와도 선택 목록을 지우거나
      // 동일 DB 조회를 반복하지 않는다. 실제 이동·확대 시에는 기존대로 갱신한다.
      return (Object.keys(next) as (keyof Viewport)[]).every((key) => next[key] === previous[key]) ? previous : next;
    }), 250);
  }, []);
  const truncated = Object.entries(loaded).filter(([, row]) => row.truncated).map(([kind]) => placeKindLabel(kind));
  const camera = useMemo(() => clusterCamera ?? (current && hasCoordinates(current) ? { center: [current.longitude, current.latitude] as [number, number], zoom: Math.max(zoom, 11) } : undefined), [current, clusterCamera]); // eslint-disable-line react-hooks/exhaustive-deps

  return <section className="map-workbench" aria-label="교통 장소 지도">
    {!embedded ? <div className="map-filter-bar">
      <ToggleGroup multiple variant="outline" className="flex-wrap" aria-label="장소 종류" value={kinds} onValueChange={(values) => { setKinds(values.filter((value): value is PlaceKind => KINDS.includes(value as PlaceKind))); setSelected(null); }}>{KINDS.map((kind) => <ToggleGroupItem key={kind} value={kind}><PlaceIcon kind={kind} />{placeKindLabel(kind)}</ToggleGroupItem>)}</ToggleGroup>
      <FieldGroup className="grid grid-cols-1 items-end gap-3 sm:grid-cols-2 xl:grid-cols-4"><Field><FieldLabel htmlFor={`${controlId}-query`}>장소 검색</FieldLabel><Input ref={queryInput} id={`${controlId}-query`} type="search" value={query} onChange={(event) => { setQuery(event.target.value); setSelected(null); }} placeholder="이름·브랜드·노선" /></Field>
      <Field><FieldLabel htmlFor={`${controlId}-source`}>데이터 출처</FieldLabel><FilterCombobox id={`${controlId}-source`} value={selectedSources} onChange={(values) => { setSelectedSources(values); setSelected(null); }} placeholder="모든 출처" options={sources.map((value) => ({ value, label: collectionSourceLabel(value) }))} /></Field>
      <Field><FieldLabel htmlFor={`${controlId}-product`}>표시 유종</FieldLabel><FilterCombobox id={`${controlId}-product`} value={products} onChange={(values) => { setProducts(values); setSelected(null); }} placeholder="전체 유종" options={["B027", "D047", "B034", "K015", "C004"].map((value) => ({ value, label: fuelProductLabel(value) }))} /></Field>
      <ViewSwitch value={view} onChange={setView} /></FieldGroup>
    </div> : <ViewSwitch value={view} onChange={setView} />}
    <div className="map-feedback" role="status">
      {pending.length ? <span>{pending.map(placeKindLabel).join("·")} 조회 중… </span> : null}
      <span>{items.length}곳 표시 · {cluster ? "축척·화면 밀도에 따라 묶음 표시" : "가까운 장소만 묶음 표시"}</span>
      {!embedded && (kinds.includes("ferry_port") || kinds.includes("bus_terminal")) ? <p>지도는 검증된 좌표만 표시합니다. 위치 미확인 항구·버스 터미널은 목록 보기에서 이름·코드로 검색하세요.</p> : null}
      {!embedded && kinds.includes("highway_incident") ? <p>도로 돌발은 최근 24시간의 최신 저장 관측입니다. 현재 통제 여부는 상세의 처리 상태와 관측 시각을 확인해 주세요.</p> : null}
      {truncated.length ? <p>{truncated.join("·")} 일부만 표시합니다. {view === "list" ? "이름·코드 검색으로 범위를 좁혀 주세요." : "지도에서 확대하거나 목록 보기에서 이름·코드로 검색해 주세요."} 묶음 수는 현재 불러온 장소 수입니다.</p> : null}
      {failed.length ? <p className="error">{failed.map(placeKindLabel).join("·")} 조회 실패 <Button variant="outline" type="button" onClick={() => setReload((value) => value + 1)}>다시 조회</Button></p> : null}
      {mapError ? <p className="error">{mapError}</p> : null}
      {!items.length && !pending.length ? <p>표시할 장소가 없습니다. 종류·출처·검색 조건을 확인해 주세요.</p> : null}
    </div>
    <div className={embedded ? "embedded-map" : "transport-map-layout"}>
      {clusterPlaces.length ? <section ref={clusterList} className="col-span-full flex min-w-0 flex-col gap-2" aria-label="겹친 장소 선택">
        <p>더 확대해도 겹치는 {clusterPlaces.length}곳입니다. 상세를 볼 장소를 선택해 주세요.</p>
        <div className="flex max-h-64 flex-wrap gap-2 overflow-y-auto">{clusterPlaces.map((place) => <Button key={keyOf(place)} className="max-w-full" variant="outline" onClick={() => selectPlace(place)}><PlaceIcon kind={place.kind} /><span className="truncate">{place.name}</span></Button>)}</div>
        <Button className="w-fit" variant="ghost" onClick={() => setClusterPlaces([])}>묶음 목록 닫기</Button>
      </section> : null}
      <div className="map-primary" ref={mapContainer}>{view === "map" ? <VWorldMapView apiKey={process.env.NEXT_PUBLIC_VWORLD_API_KEY ?? ""} cameraTarget={camera} center={[127.8, 36.2]} className="transport-map-canvas"
        fallback={() => <p className="empty-state">지도 키가 없어 지도를 표시하지 못합니다. 위의 목록 보기에서 장소를 선택해 주세요.</p>}
        geolocate={false} layerType="Base" lazy loadingSkeleton={<p className="loading">지도를 준비하는 중입니다…</p>} minZoom={5} navigation scale
        onLoad={(map) => moved(map.getBounds(), map.getZoom())}
        onMoveEnd={(event) => { const map = event.target as { getBounds: () => Bounds; getZoom: () => number }; moved(map.getBounds(), map.getZoom()); }}
        unsupportedTileFallback={{ imageUrl: MAP_FALLBACK_IMAGE }} zoom={7}>
        <ClusterLayer points={groupedPoints} radius={cluster ? (products.length === 1 ? 80 : 110) : 60} maxZoom={19}
          renderCluster={(group, count, index) => <ClusterMarker lngLat={group.geometry.coordinates} count={count} onClick={() => {
            const id = group.properties.cluster_id;
            if (id === undefined) return;
            const expansion = index.getClusterExpansionZoom(id);
            if (expansion > 19 || zoom >= 19) {
              setClusterPlaces(index.getLeaves(id, count).map((leaf: { properties: { place: Place } }) => leaf.properties.place));
              requestAnimationFrame(() => clusterList.current?.querySelector("button")?.focus());
            } else {
              setClusterPlaces([]); setClusterCamera({ center: group.geometry.coordinates, zoom: Math.min(19, expansion) });
            }
          }} />}
          renderMarker={(point) => <MapMarker key={point.id} point={point as MapPoint} products={products} onSelect={selectPlace} selected={false} />} />
        {selectedPoint ? <MapMarker point={selectedPoint} products={products} onSelect={selectPlace} selected /> : null}
      </VWorldMapView> : <div className="map-place-list">{items.map((place) => <button type="button" className="place-row" key={keyOf(place)} aria-pressed={current ? keyOf(current) === keyOf(place) : false} onClick={() => selectPlace(place)}><PlaceIcon kind={place.kind} /><span><strong>{place.name}</strong><small>{place.line_names.join(" · ") || place.brand_name || place.subtitle || placeKindLabel(place.kind)}</small>{(place.kind === "ferry_port" || place.kind === "bus_terminal") && place.provider_id ? <small>{place.kind === "ferry_port" ? "항구" : "터미널"} 코드 {place.provider_id}</small> : null}{!hasCoordinates(place) ? <small>좌표 미등록</small> : null}</span></button>)}</div>}
      </div>{!embedded ? <aside className="transport-map-detail weather-inspector" ref={detail} tabIndex={-1} aria-label="선택 장소 상세">
        {current ? <PlaceInspector key={keyOf(current)} place={current} onClose={() => { setSelected(null); queryInput.current?.focus(); }} /> : <Empty><EmptyHeader><EmptyDescription>지도나 목록에서 장소를 선택하면 가격·노선·출도착·편의정보를 확인할 수 있습니다.</EmptyDescription></EmptyHeader></Empty>}
      </aside> : null}
    </div>
  </section>;
}
