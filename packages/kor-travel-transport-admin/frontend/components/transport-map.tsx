"use client";

import { vworldApiKey } from "@/lib/vworld-presentation";

import { toast } from "sonner";
import { refreshPublicFuel, type FuelRefreshBounds, type FuelRefreshRequest } from "@/lib/public-fuel";
import { useCallback, useEffect, useId, useMemo, useRef, useState, type CSSProperties, type RefObject, type ReactNode, type MouseEvent as ReactMouseEvent } from "react";
import { ClusterLayer, VWorldMapView, type ClusterPoint, type MapLibreMap } from "vworld-map-web";
import { setWorkerUrl } from "maplibre-gl";
import { clusterAtScale, dateTime, hasCoordinates, hasFuelPrice, TransportError, transportGet, type Place, type PlaceKind } from "@/lib/journey";
import { collectionSourceLabel, fuelProductLabel, placeKindLabel } from "@/lib/transport-presentation";
import { placeMarkerColor, placeMarkerStyle, priceMarkerLabel, priceSpeech } from "@/lib/place-marker-style";
import { FuelPriceStatus, FuelViewportSummary, type FuelViewportStatistics } from "@/components/fuel-statistics";
import type { FuelAreaChoice } from "@/components/public-fuel-controls";
import type { FuelCenterSigungu, FuelViewportSigungu } from "@/lib/fuel-price-distribution";
import { MAP_FALLBACK_IMAGE } from "@/lib/map-fallback";
import { cn } from "@/lib/utils";
import { CameraRequest, ClusterBubble, MapMarkerButton, MapUnavailable, MarkerBadge, OverlapPopup, useVWorldBasemapHealth, ZoomButtons, type CameraTarget } from "./map-overlays";
import { PlaceIcon } from "./journey-controls";
import { FuelCertificationMarks } from "./fuel-certification";
import { fuelCertifications } from "@/lib/fuel-certification";
import { InfoButton } from "./info-button";
import { PlaceInspector } from "./place-inspector";
import { FuelBrandIcon } from "./fuel-brand-icon";
import { fuelBrand } from "@/lib/fuel-brands";
import { MapDetailOverlay, MapFilterBar, MapFilterField, MapFilterPanel, MapKindFilter, MapStage, MapWorkspace, MapTabs as Tabs, MapTabPanel as TabsContent, MapViewTabs, type MapViewportReadout } from "@kor-travel/ui/map-controls";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { FilterCombobox } from "./filter-combobox";
import { railLines } from "@/lib/rail-line-style";
import { layoutFuelRegionCards } from "@/lib/fuel-region-layout";
import { loadWithTransientRetry } from "@/lib/place-retry";

type MapPoint = { id: string; lngLat: [number, number]; place: Place };
type Viewport = { min_longitude: string; min_latitude: string; max_longitude: string; max_latitude: string };
type ObservedFuelViewport = { exact: FuelRefreshBounds; query: Viewport; zoom: number };
type MapCluster = { longitude: number; latitude: number; count: number; kind_counts: Partial<Record<PlaceKind, number>> };
type FuelRegion = { region_key: string; label: string; product_code: string; average_price: number; station_count: number; longitude: number; latitude: number };
function FuelRegionLabel({ label, prices, products = FUEL_PRODUCTS, showProductName = true }: { label: string; prices: Map<string, FuelRegion>; products?: readonly string[]; showProductName?: boolean }) {
  return <span className="fuel-region-label"><strong>{label}<small>원/L</small></strong>
    {products.map(code => { const price = prices.get(code); return <span key={code} className="fuel-region-price">{showProductName ? <span>{fuelProductLabel(code)}</span> : null}<b>{price ? Math.round(price.average_price).toLocaleString("ko-KR") : "미제공"}</b></span>; })}
  </span>;
}
type PublicFuelControls = {
  products: string[];
  onProductsChange: (products: string[]) => void;
  refreshEnabled?: boolean;
  /** 공개 유가 서버 필터 query(lib/public-fuel-filters.ts `publicFuelFilterQuery`). */
  filterQuery?: string;
  /** 지역 이동 열기. center는 지금 지도 중심 [경도, 위도](지역 칩이 없을 때 대화상자가 미리 고를 시군구를 찾는다). */
  onOpenRegion?: (current?: FuelAreaChoice, opener?: HTMLElement | null, center?: [number, number]) => void;
} & Pick<PublicFuelSummary, "filters" | "onFiltersChange" | "selectedRegion" | "onClearRegion">;

type PublicFuelSummary = NonNullable<Parameters<typeof FuelViewportSummary>[0]["publicFuel"]>;

type PlaceResponse = { fuel_regions?: FuelRegion[]; fuel_statistics?: FuelViewportStatistics[]; fuel_viewport_sigungu?: FuelViewportSigungu[]; fuel_viewport_sigungu_total?: number; fuel_center_sigungu?: FuelCenterSigungu | null; items: Place[]; total: number; truncated: boolean; clustered?: boolean; kind_totals?: Partial<Record<PlaceKind, number>>; clusters?: MapCluster[]; available_sources?: string[]; fuel_prices_stale?: boolean; fuel_prices_last_refreshed_at?: string | null };
const FUEL_PRODUCTS = ["B027", "D047", "B034", "C004", "K015"] as const;
const KINDS: PlaceKind[] = ["fuel_station", "rail_station", "ferry_port", "bus_terminal", "airport", "rest_area", "highway_incident", "public_parking_lot"];
const REFERENCE_LIST_KINDS = new Set<string>(["ferry_port", "bus_terminal", "public_parking_lot"]);
const TRANSPORT_KINDS: PlaceKind[] = ["rail_station", "ferry_port", "bus_terminal", "airport", "rest_area", "highway_incident", "public_parking_lot"];
const MAP_CLUSTER_CACHE_TTL_MS = 20_000;
const MAP_CLUSTER_CACHE_MAX = 8;
const CLUSTER_NUMBER_FORMATTER = new Intl.NumberFormat("ko-KR", { notation: "compact", maximumFractionDigits: 1 });
const DEFAULT_VIEWPORT: Viewport = { min_longitude: "124", min_latitude: "32", max_longitude: "132", max_latitude: "39" };
const keyOf = (place: Place) => `${place.kind}:${place.id}`;
const fuelMapScope = (view: Viewport, zoom: number, products: string) =>
  `${view.min_longitude},${view.min_latitude},${view.max_longitude},${view.max_latitude}|${Math.floor(zoom)}|${products}`;
const withinBounds = ([longitude, latitude]: [number, number], bounds: Viewport | FuelRefreshBounds) =>
  longitude >= Number(bounds.min_longitude) && longitude <= Number(bounds.max_longitude)
  && latitude >= Number(bounds.min_latitude) && latitude <= Number(bounds.max_latitude);
const canRestoreFocus = (element: HTMLElement | null): element is HTMLElement => Boolean(element?.isConnected && element !== document.body && element.getClientRects().length && !element.closest("[inert], [hidden]") && getComputedStyle(element).visibility !== "hidden");


function quantizeViewport(bounds: { min_longitude: number; min_latitude: number; max_longitude: number; max_latitude: number }, zoom: number): Viewport {
  const precision = zoom >= 14 ? 4 : zoom >= 11 ? 3 : zoom >= 8 ? 2 : 1;
  const factor = 10 ** precision;
  return {
    min_longitude: (Math.floor(Math.max(-180, bounds.min_longitude) * factor) / factor).toFixed(precision),
    min_latitude: (Math.floor(Math.max(-90, bounds.min_latitude) * factor) / factor).toFixed(precision),
    max_longitude: (Math.ceil(Math.min(180, bounds.max_longitude) * factor) / factor).toFixed(precision),
    max_latitude: (Math.ceil(Math.min(90, bounds.max_latitude) * factor) / factor).toFixed(precision),
  };
}

// Next.js는 정적 참조만 번들에 넣는다. 빈 값·자리표시자는 라이브러리 `missing-api-key` 대체 화면으로 간다.
const VWORLD_KEY = vworldApiKey(process.env.NEXT_PUBLIC_VWORLD_API_KEY);
// Map과 같은 배선: v6의 worker와 shared를 predev/prebuild에서 함께 복사한다.
setWorkerUrl("/maplibre/maplibre-gl-worker.mjs");

// Map 지도와 같은 마커: 24px 원형 배지(maki 글리프 + 팔레트 색). 이름은 배지에 쓰지 않고 hover 제목과
// 접근 이름으로만 준다. 주유소 가격은 Map 가격 마커처럼 배지 오른쪽의 흰 라벨에 한 줄씩 쓴다.
function MapMarker({ point, onSelect, selected, products, showProductName = true }: { point: MapPoint; onSelect: (place: Place) => void; selected: boolean; products: string[]; showProductName?: boolean }) {
  const place = point.place;
  const { markerIcon, markerColor } = placeMarkerStyle(place.kind);
  const priceLabel = place.kind === "fuel_station" ? priceMarkerLabel(place.prices, products, showProductName) : null;
  const title = [place.name, place.brand_name, ...(place.kind === "fuel_station" ? fuelCertifications(place).map((item) => item.label) : []), place.kind === "rail_station" ? place.line_names.join("·") : null].filter(Boolean).join(" · ");
  const ariaLabel = [placeKindLabel(place.kind), place.name, place.kind === "fuel_station" ? fuelBrand(place.brand_code, place.brand_name).name : null, ...(place.kind === "fuel_station" ? fuelCertifications(place).map((item) => item.label) : []), place.line_names.join(" · "), priceLabel ? priceSpeech(place.prices, products) : null, "상세 보기"].filter(Boolean).join(" ");
  // 선택 마커는 묶음 원(z 3) 위(z 4)에 그리되 포인터는 통과시켜 같은 좌표의 묶음 원도 눌린다.
  return <MapMarkerButton lngLat={point.lngLat} interactionId={point.id} zIndex={selected ? 4 : undefined} passThrough={selected} pressed={selected}
    className={cn("transport-map-marker", place.kind, selected && "is-selected")}
    title={priceLabel ? `${title} ${priceLabel.replace(/\n/g, " ")}` : title} ariaLabel={ariaLabel} onClick={() => onSelect(place)}>
    {place.kind === "fuel_station" ? <span className="fuel-marker-brand"><FuelBrandIcon code={place.brand_code} name={place.brand_name} className="fuel-brand-marker" /><FuelCertificationMarks place={place} /></span> : place.kind === "rail_station" ? <span className="rail-map-label"><span className="rail-map-lines">{railLines(place).map(line => <span key={line.name} className="rail-line-badge" style={{"--rail-line-color":line.color} as CSSProperties}>{line.label}</span>)}</span><span className="rail-map-name">{place.name}</span></span> : <MarkerBadge markerIcon={markerIcon} markerColor={markerColor} selected={selected} />}
    {priceLabel ? <span className="map-marker-price" style={{ "--marker-color": placeMarkerColor(place.kind) } as CSSProperties}>{priceLabel}</span> : null}
  </MapMarkerButton>;
}

type MapCamera = { center: [number, number]; zoom: number };
const DEFAULT_CAMERA: MapCamera = { center: [127.8, 36.2], zoom: 7 };

// 지도 mount 때 한 번 잡은 카메라만 VWorldMapView에 넘긴다. 실시간 카메라를 center/zoom prop으로 되먹이면 SDK가
// prop 변화마다 pending camera(기본 smooth easeTo 300ms)를 만들어, 연속 확대나 묶음·장소 연속 선택에서 옛 위치로
// 되돌아가거나 흔들린다. 목록→지도 재mount 때는 그때의 마지막 카메라로 다시 시작한다.
function MountCamera({ camera, children }: { camera: MapCamera; children: (camera: MapCamera) => ReactNode }) {
  const [initial] = useState(camera);
  return children(initial);
}

// Map `showCoincidentPopup`과 같은 겹친 지점 팝업: 제목·개수 칩과 색 점·종류 배지·이름 행.
function OverlapList({ places, onSelect, listRef }: { places: Place[]; onSelect: (place: Place) => void; listRef: RefObject<HTMLElement | null> }) {
  return <section ref={listRef} className="min-w-62 text-[13px] leading-snug text-text-primary" aria-label="겹친 장소 선택">
    <header className="flex items-center justify-between gap-2.5 pt-0.5 pb-2.5"><span className="text-[13px] font-extrabold">겹친 지점</span><span className="shrink-0 rounded-full border border-brand-tint bg-brand-tint px-2 py-1 text-2xs leading-none font-extrabold text-brand">{places.length}개</span></header>
    <div className="flex max-h-65 flex-col gap-1 overflow-y-auto">{places.map((place) => <button type="button" key={keyOf(place)} aria-label={place.name} className="flex min-h-10.5 w-full items-center gap-2 rounded-control border border-border bg-card px-2.5 py-2 text-left text-text-primary hover:border-(--marker-color) hover:bg-surface-subtle focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus" style={{ "--marker-color": placeMarkerColor(place.kind) } as CSSProperties} onClick={() => onSelect(place)}>
      <span className="size-2.25 shrink-0 rounded-full bg-(--marker-color) shadow-[0_0_0_3px_color-mix(in_srgb,var(--marker-color)_13%,transparent)]" aria-hidden="true" /><span className="shrink-0 rounded-full bg-surface-subtle px-1.5 py-1 text-[10px] leading-none font-extrabold text-text-secondary" aria-hidden="true">{placeKindLabel(place.kind)}</span><span className="min-w-0 flex-1 truncate font-semibold">{place.name}</span>
    </button>)}</div>
  </section>;
}

export function TransportMap({ places, selectedPlace, onSelectPlace, mode = "all", details, detailTitle, onCloseDetails, focusRevision = 0, layers, detailKey, mapFeatureCount = 0, listFeatureCount = 0, listCount, listContent, listPlaces = true, toolbar, feedback, filterSummary, view: controlledView, onViewChange, load = transportGet, mapOnly = false, publicFuel }: { places?: Place[]; selectedPlace?: Place | null; onSelectPlace?: (place: Place) => void; mode?: "all" | "transport" | "fuel"; details?: ReactNode; detailTitle?: ReactNode; onCloseDetails?: () => void; focusRevision?: number; layers?: ReactNode; detailKey?: string; mapFeatureCount?: number; listFeatureCount?: number; listCount?: number; listContent?: ReactNode; listPlaces?: boolean; toolbar?: ReactNode; feedback?: ReactNode; filterSummary?: string; view?: "map" | "list"; onViewChange?: (view: "map" | "list") => void; load?: typeof transportGet; mapOnly?: boolean; publicFuel?: PublicFuelControls }) {
  const { workspace, embedded, detail, detailOpener, query, selectedSources, products, kinds, allowedKinds, filtersExpanded, setFiltersExpanded, filterTrigger, setKinds, setSelected, controlId, queryInput, setQuery, setSelectedSources, sources, setProducts, view, setView, mapViewport, items, serverClustered, serverTotal, serverClusters, visiblePoints, pending, mapContainer, setMapUnavailableMessage, basemap, moved, camera, setClusterPlaces, setClusterCamera, zoom, setCameraRequest, groupedPoints, cluster, overlapOpener, setClusterAnchor, clusterList, selectPlace, selectedPoint, clusterPlaces, clusterAnchor, closeOverlap, current, loaded, mapDetail, listDetail, dismissEmbeddedDetail, closeDetail, setReload, focusFilters, failed, mapUnavailableMessage, fuelDetailScopeExpanded, setFuelDetailScopeExpanded, regionMarkers, railOnly, partialListKinds, perKindLimit, searchQuery, refreshViewport, fuelFreshness } = useTransportMap({ places, selectedPlace, onSelectPlace, mode, details, detailTitle, onCloseDetails, focusRevision, layers, detailKey, mapFeatureCount, listFeatureCount, listCount, listContent, listPlaces, toolbar, feedback, filterSummary, view: controlledView, onViewChange, load, fuelProducts: publicFuel?.products, fuelFilterQuery: publicFuel?.filterQuery });
  const detailPanel = (panelView: "map" | "list") => (embedded ? details : current) ? <MapInspector panelView={panelView} load={load} embedded={embedded} details={details} mapDetail={mapDetail} listDetail={listDetail} detailTitle={detailTitle} current={current} dismissEmbeddedDetail={dismissEmbeddedDetail} closeDetail={closeDetail} loaded={loaded} setView={setView} setCameraRequest={setCameraRequest} setSelected={setSelected} setReload={setReload} focusFilters={focusFilters} publicFuel={publicActions.detail} /> : null;
const status = <MapQueryStatus feedback={feedback} failed={failed} setReload={setReload} basemap={basemap} view={view} mapUnavailableMessage={mapUnavailableMessage} />;
const {refreshing, refreshPrices} = usePublicFuelRefresh(publicFuel?.refreshEnabled, setReload);
const publicActions = publicFuelActions({
  controls: publicFuel, bounds: refreshViewport, current, refreshing, refreshPrices,
  freshness: fuelFreshness, loading: pending.length > 0, failed: failed.length > 0, clearSelection: () => setSelected(null),
  mapCenter: mapViewport ? [mapViewport.longitude, mapViewport.latitude] : DEFAULT_CAMERA.center,
});
const summary = <MapStatusSummary load={load} publicFuel={publicActions.summary} status={status} embedded={embedded} mode={mode} loaded={loaded} pending={pending} failed={failed} current={current} fuelDetailScopeExpanded={fuelDetailScopeExpanded} setFuelDetailScopeExpanded={setFuelDetailScopeExpanded} />;
return <section className="map-workbench" aria-label={mode === "fuel" ? "유가 지도" : "교통 장소 지도"}>
    <MapWorkspace expandable={!mapOnly} ref={workspace} className={embedded ? "embedded-map" : "transport-map-workspace"} onClickCapture={(event) => captureDetailOpener(event, detail, detailOpener)}>
    {!publicFuel && (toolbar || !embedded) ? <MapSearchFilters filterSummary={filterSummary} query={query} selectedSources={selectedSources} products={products} kinds={kinds} allowedKinds={allowedKinds} filtersExpanded={filtersExpanded} setFiltersExpanded={setFiltersExpanded} filterTrigger={filterTrigger} toolbar={toolbar} mode={mode} setKinds={setKinds} setSelected={setSelected} controlId={controlId} queryInput={queryInput} setQuery={setQuery} setSelectedSources={setSelectedSources} sources={sources} setProducts={setProducts} /> : null}
    <Tabs value={view} onValueChange={(value) => { if (value === "map" || value === "list") { setView(value); setFiltersExpanded(false); } }} className="min-h-0">
    {!mapOnly ? <MapResultTabs mapViewport={mapViewport} view={view} listCount={listCount} listPlaces={listPlaces} items={items} listFeatureCount={listFeatureCount} mapFeatureCount={mapFeatureCount} serverClustered={serverClustered} serverTotal={serverTotal} visiblePoints={visiblePoints} pending={pending} partialListKinds={partialListKinds} perKindLimit={perKindLimit} searchQuery={searchQuery} /> : null}
    <TabsContent className="min-h-0" value="map"><MapStage className={mode === "fuel" ? "fuel-map-stage" : undefined} summary={summary} detail={detailPanel("map")}><TransportMapCanvas mapContainer={mapContainer} mapViewport={mapViewport} setMapUnavailableMessage={setMapUnavailableMessage} basemap={basemap} moved={moved} camera={camera} layers={layers} serverClustered={serverClustered} serverClusters={serverClusters} setClusterPlaces={setClusterPlaces} setClusterCamera={setClusterCamera} zoom={zoom} setCameraRequest={setCameraRequest} groupedPoints={groupedPoints} cluster={cluster} products={products} overlapOpener={overlapOpener} setClusterAnchor={setClusterAnchor} clusterList={clusterList} selectPlace={selectPlace} selectedPoint={selectedPoint} clusterPlaces={clusterPlaces} clusterAnchor={clusterAnchor} closeOverlap={closeOverlap} regionMarkers={regionMarkers} railOnly={railOnly} fuelOnly={mode === "fuel"} publicFuel={Boolean(publicFuel)} />
      </MapStage>
    </TabsContent>
    {!mapOnly ? <TabsContent className="min-h-0 data-[state=inactive]:hidden" value="list" forceMount><MapStage view="list" detail={view === "list" ? detailPanel("list") : null}><div className="map-primary"><MapPlaceRows status={status} listContent={listContent} listPlaces={listPlaces} items={items} current={current} selectPlace={selectPlace} /></div></MapStage></TabsContent> : null}
    <MapFuelGuidance embedded={embedded} mode={mode} view={view} kinds={kinds} loaded={loaded} />
    </Tabs>
    </MapWorkspace>
  </section>;
}

/** 지도 범위 업데이트를 지금 못 쓰는 이유(가격 아이콘 툴팁). 범위가 정해지지 않은 까닭이 조회 중·실패면 그것을 먼저 말한다. */
function viewportRefreshBlock(enabled: boolean | undefined, filterQuery: string | undefined, bounds: FuelRefreshBounds | undefined, loading: boolean, failed: boolean) {
  if (!enabled) return "disabled" as const;
  if (filterQuery) return "filters" as const;
  if (bounds) return undefined;
  return failed ? "failed" as const : loading ? "loading" as const : "range" as const;
}

function publicFuelActions({
  controls, bounds, current, refreshing, refreshPrices, freshness, loading, failed, clearSelection, mapCenter,
}: {
  controls?: PublicFuelControls; bounds?: FuelRefreshBounds; current?: Place | null;
  refreshing: boolean; refreshPrices: (target: FuelRefreshRequest) => Promise<void>;
  freshness?: { stale: boolean; lastRefreshedAt?: string | null }; loading: boolean; failed: boolean;
  clearSelection: () => void; mapCenter: [number, number];
}) {
  if (!controls) return {};
  const { products, refreshEnabled } = controls;
  // 필터를 켠 화면의 일괄 업데이트는 서버가 필터 없이 화면 안 전체 주유소 수로 판단해 거절할 수 있어 제공하지 않는다
  // (주유소 상세의 개별 업데이트는 그대로).
  const refreshViewport = refreshEnabled && bounds && !controls.filterQuery ? () => {
    void refreshPrices({ viewport: { ...bounds, product_codes: products } });
  } : undefined;
  const refreshStation = refreshEnabled && current?.kind === "fuel_station" ? () => {
    void refreshPrices({ station_id: current.id });
  } : undefined;
  const summary: PublicFuelSummary = {
    products,
    onProductsChange: values => { clearSelection(); controls.onProductsChange(values); },
    onRefresh: freshness?.stale ? refreshViewport : undefined,
    refreshing,
    priceFreshness: freshness,
    refreshBlocked: viewportRefreshBlock(refreshEnabled, controls.filterQuery, bounds, loading, failed),
    filterQuery: controls.filterQuery,
    filters: controls.filters,
    // 필터도 유종과 같은 규칙이다: 조건이 바뀌면 그 주유소가 지도에서 빠질 수 있어 열린 상세를 닫는다.
    onFiltersChange: controls.onFiltersChange ? values => { clearSelection(); controls.onFiltersChange?.(values); } : undefined,
    selectedRegion: controls.selectedRegion,
    onClearRegion: controls.onClearRegion,
    onOpenRegion: controls.onOpenRegion ? (region, opener) => controls.onOpenRegion?.(region, opener, mapCenter) : undefined,
  };
  return { summary, detail: { onRefresh: refreshStation, refreshing, products, filterQuery: controls.filterQuery } };
}

function usePublicFuelRefresh(enabled: boolean | undefined, setReload: ReturnType<typeof useTransportMap>["setReload"]) {
  const [refreshing, setRefreshing] = useState(false);
  const refreshInFlight = useRef(false);

  async function refreshPrices(target: FuelRefreshRequest) {
    if (!enabled || refreshInFlight.current) return;
    refreshInFlight.current = true;
    setRefreshing(true);
    try {
      const { results } = await refreshPublicFuel(target);
    if (!results.length) {
      toast.info("현재 범위에 업데이트할 주유소가 없습니다.");
      return;
    }
      const successful = results.filter(({ status }) => status === "updated" || status === "unchanged");
      if (!successful.length) {
        if (results.some(({ status }) => status === "cooldown")) {
          setReload(value => value + 1);
          toast.info("최근 갱신 요청이 있었습니다. 잠시 뒤 다시 시도해 주세요.");
        } else if (results.some(({ status }) => status === "rate_limited")) {
          toast.info("잠시 뒤 유가 업데이트를 다시 시도해 주세요.");
        } else {
          toast.error("유가를 업데이트하지 못했습니다.");
        }
        return;
      }
      setReload(value => value + 1);
      if (successful.length !== results.length) toast.warning(`주유소 ${successful.length}곳 업데이트 완료 · 일부 실패`);
      else if (successful.every(({ status }) => status === "unchanged")) toast.success("유가 업데이트 완료 · 가격 변화 없음");
      else toast.success("유가 업데이트 완료");
    } catch (error) {
      toast.error(error instanceof TransportError ? error.message : "유가를 업데이트하지 못했습니다.");
    } finally {
      refreshInFlight.current = false;
      setRefreshing(false);
    }
  }
  return { refreshing, refreshPrices };
}

function MapStatusSummary({ status, embedded, mode, loaded, pending, failed, current, fuelDetailScopeExpanded, setFuelDetailScopeExpanded, publicFuel, load }: { status: ReactNode; mode: "all" | "transport" | "fuel"; publicFuel?: PublicFuelSummary; load: typeof transportGet } & Pick<ReturnType<typeof useTransportMap>, "embedded" | "loaded" | "pending" | "failed" | "current" | "fuelDetailScopeExpanded" | "setFuelDetailScopeExpanded">) {
  return <>
    <div className="map-feedback">{status}</div>
    {!embedded && mode === "fuel" ? <FuelViewportSummary publicFuel={publicFuel ? {
      ...publicFuel, load, sigungu: loaded.fuel_station?.fuel_viewport_sigungu ?? [], center: loaded.fuel_station?.fuel_center_sigungu,
    } : undefined} items={loaded.fuel_station?.fuel_statistics ?? []} pending={pending.length > 0} failed={failed.length > 0}
      detailOpen={Boolean(current)} detailExpanded={fuelDetailScopeExpanded} onDetailExpandedChange={setFuelDetailScopeExpanded}
      pricesStale={loaded.fuel_station?.fuel_prices_stale} pricesLastRefreshedAt={loaded.fuel_station?.fuel_prices_last_refreshed_at} /> : null}
  </>;
}

function MapFuelGuidance({ embedded, mode, view, kinds, loaded }: { mode: "all" | "transport" | "fuel" } & Pick<ReturnType<typeof useTransportMap>, "embedded" | "view" | "kinds" | "loaded">) {
  return !embedded && !(mode === "fuel" && view === "map") ? <FuelMapGuidance kinds={kinds} loaded={loaded} /> : null;
}

// 숨은 panel의 자식은 opener로 저장하지 않아 닫기 뒤 보이는 컨트롤로 복귀한다.
function captureDetailOpener(event: ReactMouseEvent<HTMLElement>, detail: RefObject<HTMLElement | null>, openerRef: RefObject<HTMLElement | null>) {
  const opener = event.target instanceof Element ? event.target.closest<HTMLElement>("button, a") : null;
  if (opener && !detail.current?.contains(opener) && (opener.closest(".map-place-list") || opener.closest("[data-interaction-id]"))) openerRef.current = opener;
}


function truncatedListKinds(embedded: boolean, view: "map" | "list", kinds: PlaceKind[], loaded: Record<string, PlaceResponse>) {
  return !embedded && view === "list" ? kinds.filter(kind => loaded[kind]?.truncated === true) : [];
}

const mapClusterDetailZoom = (mode: "all" | "transport" | "fuel") => mode === "fuel" ? 10 : 11;
const fuelQueryDetailZoom = (mode: "all" | "transport" | "fuel") => mode === "fuel" ? 10 : 12;
// 공개 유가 지역 카드의 단위: 서버는 zoom 8 미만이면 시/도, 그 위로는 시군구 카드를 내고, 상세 zoom부터는 카드가 없다.
const publicFuelRegionBucket = (zoom: number) => Math.floor(zoom) < 8 ? "sido" : Math.floor(zoom) < fuelQueryDetailZoom("fuel") ? "sigungu" : "detail";
const NO_FUEL_REGIONS: FuelRegion[] = [];
// 공개 유가: 지역 이동(fitBounds)·확대처럼 카드 단위(시/도 ↔ 시군구 ↔ 상세)가 바뀌면 새 응답이 올 때까지 옛 단위의 카드를
// 그리지 않는다. 남겨 두면 새 화면 밖에 있는 옛 카드가 화면 가장자리로 밀려 몰린다. 관리 화면은 받은 그대로다.
function currentFuelRegions(loaded: { rows: FuelRegion[]; zoom?: number }, isPublicFuel: boolean, live: MapViewportReadout | null, settledZoom: number) {
  if (!isPublicFuel || loaded.zoom === undefined) return loaded.rows;
  const liveZoom = live ? live.zoom : settledZoom;
  return publicFuelRegionBucket(liveZoom) === publicFuelRegionBucket(loaded.zoom) ? loaded.rows : NO_FUEL_REGIONS;
}
const mapKindParameter = (mode: "all" | "transport" | "fuel") => mode === "fuel" ? "kind" : "kinds";

function partitionMapPayload(payload: PlaceResponse, kinds: string[], publicFuel: boolean) {
  const byKind: Record<string, PlaceResponse> = {};
  for (const kind of kinds) {
    const items = payload.items.filter(item => item.kind === kind);
    const total = payload.kind_totals?.[kind as PlaceKind] ?? items.length;
    byKind[kind] = {
      ...payload, items, total,
      truncated: !payload.clustered && (total > items.length || (publicFuel && payload.truncated)),
    };
  }
  return byKind;
}

function mapPlaceSearch({
  kinds, viewport, zoom, perKindLimit, mode, includeSources, sources, query, products, publicFuel, filterQuery = "",
}: {
  kinds: string[]; viewport: Viewport; zoom: number; perKindLimit: number;
  mode: "all" | "transport" | "fuel"; includeSources: boolean;
  sources: string; query: string; products: string; publicFuel: boolean; filterQuery?: string;
}) {
  const search = new URLSearchParams({
    [mapKindParameter(mode)]: kinds.join(","),
    limit: String(Math.min(900, perKindLimit * kinds.length)),
    zoom: String(Math.floor(zoom)),
    include_sources: String(includeSources),
    ...viewport,
  });
  if (sources) search.set("sources", sources);
  if (query.trim()) search.set("query", query.trim());
  if (products && kinds.includes("fuel_station") && (publicFuel || zoom >= fuelQueryDetailZoom(mode))) {
    search.set("product_codes", products);
  }
  if (mode === "fuel") search.set("include_fuel_statistics", "true");
  // 화면 안 시군구 칩은 공개 유가 화면에서만 요청한다(관리 지도 응답은 그대로).
  if (publicFuel && kinds.includes("fuel_station")) {
    search.set("include_viewport_sigungu", "true");
    // 지역 칩 기본값(지도 중심 시군구). 조회 범위(정밀도 격자로 바깥 반올림)의 가운데라 실제 중심과 반 칸 이내이고,
    // 범위에서만 나오므로 지도를 옮겨도 요청 수·응답 캐시 키는 지금과 같다.
    // 지도가 첫 이동(moveend)을 알리기 전의 기본 범위(124~132, 32~39)는 실제 카메라 중심(127.8, 36.2)과 대칭이 아니라
    // 묻지 않는다. 그동안(또는 지도를 그리지 못하면 계속) 칩은 "화면에서 주유소가 가장 많은 시군구"로 대신한다.
    if (viewport !== DEFAULT_VIEWPORT) {
      const center = viewportCenter(viewport);
      search.set("center_longitude", center.longitude);
      search.set("center_latitude", center.latitude);
    }
  }
  // 공개 유가 서버 필터: 마커·묶음·통계·지역 카드·시군구 칩이 같은 조건으로 계산된다.
  if (publicFuel && filterQuery) for (const [key, value] of new URLSearchParams(filterQuery)) search.set(key, value);
  return search;
}

function viewportCenter(viewport: Viewport) {
  const middle = (low: string, high: string) => ((Number(low) + Number(high)) / 2).toFixed(5);
  return { longitude: middle(viewport.min_longitude, viewport.max_longitude), latitude: middle(viewport.min_latitude, viewport.max_latitude) };
}

function filterTransportMapItems(items: Place[], sources: Set<string>, products: Set<string>, query: string) {
  const needle = query.trim().toLocaleLowerCase();
  return items.filter(item => {
    if (sources.size && !sources.has(item.source)) return false;
    if (needle && ![item.name, item.brand_name, item.address, item.subtitle, item.provider_id, ...item.line_names]
      .join(" ").toLocaleLowerCase().includes(needle)) return false;
    return !products.size || item.kind !== "fuel_station"
      || item.prices?.some(price => hasFuelPrice(price) && products.has(price.product_code));
  });
}

function publicSelectedFuelPlace(selected: Place | null, items: Place[], products: Set<string>) {
  if (!selected) return null;
  const loaded = items.find(item => keyOf(item) === keyOf(selected));
  if (loaded) return loaded;
  return !products.size || selected.prices?.some(price => hasFuelPrice(price) && products.has(price.product_code))
    ? selected : null;
}

function eligibleFuelViewport({
  bounds, loadedMapScope, productsKey, points, fuelResponse, serverClustered, pending, failed,
}: {
  bounds?: ObservedFuelViewport; loadedMapScope: string; productsKey: string; points: MapPoint[];
  fuelResponse?: PlaceResponse; serverClustered: boolean; pending: string[]; failed: string[];
}) {
  if (!bounds || !fuelResponse || fuelResponse.truncated || serverClustered || pending.length || failed.length) return undefined;
  if (loadedMapScope !== fuelMapScope(bounds.query, bounds.zoom, productsKey)) return undefined;
  const count = points.filter(point => withinBounds(point.lngLat, bounds.exact)).length;
  return count >= 1 && count < 10 ? bounds.exact : undefined;
}

function onlyRailStations(items: Place[]) {
  return items.length > 0 && items.every(item => item.kind === "rail_station");
}

// 조회·선택·요청 수명은 이 도메인 훅이, 아래 컴포넌트는 표현을 소유한다.
function useTransportMap({ places, selectedPlace, onSelectPlace, mode = "all", details, onCloseDetails, focusRevision = 0, detailKey, view: controlledView, onViewChange, load = transportGet, fuelProducts, fuelFilterQuery = "" }: { places?: Place[]; selectedPlace?: Place | null; onSelectPlace?: (place: Place) => void; mode?: "all" | "transport" | "fuel"; details?: ReactNode; detailTitle?: ReactNode; onCloseDetails?: () => void; focusRevision?: number; layers?: ReactNode; detailKey?: string; mapFeatureCount?: number; listFeatureCount?: number; listCount?: number; listContent?: ReactNode; listPlaces?: boolean; toolbar?: ReactNode; feedback?: ReactNode; filterSummary?: string; view?: "map" | "list"; onViewChange?: (view: "map" | "list") => void; load?: typeof transportGet; fuelProducts?: string[]; fuelFilterQuery?: string }) {
  const controlId = useId();
  const embedded = places !== undefined;
  const allowedKinds = mode === "fuel" ? ["fuel_station"] as PlaceKind[] : mode === "transport" ? TRANSPORT_KINDS : KINDS;
  const [initial] = useState(() => initialMapCamera(embedded));
  const [kinds, setKinds] = useState<PlaceKind[]>(allowedKinds);
  const [selectedSources, setSelectedSources] = useState<string[]>([]);
  const [localProducts, setProducts] = useState<string[]>([]);
  const products = fuelProducts ?? localProducts;
  const isPublicFuel = fuelProducts !== undefined;
  const [query, setQuery] = useState("");
  const [overlap, setOverlap] = useState<{ scope: string; places: Place[] }>({ scope: "", places: [] });

  const [clusterAnchor, setClusterAnchor] = useState<[number, number]>([127.8, 36.2]);
  const [clusterCamera, setClusterCamera] = useState<MapCamera | undefined>(initial.camera);
  const [cameraRequest, setCameraRequest] = useState(0);
  const clusterList = useRef<HTMLElement | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [localView, setLocalView] = useState<"map" | "list">("map");
  const view = controlledView ?? localView;
  const setView = (value: "map" | "list") => { setLocalView(value); onViewChange?.(value); };
  const [selected, setSelected] = useState<Place | null>(null);
  const { viewport, zoom, mapViewport, visibleBounds, mapSize, mapContainer, moved } = useTransportMapViewport(initial, view, isPublicFuel);
  const queryInput = useRef<HTMLInputElement | null>(null);
  const filterTrigger = useRef<HTMLButtonElement | null>(null);
  const workspace = useRef<HTMLDivElement | null>(null);
  const [filtersExpanded, setFiltersExpanded] = useState(false);
  const [fuelDetailScopeExpanded, setFuelDetailScopeExpanded] = useState(false);
  const basemap = useVWorldBasemapHealth();
  const [mapUnavailableMessage, setMapUnavailableMessage] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const selectedEntry = selectedPlace === undefined ? selected : selectedPlace;
  const kindsKey = kinds.join(",");
  const sourcesKey = selectedSources.join(",");
  const productsKey = products.join(",");
  // 공개 유가 서버 필터(셀프·상표 등)의 query 문자열. 관리 화면은 빈 문자열이다.
  const filterQuery = fuelFilterQuery;
  // 조회 이동은 선택 팝업을 보존하고 검색 조건의 정체가 바뀌면 파생 목록에서 제외한다.
  const overlapScope = `${kindsKey}|${sourcesKey}|${searchQuery}|${productsKey}|${filterQuery}|${view}|${mode}`;
  const clusterPlaces = overlap.scope === overlapScope ? overlap.places : [];
  const setClusterPlaces = (places: Place[]) => setOverlap({ scope: overlapScope, places });
  const perKindLimit = Math.min(300, Math.floor(900 / Math.max(1, kinds.length)));
  const { loaded, knownSources, fuelRegions, fuelFreshness, serverClusters, serverClustered, serverTotal, loadedMapScope, pending, failed } = useTransportMapResults({
    embedded, kindsKey, perKindLimit, viewport, zoom, reload, sourcesKey, searchQuery, productsKey, filterQuery, view, mode, isPublicFuel, load,
  });
  const regionMarkers = useFuelRegionCards({
    fuelRegions: currentFuelRegions(fuelRegions, isPublicFuel, mapViewport, zoom), mapContainer, view, serverClustered, mapViewport, mapSize,
    hideOffscreen: isPublicFuel,
  });
  const partialListKinds = truncatedListKinds(embedded, view, kinds, loaded);
  const sources = useMemo(() => [...new Set([...knownSources, ...(places ?? []).map((item) => item.source)])], [places, knownSources]);
  const all = useMemo(() => places ?? kinds.flatMap((kind) => loaded[kind]?.items ?? []), [places, kinds, loaded]);
  const sourceSet = useMemo(() => new Set(selectedSources), [selectedSources]);
  const productSet = useMemo(() => new Set(products), [products]);
  const items = useMemo(() => filterTransportMapItems(all, sourceSet, productSet, embedded ? query : ""),
    [all, embedded, query, sourceSet, productSet]);
  const points = useMemo<MapPoint[]>(() => items.filter(hasCoordinates).map((place) => ({ id: keyOf(place), lngLat: [place.longitude, place.latitude], place })), [items]);
  const visiblePoints = points.filter(point => withinBounds(point.lngLat, viewport));
  const current = isPublicFuel ? publicSelectedFuelPlace(selectedEntry, items, productSet) : selectedEntry;
  const refreshViewport = eligibleFuelViewport({
    bounds: visibleBounds, loadedMapScope, productsKey: filterQuery ? `${productsKey}|${filterQuery}` : productsKey, points, fuelResponse: loaded.fuel_station,
    serverClustered, pending, failed,
  });
  const cluster = !serverClustered && clusterAtScale(zoom, (Number(viewport.min_latitude) + Number(viewport.max_latitude)) / 2, visiblePoints.length, mapSize.width, mapSize.height, mapClusterDetailZoom(mode));
  const markerPoints = embedded ? points : visiblePoints;
  const railOnly = onlyRailStations(items);
  const groupedPoints = useMemo(() => current ? markerPoints.filter((point) => point.id !== keyOf(current)) : markerPoints, [markerPoints, current]);
  const selectedPoint = points.find((point) => current && point.id === keyOf(current))
    ?? (current && hasCoordinates(current) ? { id: keyOf(current), lngLat: [current.longitude, current.latitude] as [number, number], place: current } : undefined);
  const focusMapControl = () => (mapContainer.current?.querySelector<HTMLElement>(".maplibregl-canvas") ?? (filterTrigger.current?.getClientRects().length ? filterTrigger.current : workspace.current?.querySelector<HTMLElement>('[role="tab"][aria-selected="true"]')))?.focus({ preventScroll: true });
  const { detail, detailOpener, mapDetail, listDetail, dismissEmbeddedDetail } = useMapDetailFocus({
    view, embedded, current, detailKey, details, focusRevision, cameraRequest, onCloseDetails, focusMapControl,
  });
  // 겹친 지점 팝업을 연 묶음 원. 닫기(×·Escape) 뒤 포커스를 그 자리로 돌려준다. 장소를 고르면 상세로 간다.
  const overlapOpener = useRef<HTMLElement | null>(null);
  const overlapFocusCleanup = useRef<(() => void) | null>(null);
  useEffect(() => () => overlapFocusCleanup.current?.(), []);
  const closeOverlap = () => {
    overlapFocusCleanup.current?.();
    const opener = overlapOpener.current;
    overlapOpener.current = null;
    setClusterPlaces([]);
    overlapFocusCleanup.current = restoreOverlapFocus(opener, mapContainer.current);
  };
  const selectPlace = (place: Place) => {
    overlapOpener.current = null;
    setClusterPlaces([]); setClusterCamera(undefined);
    // 같은 장소를 다시 골라도(손으로 지도를 옮긴 뒤) 다시 그 자리로 이동하도록 요청 번호를 올린다.
    setCameraRequest((value) => value + 1);
    setSelected(place); onSelectPlace?.(place);
    if (!embedded) requestAnimationFrame(() => {
      detail.current?.focus({ preventScroll: true });
    });
  };

  useEffect(() => {
    if (query === searchQuery) return;
    const debounce = setTimeout(() => { setSearchQuery(query); setSelected(null); }, 250);
    return () => clearTimeout(debounce);
  }, [query, searchQuery]);


  // 카메라 요청 정체: 장소 key(부모가 선택을 바꾼 경우)와 요청 번호(같은 묶음·장소를 다시 누른 경우).
  // 현재 zoom은 이동 목표 계산에만 쓰고 정체에는 넣지 않는다 — 넣으면 손으로 확대할 때마다 다시 끌려간다.
  const camera = useMemo<CameraTarget | undefined>(() => clusterCamera ? { ...clusterCamera, id: `cluster:${cameraRequest}` }
    : current && hasCoordinates(current) ? { center: [current.longitude, current.latitude], zoom: Math.max(zoom, 11), id: `${keyOf(current)}:${cameraRequest}:${focusRevision}` } : undefined,
  [current, clusterCamera, cameraRequest, focusRevision]); // eslint-disable-line react-hooks/exhaustive-deps
  const focusFilters = () => { if (queryInput.current?.getClientRects().length) queryInput.current.focus({ preventScroll: true }); else focusMapControl(); };
  const closeDetail = () => { setSelected(null); requestAnimationFrame(() => { if (canRestoreFocus(detailOpener.current)) detailOpener.current.focus({ preventScroll: true }); else focusFilters(); }); };
  return { workspace, embedded, detail, detailOpener, query, selectedSources, products, kinds, allowedKinds, filtersExpanded, setFiltersExpanded, filterTrigger, setKinds, setSelected, controlId, queryInput, setQuery, setSelectedSources, sources, setProducts, view, setView, mapViewport, items, serverClustered, serverTotal, serverClusters, visiblePoints, pending, mapContainer, setMapUnavailableMessage, basemap, moved, camera, setClusterPlaces, setClusterCamera, zoom, setCameraRequest, groupedPoints, cluster, overlapOpener, setClusterAnchor, clusterList, selectPlace, selectedPoint, clusterPlaces, clusterAnchor, closeOverlap, current, loaded, mapDetail, listDetail, dismissEmbeddedDetail, closeDetail, setReload, focusFilters, failed, mapUnavailableMessage, fuelDetailScopeExpanded, setFuelDetailScopeExpanded, regionMarkers, railOnly, partialListKinds, perKindLimit, searchQuery, refreshViewport, fuelFreshness };
}

function useMapDetailFocus({
  view, embedded, current, detailKey, details, focusRevision, cameraRequest, onCloseDetails, focusMapControl,
}: {
  view: "map" | "list"; embedded: boolean; current: Place | null; detailKey?: string;
  details?: ReactNode; focusRevision: number; cameraRequest: number;
  onCloseDetails?: () => void; focusMapControl: () => void;
}) {
  // 전환 중 이전 Panel이 잠시 남으므로 각 Panel의 ref를 분리한다. 이전 상세의
  // 언마운트가 새 활성 상세의 ref를 비워 주소 이동 뒤 초점이 body로 빠지지 않게 한다.
  const mapDetail = useRef<HTMLElement | null>(null);
  const listDetail = useRef<HTMLElement | null>(null);
  const detail = view === "map" ? mapDetail : listDetail;
  const detailOpener = useRef<HTMLElement | null>(null);
  const selectedKey = detailKey ?? (current ? keyOf(current) : "");
  const hasEmbeddedDetails = embedded && details !== undefined;
  useEffect(() => {
    if (!selectedKey || (embedded && !hasEmbeddedDetails)) return;
    const active = document.activeElement;
    if (active instanceof HTMLElement && active !== document.body && !detail.current?.contains(active)) detailOpener.current = active;
    const frame = requestAnimationFrame(() => detail.current?.focus({ preventScroll: true }));
    return () => cancelAnimationFrame(frame);
  }, [embedded, hasEmbeddedDetails, selectedKey, focusRevision, cameraRequest, view, detail]);
  const dismissEmbeddedDetail = () => {
    onCloseDetails?.();
    const opener = detailOpener.current;
    detailOpener.current = null;
    requestAnimationFrame(() => {
      if (canRestoreFocus(opener)) opener.focus({ preventScroll: true });
      else focusMapControl();
    });
  };

  return { detail, detailOpener, mapDetail, listDetail, dismissEmbeddedDetail };
}

function restoreOverlapFocus(opener: HTMLElement | null, root: HTMLElement | null) {
  const id = opener?.dataset.interactionId;
  if (!opener || !id || !root) return null;
  // 팝업을 지우기 전에 포커스를 묶음 원으로 옮긴다(포커스된 목록 버튼이 먼저 사라지면 body로 간다).
  // 장소 재조회는 목록을 비웠다 다시 채우므로 같은 좌표의 묶음 원 DOM이 곧 새로 만들어질 수 있다. 잠시 동안
  // 포커스가 body로 떨어지면 같은 묶음(data-interaction-id)을 다시 잡는다. 사용자가 다른 곳으로 옮겼으면 건드리지 않는다.
  const find = () => root.querySelector<HTMLElement>(`[data-interaction-id="${CSS.escape(id)}"]`);
  (opener.isConnected ? opener : find())?.focus();
  const observer = new MutationObserver(() => {
    if (document.activeElement && document.activeElement !== document.body) return;
    find()?.focus();
  });
  observer.observe(root, { childList: true, subtree: true });
  const timer = setTimeout(() => observer.disconnect(), 2000);
  return () => { observer.disconnect(); clearTimeout(timer); };
}

function useTransportMapViewport(
  initial: ReturnType<typeof initialMapCamera>, view: "map" | "list", isPublicFuel: boolean,
) {
  const [viewport, setViewport] = useState(initial.viewport);
  const [zoom, setZoom] = useState(initial.zoom);
  const [mapViewport, setMapViewport] = useState<MapViewportReadout | null>(null);
  const [visibleBounds, setVisibleBounds] = useState<ObservedFuelViewport>();
  const [mapSize, setMapSize] = useState({ width: 800, height: 540 });
  const mapContainer = useRef<HTMLDivElement | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!mapContainer.current) return;
    const observer = new ResizeObserver(([entry]) => setMapSize({ width: entry.contentRect.width, height: entry.contentRect.height }));
    observer.observe(mapContainer.current);
    return () => observer.disconnect();
  }, [view]);

  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  const moved = useCallback((map: MapLibreMap) => {
    const bounds = map.getBounds();
    const nextZoom = map.getZoom();
    const center = map.getCenter();
    setMapViewport({ longitude: center.lng, latitude: center.lat, zoom: nextZoom });
    const exact = { min_longitude: bounds.getWest(), min_latitude: bounds.getSouth(), max_longitude: bounds.getEast(), max_latitude: bounds.getNorth() };
    const next = quantizeViewport(exact, nextZoom);
    if (isPublicFuel) setVisibleBounds({ exact, query: next, zoom: nextZoom });
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      setZoom(nextZoom);
      setViewport((previous) => {
      // 패널 높이/스크롤 변화로 같은 bounds의 moveend가 와도 선택 목록을 지우거나
      // 같은 정밀도 셀 안에서 같은 DB 조회를 반복하지 않는다.
      return (Object.keys(next) as (keyof Viewport)[]).every((key) => next[key] === previous[key]) ? previous : next;
      });
    }, 250);
  }, [isPublicFuel]);

  return { viewport, zoom, mapViewport, visibleBounds, mapSize, mapContainer, moved };
}

function useTransportMapResults({
  embedded, kindsKey, perKindLimit, viewport, zoom, reload, sourcesKey, searchQuery, productsKey, filterQuery, view, mode, isPublicFuel, load,
}: {
  embedded: boolean; kindsKey: string; perKindLimit: number; viewport: Viewport; zoom: number; reload: number;
  sourcesKey: string; searchQuery: string; productsKey: string; filterQuery: string; view: "map" | "list";
  mode: "all" | "transport" | "fuel"; isPublicFuel: boolean; load: typeof transportGet;
}) {
  const [loaded, setLoaded] = useState<Record<string, PlaceResponse>>({});
  const [knownSources, setKnownSources] = useState<string[]>([]);
  const [serverClusters, setServerClusters] = useState<MapCluster[]>([]);
  const [serverClustered, setServerClustered] = useState(false);
  const [serverTotal, setServerTotal] = useState(0);
  const [loadedMapScope, setLoadedMapScope] = useState("");
  const [pending, setPending] = useState<string[]>([]);
  const [failed, setFailed] = useState<string[]>([]);
  const mapResponseCache = useRef(new Map<string, { expiresAt: number; payload: PlaceResponse }>());
  const lastReload = useRef(reload);
  const mapFilterSignature = useRef("");
  const knownSourcesReady = useRef(false);
  // 공개 유가: 가격 읽기 모델의 신선도(전역 값). 필터·유종을 바꿔 결과를 비워도(재조회 중) 마지막으로 받은 값을 유지해
  // 가격 아이콘이 빨강→회색→빨강으로 깜빡이지 않게 한다.
  const [fuelFreshness, setFuelFreshness] = useState<{ stale: boolean; lastRefreshedAt?: string | null }>();
  // 지역 카드와 그것을 받은 요청의 zoom(공개 유가가 카드 단위가 바뀌었는지 판단한다).
  const [fuelRegions, setFuelRegions] = useState<{ rows: FuelRegion[]; zoom?: number }>({ rows: [] });

  useEffect(() => {
    if (embedded) return;
    const controller = new AbortController();
    const selectedKinds = kindsKey ? kindsKey.split(",") : [];
    const filterSignature = `${kindsKey}|${sourcesKey}|${searchQuery}|${productsKey}|${filterQuery}|${view}`;
    if (lastReload.current !== reload) {
      mapResponseCache.current.clear();
      lastReload.current = reload;
    }
    // 필터가 바뀌면 이전 조건 결과를 비우지만, 이동 중에는 기존 viewport 결과를
    // 유지해 빈 화면 대신 현재 화면 안에 남아 있는 점을 계속 보여준다.
    if (mapFilterSignature.current !== filterSignature || view === "list") {
      setLoaded({}); setServerClusters([]); setServerClustered(false); setServerTotal(0);
      mapFilterSignature.current = filterSignature;
    }
    setPending(selectedKinds); setFailed([]);

    const applyPayload = (payload: PlaceResponse) => {
      setLoaded(partitionMapPayload(payload, selectedKinds, isPublicFuel));
      if (isPublicFuel) setLoadedMapScope(fuelMapScope(viewport, zoom, filterQuery ? `${productsKey}|${filterQuery}` : productsKey));
      setFuelRegions({ rows: payload.fuel_regions ?? [], zoom });
      if (isPublicFuel && typeof payload.fuel_prices_stale === "boolean") {
        setFuelFreshness({ stale: payload.fuel_prices_stale, lastRefreshedAt: payload.fuel_prices_last_refreshed_at });
      }
      setServerClusters(payload.clusters ?? []);
      setServerClustered(payload.clustered ?? false);
      setServerTotal(payload.total);
      knownSourcesReady.current = true;
      setKnownSources((value) => [...new Set([...value, ...(payload.available_sources ?? payload.items.map((item) => item.source))])]);
      setPending([]);
    };

    if (view === "map" && selectedKinds.length) {
      const search = mapPlaceSearch({
        kinds: selectedKinds, viewport, zoom, perKindLimit, mode, includeSources: !knownSourcesReady.current,
        sources: sourcesKey, query: searchQuery, products: productsKey, publicFuel: isPublicFuel, filterQuery,
      });
      const cacheKey = search.toString();
      const cached = mapResponseCache.current.get(cacheKey);
      if (cached && cached.expiresAt > Date.now()) {
        mapResponseCache.current.delete(cacheKey);
        mapResponseCache.current.set(cacheKey, cached);
        applyPayload(cached.payload);
        return () => controller.abort();
      }
      mapResponseCache.current.delete(cacheKey);
      // 일시적 혼잡(429·503·504, Retry-After 5초 이하)은 같은 조건으로 한 번 자동 재조회한다. 기다리는 동안 이전 결과는 그대로 둔다.
      loadWithTransientRetry<PlaceResponse>(load, `transport/features/places?${search}`, controller.signal).then((payload) => {
        if (controller.signal.aborted) return;
        mapResponseCache.current.set(cacheKey, { expiresAt: Date.now() + MAP_CLUSTER_CACHE_TTL_MS, payload });
        while (mapResponseCache.current.size > MAP_CLUSTER_CACHE_MAX) {
          const oldest = mapResponseCache.current.keys().next().value;
          if (oldest === undefined) break;
          mapResponseCache.current.delete(oldest);
        }
        applyPayload(payload);
      }).catch(() => {
        if (!controller.signal.aborted) { setFailed(selectedKinds); setPending([]); }
      });
      return () => controller.abort();
    }

    // 목록은 좌표 없는 항구·터미널도 찾아야 하므로 기존 종류별 reference 조회를 유지한다.
    selectedKinds.forEach((kind) => {
      // 좌표 없는 항구·터미널도 목록에서 코드/이름으로 찾되 지도에는 검증된 위치만 놓는다.
      const referenceList = view === "list" && REFERENCE_LIST_KINDS.has(kind);
      const search = new URLSearchParams({ kind, limit: String(referenceList && searchQuery.trim() ? 5000 : perKindLimit),
        ...(referenceList ? { include_unlocated: "true" } : viewport) });
      if (!knownSourcesReady.current) search.set("include_sources", "true");
      else search.set("include_sources", "false");
      if (sourcesKey) search.set("sources", sourcesKey);
      if (searchQuery.trim()) search.set("query", searchQuery.trim());
      if (productsKey && kind === "fuel_station") search.set("product_codes", productsKey);
      loadWithTransientRetry<PlaceResponse>(load, `transport/features/places?${search}`, controller.signal).then((payload) => {
        if (!controller.signal.aborted) {
          setLoaded((value) => ({ ...value, [kind]: payload }));
          setKnownSources((value) => [...new Set([...value, ...(payload.available_sources ?? payload.items.map((item) => item.source))])]);
        }
      }).catch(() => { if (!controller.signal.aborted) setFailed((value) => [...value, kind]); })
        .finally(() => { if (!controller.signal.aborted) setPending((value) => value.filter((entry) => entry !== kind)); });
    });
    return () => controller.abort();
  }, [embedded, kindsKey, perKindLimit, viewport, zoom, reload, sourcesKey, searchQuery, productsKey, filterQuery, view, mode, isPublicFuel, load]);

  return { loaded, knownSources, fuelRegions, fuelFreshness, serverClusters, serverClustered, serverTotal, loadedMapScope, pending, failed };
}

// 유가 지역 카드의 배치·넘침·접기 수명은 장소 조회와 겹친 장소 선택에서 분리한다.
function useFuelRegionCards({ fuelRegions, mapContainer, view, serverClustered, mapViewport, mapSize, hideOffscreen = false }: {
  fuelRegions: FuelRegion[]; mapContainer: RefObject<HTMLDivElement | null>; view: "map" | "list"; serverClustered: boolean;
  mapViewport: MapViewportReadout | null; mapSize: { width: number; height: number };
  /** 공개 유가: 원점(지역 좌표)이 지도 밖인 카드는 가장자리로 끌어오지 않고 접는다. 서버는 화면 안 지역만 내므로
   * 그런 카드는 이전 화면의 응답이다. */
  hideOffscreen?: boolean;
}) {
  const regionMarkers = useMemo(() => {
    const groups = new Map<string, FuelRegion[]>();
    for (const row of fuelRegions) groups.set(row.region_key, [...(groups.get(row.region_key) ?? []), row]);
    return [...groups.values()].map(rows => {
      const prices = new Map(rows.map(row => [row.product_code, row]));
      // 유종별 대표 좌표가 달라도 한 지역에는 카드 하나만 놓는다. 가격은 API 집계를 그대로 쓴다.
      const anchor = FUEL_PRODUCTS.map(code => prices.get(code)).find(Boolean) ?? rows[0];
      return { ...anchor, prices };
    });
  }, [fuelRegions]);

  useEffect(() => {
    const root = mapContainer.current;
    if (!root || view !== "map" || !serverClustered || !regionMarkers.length) return;
    let frame = 0;
    const position = () => {
      frame = 0;
      const bounds = root.getBoundingClientRect();
      if (!bounds.width || !bounds.height) return;
      const hosts = [...root.querySelectorAll<HTMLElement>(".fuel-region-marker")];
      const offscreen = hideOffscreen ? hosts.filter(host => {
        const anchor = host.getBoundingClientRect();
        return anchor.left < bounds.left || anchor.left > bounds.right || anchor.top < bounds.top || anchor.top > bounds.bottom;
      }) : [];
      const hidden = new Set(offscreen);
      // 원점이 지도 밖인 카드(이전 화면의 응답)는 접고 탭 순서·접근성 트리에서도 뺀다(inert). 초점을 받으면 지도 밖에 라벨이 그려진다.
      if (hideOffscreen) for (const host of hosts) {
        const away = hidden.has(host);
        host.inert = away;
        if (away) host.dataset.regionOffscreen = "true"; else delete host.dataset.regionOffscreen;
      }
      for (const host of offscreen) {
        host.style.setProperty("--region-offset-x", "0px");
        host.style.setProperty("--region-offset-y", "0px");
        host.dataset.regionOverflow = "true";
      }
      const cards = hosts.filter(host => !hidden.has(host)).flatMap(host => {
        const label = host.querySelector<HTMLElement>(".fuel-region-label");
        // Marker hosts can outlive their portal children; the child-list observer retries attachment.
        if (!label) return [];
        const anchor = host.getBoundingClientRect();
        return [{ host, left: anchor.left - bounds.left, top: anchor.top - bounds.top,
          width: label.offsetWidth, height: label.offsetHeight }];
      });
      if (cards.some(card => !card.width || !card.height)) return;
      const controls = root.closest(".fuel-map-stage")?.querySelectorAll<HTMLElement>(".fuel-viewport-summary, .maplibregl-ctrl-top-right, .maplibregl-ctrl-bottom-right") ?? [];
      const reserved = [...controls].map(control => {
        const rect = control.getBoundingClientRect();
        return { left: rect.left - bounds.left, top: rect.top - bounds.top, width: rect.width, height: rect.height };
      }).filter(rect => rect.width && rect.height);
      const offsets = layoutFuelRegionCards(cards, bounds.width, bounds.height, reserved);
      offsets.forEach((offset, index) => {
        const host = cards[index].host;
        host.style.setProperty("--region-offset-x", `${offset.x}px`);
        host.style.setProperty("--region-offset-y", `${offset.y}px`);
        // 공간이 모자란 카드는 화면에서 접어 원점만 남긴다. 마커 버튼은 그대로 탭 순서에 두고(접근 이름에
        // 전 유종 가격이 있다) 키보드 포커스를 받으면 카드를 다시 보인다(globals.css).
        host.dataset.regionOverflow = String(!offset.placed);
        const line = host.querySelector(".fuel-region-link line");
        line?.setAttribute("x2", String(offset.x)); line?.setAttribute("y2", String(offset.y));
      });
    };
    const schedule = () => { if (!frame) frame = requestAnimationFrame(position); };
    // Marker는 portal로 늦게 붙는다. style 변경은 관찰하지 않아 자체 위치 보정이 반복되지 않는다.
    const observer = new MutationObserver(schedule);
    observer.observe(root, { childList: true, subtree: true });
    const resize = new ResizeObserver(schedule);
    root.closest(".fuel-map-stage")?.querySelectorAll<HTMLElement>(".fuel-viewport-summary").forEach(control => resize.observe(control));
    schedule();
    return () => { observer.disconnect(); resize.disconnect(); cancelAnimationFrame(frame); };
  }, [view, serverClustered, regionMarkers, mapViewport, mapSize, mapContainer, hideOffscreen]);
  return regionMarkers;
}

function initialMapCamera(embedded: boolean): { camera?: MapCamera; viewport: Viewport; zoom: number } {
  if (embedded || typeof window === "undefined") return { viewport: DEFAULT_VIEWPORT, zoom: 7 };
  const search = new URLSearchParams(window.location.search);
  const longitude = Number(search.get("longitude")), latitude = Number(search.get("latitude"));
  if (!search.has("longitude") || !search.has("latitude") || !Number.isFinite(longitude) || !Number.isFinite(latitude)
    || longitude < 124 || longitude > 132 || latitude < 32 || latitude > 39.5) return { viewport: DEFAULT_VIEWPORT, zoom: 7 };
  return { camera: { center: [longitude, latitude], zoom: 15 }, zoom: 15,
    viewport: { min_longitude: String(longitude - .015), max_longitude: String(longitude + .015), min_latitude: String(latitude - .015), max_latitude: String(latitude + .015) } };
}

function MapInspector({ panelView, embedded, details, mapDetail, listDetail, detailTitle, current, dismissEmbeddedDetail, closeDetail, loaded, setView, setCameraRequest, setSelected, setReload, focusFilters, load, publicFuel }: { publicFuel?: { onRefresh?: () => void; refreshing: boolean; products?: string[]; filterQuery?: string }; load: typeof transportGet; panelView: "map" | "list"; details?: ReactNode; detailTitle?: ReactNode } & Pick<ReturnType<typeof useTransportMap>, "embedded" | "mapDetail" | "listDetail" | "current" | "dismissEmbeddedDetail" | "closeDetail" | "loaded" | "setView" | "setCameraRequest" | "setSelected" | "setReload" | "focusFilters">) {
  if (embedded) return details ? <MapDetailOverlay ref={panelView === "map" ? mapDetail : listDetail} className="transport-map-detail" aria-label="선택 장소 상세" header={<h2>{detailTitle ?? current?.name ?? "선택 장소 상세"}</h2>} collapsible onDismiss={dismissEmbeddedDetail}>
    {details}
  </MapDetailOverlay> : null;
  if (!current) return null;
  return <MapDetailOverlay className={cn("transport-map-detail weather-inspector", current.kind === "fuel_station" && "fuel-inspector")} ref={panelView === "map" ? mapDetail : listDetail} aria-label="선택 장소 상세" header={<MapInspectorHeading current={current} />} collapsible={current.kind !== "fuel_station"} onDismiss={closeDetail}>
    {!publicFuel && current.kind === "fuel_station" && loaded.fuel_station?.fuel_prices_stale ? <div className="inspector-section fuel-price-status"><FuelPriceStatus stale lastRefreshedAt={loaded.fuel_station.fuel_prices_last_refreshed_at} /></div> : null}
    <PlaceInspector key={keyOf(current)} load={load} place={current} showHeader={false} publicFuel={publicFuel} onShowMap={() => { setView("map"); setCameraRequest((value) => value + 1); }} onClose={closeDetail} onSaved={(updated) => { setSelected(updated); setReload((value) => value + 1); }} onReload={() => { setSelected(null); setReload((value) => value + 1); focusFilters(); }} />
  </MapDetailOverlay>;
}


function MapSearchFilters({ filterSummary, query, selectedSources, products, kinds, allowedKinds, filtersExpanded, setFiltersExpanded, filterTrigger, toolbar, mode, setKinds, setSelected, controlId, queryInput, setQuery, setSelectedSources, sources, setProducts }: Pick<ReturnType<typeof useTransportMap>, "query" | "selectedSources" | "products" | "kinds" | "allowedKinds" | "filtersExpanded" | "setFiltersExpanded" | "filterTrigger" | "setKinds" | "setSelected" | "controlId" | "queryInput" | "setQuery" | "setSelectedSources" | "sources" | "setProducts"> & Pick<NonNullable<Parameters<typeof TransportMap>[0]>, "filterSummary" | "toolbar" | "mode">) {
  return (<MapFilterPanel label={filterSummary ?? ([query, selectedSources.length ? `${selectedSources.length}개 출처` : "", products.map(fuelProductLabel).join("·"), kinds.length !== allowedKinds.length ? `${kinds.length}종류` : ""].filter(Boolean).join(" · ") || "지도 필터")} expanded={filtersExpanded} onExpandedChange={setFiltersExpanded} triggerRef={filterTrigger}>
    {toolbar ?? <MapFilterBar>
      {mode !== "fuel" ? <MapKindFilter ariaLabel={mode === "transport" ? "교통 종류" : "장소 종류"} options={allowedKinds.map((kind) => ({ value: kind, label: placeKindLabel(kind), icon: <PlaceIcon kind={kind} /> }))} value={kinds} onToggle={(value) => { const kind = value as PlaceKind; setKinds((previous) => previous.includes(kind) ? previous.filter((entry) => entry !== kind) : [...previous, kind]); setSelected(null); }} /> : null}
      <MapFilterField htmlFor={`${controlId}-query`} label="장소 검색"><Input ref={queryInput} id={`${controlId}-query`} type="search" value={query} onChange={(event) => { setQuery(event.target.value); setSelected(null); }} placeholder="이름·주소·브랜드·노선" /></MapFilterField>
      <MapFilterField htmlFor={`${controlId}-source`} label="데이터 출처"><FilterCombobox compact id={`${controlId}-source`} value={selectedSources} onChange={(values) => { setSelectedSources(values); setSelected(null); }} placeholder="모든 출처" options={sources.map((value) => ({ value, label: collectionSourceLabel(value) }))} /></MapFilterField>
      {kinds.includes("fuel_station") ? <MapFilterField htmlFor={`${controlId}-product`} label="표시 유종"><FilterCombobox compact id={`${controlId}-product`} value={products} onChange={(values) => { setProducts(values); setSelected(null); }} placeholder="전체 유종" options={FUEL_PRODUCTS.map((value) => ({ value, label: fuelProductLabel(value) }))} /></MapFilterField> : null}
    </MapFilterBar>}
    </MapFilterPanel>);
}


function TransportMapCanvas({ mapContainer, mapViewport, setMapUnavailableMessage, basemap, moved, camera, layers, serverClustered, serverClusters, setClusterPlaces, setClusterCamera, zoom, setCameraRequest, groupedPoints, cluster, products, overlapOpener, setClusterAnchor, clusterList, selectPlace, selectedPoint, clusterPlaces, clusterAnchor, closeOverlap, regionMarkers, railOnly, fuelOnly, publicFuel }: { fuelOnly: boolean; publicFuel: boolean } & Pick<ReturnType<typeof useTransportMap>, "mapContainer" | "mapViewport" | "setMapUnavailableMessage" | "basemap" | "moved" | "camera" | "serverClustered" | "serverClusters" | "setClusterPlaces" | "setClusterCamera" | "zoom" | "setCameraRequest" | "groupedPoints" | "cluster" | "products" | "overlapOpener" | "setClusterAnchor" | "clusterList" | "selectPlace" | "selectedPoint" | "clusterPlaces" | "clusterAnchor" | "closeOverlap" | "regionMarkers" | "railOnly"> & Pick<NonNullable<Parameters<typeof TransportMap>[0]>, "layers">) {
  const regionProducts = publicFuel && products.length ? products : FUEL_PRODUCTS;
  const showProductName = !publicFuel || products.length !== 1;
  return (<div className="map-primary" ref={mapContainer}><MountCamera camera={mapViewport ? { center: [mapViewport.longitude, mapViewport.latitude], zoom: mapViewport.zoom } : DEFAULT_CAMERA}>{(initialCamera) => <VWorldMapView apiKey={VWORLD_KEY} center={initialCamera.center} zoom={initialCamera.zoom} minZoom={5}

        className="transport-map-canvas" layerType="Base" navigation={false} geolocate={false} scale
        loadingSkeleton={<p className="transport-map-loading" role="status">지도를 준비하는 중입니다…</p>} fallback={(info) => <MapUnavailable info={info} onMessage={setMapUnavailableMessage} />}
        unsupportedTileFallback={{ imageUrl: MAP_FALLBACK_IMAGE }} transformRequest={basemap.transformRequest}
        onError={basemap.onError} onIdle={basemap.onIdle} onLoad={moved} onMoveEnd={(event) => moved(event.target)}>
        <ZoomButtons />
        <CameraRequest target={camera} />
        {layers}
        {serverClustered && regionMarkers.map(r => <MapMarkerButton key={r.region_key} lngLat={[r.longitude, r.latitude]} passThrough
          ariaLabel={`${r.label}, ${regionProducts.map(code => { const price = r.prices.get(code); return `${fuelProductLabel(code)} ${price ? `${Math.round(price.average_price)}원/L, ${price.station_count}곳` : "미제공"}`; }).join(", ")}`}
          interactionId={`region:${r.region_key}`} className="fuel-region-marker" onClick={() => { setClusterCamera({center:[r.longitude,r.latitude],zoom:Math.floor(zoom)<8?8:fuelOnly?10:12});setCameraRequest(v=>v+1); }}>
          <svg className="fuel-region-link" aria-hidden="true" width="1" height="1"><line x1="0" y1="0" x2="0" y2="0" /></svg>
          <span className="fuel-region-origin" aria-hidden="true" />
          <FuelRegionLabel label={r.label} prices={r.prices} products={regionProducts} showProductName={showProductName} />
        </MapMarkerButton>)}
        {serverClustered ? serverClusters.map(item => <MapMarkerButton key={`server-cluster:${item.longitude}:${item.latitude}`} lngLat={[item.longitude, item.latitude]} ariaLabel={`${item.count}개 장소 요약 묶음 확대`} interactionId={`server-cluster:${item.longitude.toFixed(6)},${item.latitude.toFixed(6)}`} className="map-cluster" zIndex={3} isCluster onClick={() => {

          setClusterPlaces([]); setClusterCamera({ center: [item.longitude, item.latitude], zoom: Math.min(19, Math.max(fuelOnly ? 10 : 12, Math.ceil(zoom) + 2)) });
          setCameraRequest((value) => value + 1);
        }}><ClusterBubble count={item.count} label={CLUSTER_NUMBER_FORMATTER.format(item.count)} /></MapMarkerButton>) : <ClusterLayer points={groupedPoints} radius={railOnly ? 24 : cluster ? (products.length === 1 ? 80 : 110) : fuelOnly ? 0 : 60} maxZoom={railOnly ? 10 : 19}
          renderCluster={(group, count, index) => {
            const coordinates = group.geometry.coordinates;
            const id = group.properties.cluster_id;
            // 묶음 원은 낱개 마커 위(z 3), 선택 마커 아래다. interaction id는 zoom이 든 cluster_id 대신 위치로 잡아
            // 재조회로 묶음 원이 다시 만들어져도 같은 data-interaction-id로 포커스를 찾는다.
            return <MapMarkerButton lngLat={coordinates} ariaLabel={`${count}개 위치 묶음 펼치기`} className="map-cluster" zIndex={3} isCluster
              interactionId={`cluster:${coordinates[0].toFixed(6)},${coordinates[1].toFixed(6)}`} onClick={(element) => {
                if (id === undefined) return;
                const expansion = index.getClusterExpansionZoom(id);
                if (expansion > 19 || zoom >= 19) {
                  // Map과 같이 확대해도 풀리지 않는 묶음은 겹친 지점 팝업으로 고르게 한다.
                  overlapOpener.current = element;
                  setClusterAnchor(coordinates);
                  setClusterPlaces(index.getLeaves(id, count).map((leaf) => (leaf.properties as unknown as MapPoint).place));
                  requestAnimationFrame(() => clusterList.current?.querySelector("button")?.focus());
                } else {
                  setClusterPlaces([]); setClusterCamera({ center: coordinates, zoom: Math.min(19, expansion) });
                  setCameraRequest((value) => value + 1);
                }
              }}><ClusterBubble count={count} label={String(group.properties.point_count_abbreviated ?? count)} /></MapMarkerButton>;
          }}
          renderMarker={(point: ClusterPoint) => <MapMarker point={point as unknown as MapPoint} products={products} showProductName={showProductName} onSelect={selectPlace} selected={false} />} />}
        {selectedPoint ? <MapMarker point={selectedPoint} products={products} showProductName={showProductName} onSelect={selectPlace} selected /> : null}
        {clusterPlaces.length ? <OverlapPopup lngLat={clusterAnchor} onClose={closeOverlap}>
          <OverlapList places={clusterPlaces} onSelect={selectPlace} listRef={clusterList} />
        </OverlapPopup> : null}
      </VWorldMapView>}</MountCamera>
      </div>);
}


function MapPlaceRows({ status, listContent, listPlaces, items, current, selectPlace }: { status: import("react").ReactNode } & Pick<ReturnType<typeof useTransportMap>, "items" | "current" | "selectPlace"> & Pick<NonNullable<Parameters<typeof TransportMap>[0]>, "listContent" | "listPlaces">) {
  return (<div className="map-place-list"><div className="map-feedback">{status}</div>{listContent}{listPlaces ? items.map((place) => <button type="button" className="place-row" key={keyOf(place)} aria-pressed={current ? keyOf(current) === keyOf(place) : false} onClick={() => selectPlace(place)}><PlaceIcon kind={place.kind} brandCode={place.brand_code} brandName={place.brand_name} /><span><strong>{place.name}</strong><small>{place.line_names.join(" · ") || place.brand_name || place.subtitle || placeKindLabel(place.kind)}</small>{(place.kind === "ferry_port" || place.kind === "bus_terminal") && place.provider_id ? <small>{place.kind === "ferry_port" ? "항구" : "터미널"} 코드 {place.provider_id}</small> : null}{!hasCoordinates(place) ? <small>좌표 미등록</small> : null}</span></button>) : null}</div>);
}


function FuelMapGuidance({ kinds, loaded }: Pick<ReturnType<typeof useTransportMap>, "kinds" | "loaded">) {
  return (<div className="map-feedback map-guidance text-xs text-text-secondary" role="status">

      {kinds.includes("fuel_station") && loaded.fuel_station?.fuel_prices_stale ? <p className="error text-destructive">유가 갱신 지연 · 유종·가격은 {dateTime(loaded.fuel_station.fuel_prices_last_refreshed_at)} 기준이며 판매 여부도 다를 수 있습니다.</p> : null}
      {kinds.includes("fuel_station") && loaded.fuel_station?.fuel_prices_last_refreshed_at && !loaded.fuel_station.fuel_prices_stale ? <p>유가 {dateTime(loaded.fuel_station.fuel_prices_last_refreshed_at)} 갱신</p> : null}
    </div>);
}


function MapResultTabs({ mapViewport, view, listCount, listPlaces, items, listFeatureCount = 0, mapFeatureCount = 0, serverClustered, serverTotal, visiblePoints, pending, partialListKinds, perKindLimit, searchQuery }: Pick<ReturnType<typeof useTransportMap>, "mapViewport" | "view" | "items" | "serverClustered" | "serverTotal" | "visiblePoints" | "pending" | "partialListKinds" | "perKindLimit" | "searchQuery"> & Pick<NonNullable<Parameters<typeof TransportMap>[0]>, "listCount" | "listPlaces" | "listFeatureCount" | "mapFeatureCount">) {
  const count = view === "list" ? listCount ?? ((listPlaces ? items.length : 0) + listFeatureCount) : mapFeatureCount + (serverClustered ? serverTotal : visiblePoints.length);
  const partialCount = listCount ?? ((listPlaces ? items.length : 0) + listFeatureCount);
  const partial = partialListKinds.map(kind => {
    const searchable = kind === "ferry_port" || kind === "bus_terminal" || kind === "public_parking_lot";
    return placeKindLabel(kind) + " 최대 " + (searchable && searchQuery.trim() ? 5000 : perKindLimit).toLocaleString("ko-KR") + "건";
  }).join(" · ");
  return <MapViewTabs ariaLabel="장소 보기" viewport={mapViewport} count={count} status={pending.length ? <span className="kt-map-count">조회 중…</span> : partialListKinds.length ? <span className="inline-flex items-center gap-1"><span className="kt-map-count">{partialCount.toLocaleString("ko-KR")}건 표시</span><InfoButton label="목록 일부 표시">일부 결과만 조회했습니다. {partial}. 검색 조건을 좁혀 주세요.</InfoButton></span> : undefined} />;
}


function MapInspectorHeading({ current }: { current: NonNullable<ReturnType<typeof useTransportMap>["current"]> }) {
  // 로고 이미지가 있으면 브랜드는 로고가 보여 준다(접근 이름은 로고 alt). 로고가 없는 상표(자가상표·미등록)만 글자로 남긴다.
  const brand = current.kind === "fuel_station" ? fuelBrand(current.brand_code, current.brand_name) : null;
  return current.kind === "fuel_station" ? <div className="fuel-detail-heading"><PlaceIcon kind={current.kind} brandCode={current.brand_code} brandName={current.brand_name} /><h2>{current.name}</h2>{brand && !brand.image && current.brand_name ? <small>{current.brand_name}</small> : null}</div> : <div><span className="place-title"><PlaceIcon kind={current.kind} brandCode={current.brand_code} brandName={current.brand_name} />{current.brand_name ?? placeKindLabel(current.kind)}</span><h2>{current.name}</h2></div>;
}


function MapQueryStatus({ feedback, failed, setReload, basemap, view, mapUnavailableMessage }: Pick<ReturnType<typeof useTransportMap>, "failed" | "setReload" | "basemap" | "view" | "mapUnavailableMessage"> & Pick<NonNullable<Parameters<typeof TransportMap>[0]>, "feedback">) {
  return (<>
    {feedback}
    {failed.length ? <p className="error" role="alert">{failed.map(placeKindLabel).join("·")} 조회 실패 <Button variant="outline" type="button" onClick={() => setReload((value) => value + 1)}>다시 조회</Button></p> : null}
    {basemap.basemapFailed && view === "map" ? <p className="error" role="alert">지도 타일 오류 · 목록 보기</p> : null}
    {mapUnavailableMessage && view === "map" ? <p className="error" role="alert">{mapUnavailableMessage}</p> : null}
  </>);
}
