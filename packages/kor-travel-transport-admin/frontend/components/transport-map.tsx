"use client";

import { ClusterLayer, ClusterMarker, Marker, VWorldMapView } from "vworld-map-web";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { clusterAtScale, hasCoordinates, transportGet, type Place, type PlaceKind } from "@/lib/journey";
import { collectionSourceLabel, fuelProductLabel, placeKindLabel } from "@/lib/transport-presentation";
import { PlaceIcon, ViewSwitch } from "./journey-controls";
import { PlaceInspector } from "./place-inspector";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Empty, EmptyHeader, EmptyDescription } from "@/components/ui/empty";

type MapPoint = { id: string; lngLat: [number, number]; place: Place };
type Bounds = { getWest: () => number; getSouth: () => number; getEast: () => number; getNorth: () => number };
type Viewport = { min_longitude: string; min_latitude: string; max_longitude: string; max_latitude: string };
type PlaceResponse = { items: Place[]; total: number; truncated: boolean; available_sources?: string[] };
const KINDS: PlaceKind[] = ["fuel_station", "rail_station", "ferry_port", "airport", "rest_area"];
const DEFAULT_VIEWPORT: Viewport = { min_longitude: "124", min_latitude: "32", max_longitude: "132", max_latitude: "39" };
const keyOf = (place: Place) => `${place.kind}:${place.id}`;

function MapMarker({ point, onSelect, selected, product }: { point: MapPoint; onSelect: (place: Place) => void; selected: boolean; product: string }) {
  const place = point.place;
  const prices = (place.prices ?? []).filter((row) => row.price != null && (!product || row.product_code === product));
  const props = { ariaLabel: `${placeKindLabel(place.kind)} ${place.name} ${place.line_names.join(" · ")} 상세 보기`, interactionId: point.id, lngLat: point.lngLat, onClick: () => onSelect(place), selected, className: `transport-map-marker ${place.kind}` };
  return <Marker {...props}><span className={`journey-marker compact-marker ${place.kind}`} title={`${place.name}${place.brand_name ? ` · ${place.brand_name}` : ""}`}><PlaceIcon kind={place.kind} />{place.kind === "fuel_station" && prices.length ? <span className="marker-prices">{prices.map((row) => <span key={row.product_code}><span>{fuelProductLabel(row.product_code)}</span><strong>{row.price?.toLocaleString("ko-KR")}</strong></span>)}</span> : <strong>{[place.name, place.kind === "rail_station" ? place.line_names.join("·") : null].filter(Boolean).join(" ")}</strong>}</span></Marker>;
}

export function TransportMap({ places, selectedPlace, onSelectPlace }: { places?: Place[]; selectedPlace?: Place | null; onSelectPlace?: (place: Place) => void }) {
  const controlId = useId();
  const embedded = places !== undefined;
  const [loaded, setLoaded] = useState<Record<string, PlaceResponse>>({});
  const [kinds, setKinds] = useState<PlaceKind[]>(KINDS);
  const [source, setSource] = useState("");
  const [knownSources, setKnownSources] = useState<string[]>([]);
  const [product, setProduct] = useState("");
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
  const [pending, setPending] = useState<string[]>([]);
  const [failed, setFailed] = useState<string[]>([]);
  const [mapError, setMapError] = useState("");
  const [reload, setReload] = useState(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const current = selectedPlace === undefined ? selected : selectedPlace;
  const kindsKey = kinds.join(",");
  const perKindLimit = Math.min(300, Math.floor(900 / Math.max(1, kinds.length)));
  const sources = useMemo(() => [...new Set([...knownSources, ...(places ?? []).map((item) => item.source)])], [places, knownSources]);
  const all = useMemo(() => places ?? kinds.flatMap((kind) => loaded[kind]?.items ?? []), [places, kinds, loaded]);
  const items = useMemo(() => all.filter((item) => (!source || item.source === source) && (!embedded || !query || [item.name, item.brand_name, item.address, item.subtitle, item.provider_id, ...item.line_names].join(" ").toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())) && (!product || item.kind !== "fuel_station" || item.prices?.some((row) => row.product_code === product))), [all, embedded, source, query, product]);
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
    const debounce = setTimeout(() => setSearchQuery(query), 250);
    return () => clearTimeout(debounce);
  }, [query]);

  useEffect(() => {
    if (embedded) return;
    const controller = new AbortController();
    const selectedKinds = kindsKey ? kindsKey.split(",") : [];
    // 외부 조회 조건이 바뀌면 이전 영역의 결과를 제거하고 요청 상태를 초기화한다.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setPending(selectedKinds); setFailed([]); setClusterPlaces([]);
    // 각 종류가 끝나는 즉시 표시한다. 느린 유가 조회가 역·항구를 가리지 않는다.
    selectedKinds.forEach((kind) => {
      const search = new URLSearchParams({ kind, limit: String(perKindLimit), ...viewport });
      if (source) search.set("source", source);
      if (searchQuery.trim()) search.set("query", searchQuery.trim());
      if (product && kind === "fuel_station") search.set("product_code", product);
      transportGet<PlaceResponse>(`transport/features/places?${search}`, controller.signal).then((payload) => {
        if (!controller.signal.aborted) {
          setLoaded((value) => ({ ...value, [kind]: payload }));
          setKnownSources((value) => [...new Set([...value, ...(payload.available_sources ?? payload.items.map((item) => item.source))])]);
        }
      }).catch(() => { if (!controller.signal.aborted) setFailed((value) => [...value, kind]); })
        .finally(() => { if (!controller.signal.aborted) setPending((value) => value.filter((entry) => entry !== kind)); });
    });
    return () => controller.abort();
  }, [embedded, kindsKey, perKindLimit, viewport, reload, source, searchQuery, product]);

  useEffect(() => {
    const handleError = () => setMapError("VWorld 지도 타일을 불러오지 못했습니다. 목록 보기에서 장소를 확인할 수 있습니다.");
    window.addEventListener("vworld-tile-error", handleError);
    return () => { window.removeEventListener("vworld-tile-error", handleError); if (timer.current) clearTimeout(timer.current); };
  }, []);

  const moved = useCallback((bounds: Bounds, nextZoom: number) => {
    setZoom(nextZoom);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setViewport({
      min_longitude: Math.max(-180, bounds.getWest()).toFixed(4), min_latitude: Math.max(-90, bounds.getSouth()).toFixed(4),
      max_longitude: Math.min(180, bounds.getEast()).toFixed(4), max_latitude: Math.min(90, bounds.getNorth()).toFixed(4),
    }), 250);
  }, []);
  const truncated = Object.entries(loaded).filter(([, row]) => row.truncated).map(([kind]) => placeKindLabel(kind));
  const camera = useMemo(() => clusterCamera ?? (current && hasCoordinates(current) ? { center: [current.longitude, current.latitude] as [number, number], zoom: Math.max(zoom, 11) } : undefined), [current, clusterCamera]); // eslint-disable-line react-hooks/exhaustive-deps

  return <section className="map-workbench" aria-label="교통 장소 지도">
    {!embedded ? <div className="map-filter-bar">
      <ToggleGroup multiple variant="outline" className="flex-wrap" aria-label="장소 종류" value={kinds} onValueChange={(values) => { setKinds(values.filter((value): value is PlaceKind => KINDS.includes(value as PlaceKind))); setSelected(null); }}>{KINDS.map((kind) => <ToggleGroupItem key={kind} value={kind}><PlaceIcon kind={kind} />{placeKindLabel(kind)}</ToggleGroupItem>)}</ToggleGroup>
      <FieldGroup className="grid grid-cols-1 items-end gap-3 sm:grid-cols-2 xl:grid-cols-4"><Field><FieldLabel htmlFor={`${controlId}-query`}>장소 검색</FieldLabel><Input id={`${controlId}-query`} type="search" value={query} onChange={(event) => { setQuery(event.target.value); setSelected(null); }} placeholder="이름·브랜드·노선" /></Field>
      <Field><FieldLabel htmlFor={`${controlId}-source`}>데이터 출처</FieldLabel><NativeSelect id={`${controlId}-source`} value={source} onChange={(event) => { setSource(event.target.value); setSelected(null); }}><NativeSelectOption value="">모든 출처</NativeSelectOption>{sources.map((value) => <NativeSelectOption key={value} value={value}>{collectionSourceLabel(value)}</NativeSelectOption>)}</NativeSelect></Field>
      <Field><FieldLabel htmlFor={`${controlId}-product`}>표시 유종</FieldLabel><NativeSelect id={`${controlId}-product`} value={product} onChange={(event) => { setProduct(event.target.value); setSelected(null); }}><NativeSelectOption value="">전체 유종</NativeSelectOption>{["B027", "D047", "B034", "K015", "C004"].map((code) => <NativeSelectOption key={code} value={code}>{fuelProductLabel(code)}</NativeSelectOption>)}</NativeSelect></Field>
      <ViewSwitch value={view} onChange={setView} /></FieldGroup>
    </div> : <ViewSwitch value={view} onChange={setView} />}
    <div className="map-feedback" role="status">
      {pending.length ? <span>{pending.map(placeKindLabel).join("·")} 조회 중… </span> : null}
      <span>{items.length}곳 표시 · {cluster ? "축척·화면 밀도에 따라 묶음 표시" : "가까운 장소만 묶음 표시"}</span>
      {truncated.length ? <p>{truncated.join("·")} 일부를 표시합니다(종류별 최대 {perKindLimit}곳). 확대해 주세요. 묶음 수는 현재 불러온 장소 수입니다.</p> : null}
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
        unsupportedTileFallback={{ label: "지도를 불러오지 못했습니다." }} zoom={7}>
        <ClusterLayer points={groupedPoints} radius={cluster ? (product ? 80 : 110) : 60} maxZoom={19}
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
          renderMarker={(point) => <MapMarker key={point.id} point={point as MapPoint} product={product} onSelect={selectPlace} selected={false} />} />
        {selectedPoint ? <MapMarker point={selectedPoint} product={product} onSelect={selectPlace} selected /> : null}
      </VWorldMapView> : <div className="map-place-list">{items.map((place) => <button type="button" className="place-row" key={keyOf(place)} aria-pressed={current ? keyOf(current) === keyOf(place) : false} onClick={() => selectPlace(place)}><PlaceIcon kind={place.kind} /><span><strong>{place.name}</strong><small>{place.line_names.join(" · ") || place.brand_name || place.subtitle || placeKindLabel(place.kind)}</small>{!hasCoordinates(place) ? <small>좌표 미등록</small> : null}</span></button>)}</div>}
      </div>{!embedded ? <aside className="transport-map-detail weather-inspector" ref={detail} tabIndex={-1} aria-label="선택 장소 상세">
        <FieldGroup className="mb-4"><Field><FieldLabel htmlFor={`${controlId}-place`}>장소 목록에서 선택</FieldLabel><NativeSelect id={`${controlId}-place`} value={current ? keyOf(current) : ""} onChange={(event) => { const place = items.find((item) => keyOf(item) === event.target.value); if (place) selectPlace(place); }}><NativeSelectOption value="">장소 선택</NativeSelectOption>{items.map((place) => <NativeSelectOption key={keyOf(place)} value={keyOf(place)}>{placeKindLabel(place.kind)} · {place.name}</NativeSelectOption>)}</NativeSelect></Field></FieldGroup>
        {current ? <PlaceInspector key={keyOf(current)} place={current} onClose={() => { setSelected(null); detail.current?.querySelector("select")?.focus(); }} /> : <Empty><EmptyHeader><EmptyDescription>지도나 목록에서 장소를 선택하면 가격·노선·출도착·편의정보를 확인할 수 있습니다.</EmptyDescription></EmptyHeader></Empty>}
      </aside> : null}
    </div>
  </section>;
}
