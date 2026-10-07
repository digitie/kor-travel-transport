"use client";

// 교통 지도의 MapLibre 셸. kor-travel-map admin의 `components/vworld-map-view.tsx`
// (commit 399d6b6a844d0d806dc067ab29aaf8442840f789)와 같은 방식으로 지도를 만든다:
// - 배경지도: `lib/vworld-style.ts`(Map 사본)의 VWorld WMTS raster style. 키가 없으면 배경색만 그린다.
// - 컨트롤: 확대/축소(나침반 없음) 오른쪽 위, 축척 오른쪽 아래(150px·미터), 접힌 출처 표기.
// - 마커: DOM 마커. 배지 모양은 Map `@kor-travel-map/map-marker-react`의 `createMarkerElement`(vendored)다.
// - 묶음: Map `createClusterElement`와 같은 brand 색 원 + 개수.
// - 겹친 지점: Map과 같은 MapLibre Popup.
// Map과 다른 점: 묶음 계산은 GeoJSON source(cluster:true) 대신 main thread의 supercluster로 한다.
// MapLibre worker를 쓰지 않아 Turbopack worker 배포 함정(Map `setWorkerUrl` 주석)을 피하고,
// 확대 한계에서 묶음의 장소 목록을 바로 얻는다.

import "maplibre-gl/dist/maplibre-gl.css";
import * as maplibregl from "maplibre-gl";
import type { Map as MapLibreMap, Marker as MapLibreMarker, Popup as MapLibrePopup } from "maplibre-gl";
import Supercluster from "supercluster";
import {
  createContext, Fragment, use, useEffect, useLayoutEffect, useMemo, useRef, useState,
  type CSSProperties, type KeyboardEvent, type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { createMarkerElement } from "@/lib/vendor/map-marker-react";
import { abbreviateClusterCount, clusterBubbleSize } from "@/lib/place-marker-style";
import { buildVWorldStyle, getVWorldMaxZoom, redactVWorldUrl, type VWorldLayerType } from "@/lib/vworld-style";

const VWorldMapContext = createContext<MapLibreMap | null>(null);

/** 지도 인스턴스. 지도가 준비되기 전에는 null이다. */
export function useVWorldMap(): MapLibreMap | null {
  return use(VWorldMapContext);
}

/**
 * 카메라 이동 요청. `id`가 요청의 정체다 — 같은 위치·확대라도 id가 바뀌면 다시 이동한다(손으로 옮긴 뒤
 * 같은 묶음·장소를 다시 누른 경우). 같은 id의 재렌더는 사용자가 옮긴 화면을 되돌리지 않는다.
 */
export type CameraTarget = { center: [number, number]; zoom: number; id: string | number };

/** 로그에 남기기 전에 메시지·URL 안의 VWorld 키를 가린다. */
function redactVWorldText(value: string | undefined): string | undefined {
  return value?.replace(/(\/req\/wmts\/1\.0\.0\/)([^/?#\s]+)(\/)/g, "$1***$3");
}

/** Map `SELECTED_OUTLINE` — 선택 강조는 불투명 focus 토큰 outline이다. */
const SELECTED_OUTLINE = "3px solid var(--focus)";

function isVWorldTileFailure(event: maplibregl.ErrorEvent): boolean {
  const sourceId = (event as { sourceId?: unknown }).sourceId;
  if (typeof sourceId === "string" && sourceId.startsWith("vworld-")) return true;
  const url = (event.error as { url?: unknown } | undefined)?.url;
  return typeof url === "string" && url.includes("api.vworld.kr");
}

type VWorldMapViewProps = {
  apiKey: string | undefined;
  center: [number, number];
  zoom: number;
  layerType?: VWorldLayerType;
  minZoom?: number;
  maxZoom?: number;
  /** mount 시점에만 읽는다(Map과 같다). */
  navigation?: boolean;
  /** mount 시점에만 읽는다(Map과 같다). */
  scale?: boolean;
  /** 값이 바뀔 때마다 그 위치로 부드럽게 이동한다. */
  cameraTarget?: CameraTarget;
  className?: string;
  loading?: ReactNode;
  /** 지도를 만들지 못했을 때(WebGL 미지원 등) 지도 자리에 보인다. */
  fallback?: ReactNode;
  children?: ReactNode;
  onLoad?: (map: MapLibreMap) => void;
  onMoveEnd?: (map: MapLibreMap) => void;
  /** VWorld 타일을 받지 못했을 때. 키는 넘기지 않는다. */
  onTileError?: () => void;
};

export function VWorldMapView({
  apiKey, center, zoom, layerType = "Base", minZoom = 6, maxZoom = 22, navigation = false, scale = false,
  cameraTarget, className, loading, fallback, children, onLoad, onMoveEnd, onTileError,
}: VWorldMapViewProps) {
  const [initFailed, setInitFailed] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const initialRef = useRef({ apiKey, center: cameraTarget?.center ?? center, zoom: cameraTarget?.zoom ?? zoom, layerType, minZoom, maxZoom, navigation, scale });
  const appliedStyleRef = useRef({ apiKey, layerType });
  const appliedCameraRef = useRef<CameraTarget | undefined>(cameraTarget);
  const onLoadRef = useRef(onLoad);
  const onMoveEndRef = useRef(onMoveEnd);
  const onTileErrorRef = useRef(onTileError);
  const [map, setMap] = useState<MapLibreMap | null>(null);
  const [loaded, setLoaded] = useState(false);

  useLayoutEffect(() => {
    onLoadRef.current = onLoad;
    onMoveEndRef.current = onMoveEnd;
    onTileErrorRef.current = onTileError;
  });

  useEffect(() => {
    if (containerRef.current === null) return;
    const initial = initialRef.current;
    let nextMap: MapLibreMap;
    try {
      nextMap = new maplibregl.Map({
        container: containerRef.current,
        style: buildVWorldStyle(initial.apiKey, initial.layerType),
        center: initial.center,
        zoom: initial.zoom,
        minZoom: initial.minZoom,
        maxZoom: Math.min(initial.maxZoom, getVWorldMaxZoom(initial.layerType)),
        attributionControl: { compact: true },
      });
    } catch (error) {
      // WebGL이 없거나 막힌 브라우저에서 생성자가 던진다. 페이지 전체를 깨지 않고 대체 안내로 바꿔
      // 필터·목록·상세는 계속 쓰게 한다.
      console.warn("[VWorldMapView] 지도를 초기화하지 못했습니다", redactVWorldText(error instanceof Error ? error.message : String(error)));
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setInitFailed(true);
      return;
    }
    setMap(nextMap);
    // e2e 훅(Map과 같다): 컨테이너 DOM에 지도 인스턴스를 매달아 Playwright가 카메라·bounds를 단언할 수 있게 한다.
    const containerNode = containerRef.current as HTMLDivElement & { _maplibreMap?: MapLibreMap };
    containerNode._maplibreMap = nextMap;

    let didNotifyLoad = false;
    const notifyLoad = () => {
      if (didNotifyLoad) return;
      didNotifyLoad = true;
      setLoaded(true);
      onLoadRef.current?.(nextMap);
    };
    const handleMoveEnd = () => onMoveEndRef.current?.(nextMap);
    const handleError = (event: maplibregl.ErrorEvent) => {
      if (isVWorldTileFailure(event)) {
        onTileErrorRef.current?.();
        return;
      }
      const error = event.error as { message?: string; url?: string } | undefined;
      console.warn("[VWorldMapView]", redactVWorldText(error?.message) ?? "unknown map error", redactVWorldUrl(error?.url) ?? "");
    };
    nextMap.on("load", notifyLoad);
    nextMap.on("idle", notifyLoad);
    nextMap.on("moveend", handleMoveEnd);
    nextMap.on("error", handleError);
    const loadFrame = requestAnimationFrame(notifyLoad);

    let resizeFrame = 0;
    const resizeObserver = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(() => {
      if (resizeFrame !== 0) return;
      resizeFrame = requestAnimationFrame(() => { resizeFrame = 0; nextMap.resize(); });
    });
    resizeObserver?.observe(containerRef.current);

    if (initial.navigation) nextMap.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    if (initial.scale) nextMap.addControl(new maplibregl.ScaleControl({ maxWidth: 150, unit: "metric" }), "bottom-right");

    return () => {
      cancelAnimationFrame(loadFrame);
      if (resizeFrame !== 0) cancelAnimationFrame(resizeFrame);
      resizeObserver?.disconnect();
      nextMap.off("load", notifyLoad);
      nextMap.off("idle", notifyLoad);
      nextMap.off("moveend", handleMoveEnd);
      nextMap.off("error", handleError);
      delete containerNode._maplibreMap;
      nextMap.remove();
      setLoaded(false);
      setMap(null);
    };
    // 지도 인스턴스는 mount 1회만 만든다. 카메라는 사용자 조작과 cameraTarget으로만 움직인다.
  }, []);

  useEffect(() => {
    if (map === null) return;
    if (appliedStyleRef.current.apiKey === apiKey && appliedStyleRef.current.layerType === layerType) return;
    map.setStyle(buildVWorldStyle(apiKey, layerType));
    appliedStyleRef.current = { apiKey, layerType };
  }, [map, apiKey, layerType]);

  const targetLng = cameraTarget?.center[0];
  const targetLat = cameraTarget?.center[1];
  const targetZoom = cameraTarget?.zoom;
  const targetId = cameraTarget?.id;
  useEffect(() => {
    if (map === null || targetLng === undefined || targetLat === undefined || targetZoom === undefined || targetId === undefined) return;
    // 요청 정체(id)로만 비교한다. mount 때의 요청은 초기 카메라로 이미 반영됐다.
    if (appliedCameraRef.current?.id === targetId) return;
    appliedCameraRef.current = { center: [targetLng, targetLat], zoom: targetZoom, id: targetId };
    map.easeTo({ center: [targetLng, targetLat], zoom: Math.min(targetZoom, map.getMaxZoom()) });
  }, [map, targetLng, targetLat, targetZoom, targetId]);

  if (initFailed) return <>{fallback ?? null}</>;
  return <VWorldMapContext value={map}>
    <div ref={containerRef} className={className} data-testid="vworld-map-container" />
    {loaded ? children : loading ?? null}
  </VWorldMapContext>;
}

type DomMarkerProps = {
  lngLat: [number, number];
  ariaLabel?: string;
  title?: string;
  interactionId?: string;
  className?: string;
  zIndex?: number;
  /** 위에 그리되 마우스·터치는 아래 마커로 통과시킨다(키보드로는 그대로 고른다). */
  passThrough?: boolean;
  /** 선택 상태를 `aria-pressed`로 알린다. 생략하면 토글 버튼이 아니다(묶음). */
  pressed?: boolean;
  /** 누른 마커 요소를 넘긴다(팝업을 닫을 때 그 자리로 포커스를 돌려주는 데 쓴다). */
  onClick?: (element: HTMLElement) => void;
  children: ReactNode;
};

/**
 * React children을 MapLibre DOM 마커로 띄운다. 클릭할 수 있으면 키보드(Enter·Space)로도 연다.
 * 마커 DOM은 지도가 바뀔 때만 다시 만들고 위치는 setLngLat로만 옮긴다(Map `VWorldMarker`와 같다).
 */
export function DomMarker({ lngLat, ariaLabel, title, interactionId, className, zIndex, passThrough = false, pressed, onClick, children }: DomMarkerProps) {
  const map = useVWorldMap();
  const [element] = useState(() => (typeof document === "undefined" ? null : document.createElement("div")));
  const markerRef = useRef<MapLibreMarker | null>(null);
  const [lng, lat] = lngLat;
  const positionRef = useRef<[number, number]>([lng, lat]);
  useLayoutEffect(() => { positionRef.current = [lng, lat]; });

  useEffect(() => {
    if (map === null || element === null) return;
    const marker = new maplibregl.Marker({ element }).setLngLat(positionRef.current).addTo(map);
    markerRef.current = marker;
    return () => { marker.remove(); markerRef.current = null; };
  }, [map, element]);

  useEffect(() => { markerRef.current?.setLngLat([lng, lat]); }, [lng, lat]);
  useEffect(() => {
    // 선택한 마커가 묶음·이웃 마커 위에 오게 한다. MapLibre가 감싸는 바깥 요소에 걸어야 효과가 있다.
    const host = markerRef.current?.getElement();
    if (!host) return;
    host.style.zIndex = zIndex === undefined ? "" : String(zIndex);
    host.style.pointerEvents = passThrough ? "none" : "";
  }, [map, zIndex, passThrough]);

  if (element === null) return null;
  const interactive = onClick !== undefined;
  const handleKeyDown = (event: KeyboardEvent<HTMLSpanElement>) => {
    if (!interactive || (event.key !== "Enter" && event.key !== " ")) return;
    event.preventDefault();
    onClick(event.currentTarget);
  };
  return createPortal(<span
    className={className}
    title={title}
    data-interaction-id={interactionId}
    role={interactive ? "button" : undefined}
    tabIndex={interactive ? 0 : undefined}
    aria-label={ariaLabel}
    aria-pressed={interactive ? pressed : undefined}
    onClick={interactive ? (event) => { event.preventDefault(); onClick(event.currentTarget); } : undefined}
    onKeyDown={interactive ? handleKeyDown : undefined}
  >{children}</span>, element);
}

/** Map 공용 마커 배지(24px 원 + maki 글리프). `createMarkerElement`가 만든 요소를 그대로 붙인다. */
export function MarkerBadge({ markerIcon, markerColor, selected = false }: { markerIcon: string; markerColor: string | null; selected?: boolean }) {
  const hostRef = useRef<HTMLSpanElement | null>(null);
  useLayoutEffect(() => {
    const host = hostRef.current;
    if (host === null) return;
    const element = createMarkerElement({ markerIcon, markerColor, size: 24 });
    // 접근 이름은 바깥 버튼이 갖는다. 배지는 장식이다.
    element.removeAttribute("role");
    element.setAttribute("aria-hidden", "true");
    element.dataset.markerIcon = markerIcon;
    if (selected) { element.style.outline = SELECTED_OUTLINE; element.style.outlineOffset = "2px"; }
    host.replaceChildren(element);
    return () => element.remove();
  }, [markerIcon, markerColor, selected]);
  return <span ref={hostRef} className="map-marker-badge" />;
}

/** Map `createClusterElement`와 같은 묶음 원(brand 배경·card 테두리·elevated 그림자). */
export function ClusterBubble({ count, label }: { count: number; label?: string }) {
  const size = clusterBubbleSize(count);
  const style: CSSProperties = { width: size, height: size, fontSize: count < 1000 ? 12 : 11 };
  return <span className="map-cluster-bubble" style={style} aria-hidden="true">{label ?? abbreviateClusterCount(count)}</span>;
}

type MapPopupProps = { lngLat: [number, number]; maxWidth?: string; onClose?: () => void; children: ReactNode };

/** React children을 MapLibre Popup으로 띄운다. Map 겹친 지점 팝업과 같은 옵션(닫기 버튼, 지도 클릭으로 닫지 않음)이다. */
export function MapPopup({ lngLat, maxWidth = "260px", onClose, children }: MapPopupProps) {
  const map = useVWorldMap();
  const [container] = useState(() => (typeof document === "undefined" ? null : document.createElement("div")));
  const popupRef = useRef<MapLibrePopup | null>(null);
  const onCloseRef = useRef(onClose);
  const [lng, lat] = lngLat;
  const positionRef = useRef<[number, number]>([lng, lat]);
  useLayoutEffect(() => { onCloseRef.current = onClose; positionRef.current = [lng, lat]; });

  useEffect(() => {
    if (map === null || container === null) return;
    const popup = new maplibregl.Popup({ closeButton: true, closeOnClick: false, maxWidth, focusAfterOpen: false, className: "map-overlap-popup" })
      .setLngLat(positionRef.current)
      .setDOMContent(container)
      .addTo(map);
    const handleClose = () => onCloseRef.current?.();
    // Escape는 팝업 안 어디에 포커스가 있든(목록 버튼·닫기 버튼) 팝업을 닫는다.
    const popupElement = popup.getElement();
    const handleKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      onCloseRef.current?.();
    };
    popupElement.addEventListener("keydown", handleKeyDown);
    popup.on("close", handleClose);
    popupRef.current = popup;
    return () => { popupElement.removeEventListener("keydown", handleKeyDown); popup.off("close", handleClose); popup.remove(); popupRef.current = null; };
  }, [map, container, maxWidth]);

  useEffect(() => { popupRef.current?.setLngLat([lng, lat]); }, [lng, lat]);

  return container === null ? null : createPortal(children, container);
}

export type ClusterPoint = { id: string; lngLat: [number, number] };
export type ClusterFeature<P extends ClusterPoint> = Supercluster.PointFeature<P> | Supercluster.ClusterFeature<Supercluster.AnyProps>;
type Viewport = { bbox: [number, number, number, number]; zoom: number };

function viewportOf(map: MapLibreMap): Viewport {
  const bounds = map.getBounds();
  return { bbox: [bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()], zoom: map.getZoom() };
}

/**
 * 화면 안의 점을 supercluster로 묶어 렌더한다. 묶음은 `renderCluster`, 낱개는 `renderPoint`가 그린다.
 * 지도 이동이 끝날 때만 다시 계산한다.
 */
export function PointClusters<P extends ClusterPoint>({ points, radius = 60, maxZoom = 19, renderPoint, renderCluster }: {
  points: readonly P[];
  radius?: number;
  maxZoom?: number;
  renderPoint: (point: P) => ReactNode;
  renderCluster: (cluster: Supercluster.ClusterFeature<Supercluster.AnyProps>, count: number, index: Supercluster<P, Supercluster.AnyProps>) => ReactNode;
}) {
  const map = useVWorldMap();
  const [viewport, setViewport] = useState<Viewport | null>(null);
  useEffect(() => {
    if (map === null) return;
    const update = () => setViewport((previous) => {
      const next = viewportOf(map);
      return previous && previous.zoom === next.zoom && previous.bbox.every((value, index) => value === next.bbox[index]) ? previous : next;
    });
    update();
    map.on("moveend", update);
    map.on("resize", update);
    return () => { map.off("moveend", update); map.off("resize", update); };
  }, [map]);

  const index = useMemo(() => {
    const cluster = new Supercluster<P, Supercluster.AnyProps>({ radius, maxZoom });
    cluster.load(points.map((point) => ({ type: "Feature", properties: point, geometry: { type: "Point", coordinates: point.lngLat } })));
    return cluster;
  }, [points, radius, maxZoom]);

  if (viewport === null) return null;
  return <>{index.getClusters(viewport.bbox, Math.floor(viewport.zoom)).map((feature) => {
    if ((feature.properties as Partial<Supercluster.ClusterProperties>).cluster) {
      const cluster = feature as Supercluster.ClusterFeature<Supercluster.AnyProps>;
      // cluster_id는 확대 단계를 품고 있어 같은 묶음도 zoom이 바뀌면 달라진다. 위치·개수로 key를 잡아 같은 묶음의
      // DOM(과 그 위의 포커스)을 재사용한다.
      const [clusterLng, clusterLat] = cluster.geometry.coordinates;
      return <Fragment key={`cluster-${clusterLng.toFixed(6)},${clusterLat.toFixed(6)}:${cluster.properties.point_count}`}>{renderCluster(cluster, cluster.properties.point_count, index)}</Fragment>;
    }
    const point = feature.properties as P;
    return <Fragment key={point.id}>{renderPoint(point)}</Fragment>;
  })}</>;
}
