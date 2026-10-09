"use client";

// 교통 지도가 `digitie/maplibre-vworld-react`(`vworld-map-web`, vendor tarball)의 지도 위에 얹는 부품.
// 지도 엔진·VWorld 타일 protocol·타일 대체 이미지·초기화 실패 대체는 라이브러리가 맡는다
// (`VWorldMapView`의 `unsupportedTileFallback`·`fallback`). 여기에는 라이브러리 API로 표현하지 못하는
// 교통 지도 고유의 겉모양과 접근성만 둔다.
// - 마커 겉모양: Map 공용 `@kor-travel-map/map-marker-react`(vendored)의 24px maki 배지와 Map 묶음 원.
//   라이브러리 `Marker`의 children으로 그린다.
// - `aria-pressed`·포인터 통과: 라이브러리 `Marker`에 prop이 없어 마커 요소에 직접 단다.
// - 카메라 요청: 라이브러리 `cameraTarget`은 값으로 비교해 같은 장소를 다시 눌러도 움직이지 않는다.
//   요청 정체(id)로 비교하도록 `useMap()`으로 직접 옮긴다.
// - 확대/축소 버튼: 라이브러리 `navigation`은 나침반이 붙는다. Map과 같이 나침반 없이 단다.
// - 겹친 지점 팝업 Escape: 라이브러리 `Popup`에 없어 문서 keydown으로 닫는다.
// - 타일 실패: 타일 하나의 실패는 라이브러리 protocol이 대체 이미지로 메운다. 한 번의 그리기(idle)에서
//   요청한 VWorld 타일이 모두 실패했을 때만 배경지도를 불러오지 못한 것으로 본다.

import * as maplibregl from "maplibre-gl";
import {
  isVWorldTileError, Marker, Popup, redactVWorldUrl, useMap,
  type MapErrorEvent, type RequestTransformFunction, type VWorldMapFallbackInfo,
} from "vworld-map-web";
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { createMarkerElement } from "@/lib/vendor/map-marker-react";
import { abbreviateClusterCount, clusterBubbleSize } from "@/lib/place-marker-style";

/** 빈 값·자리표시자 키는 라이브러리에 빈 문자열로 넘겨 `missing-api-key` 대체 화면을 쓰게 한다. */
export function vworldApiKey(value: string | undefined): string {
  const trimmed = value?.trim() ?? "";
  return trimmed === "CHANGE_ME" || trimmed.startsWith("replace-with-") ? "" : trimmed;
}

/** 로그에 남기기 전에 메시지 안의 VWorld 키를 가린다(라이브러리 `redactVWorldUrl`은 URL 하나만 가린다). */
export function redactVWorldText(value: string | undefined): string | undefined {
  return value?.replace(/(\/req\/wmts\/1\.0\.0\/)([^/?#\s]+)(\/)/g, "$1***$3");
}

/** Map `SELECTED_OUTLINE` — 선택 강조는 불투명 focus 토큰 outline이다. */
const SELECTED_OUTLINE = "3px solid var(--focus)";

type MapMarkerButtonProps = {
  lngLat: [number, number];
  ariaLabel: string;
  interactionId: string;
  className: string;
  title?: string;
  zIndex?: number;
  isCluster?: boolean;
  /** 위에 그리되 마우스·터치는 아래 마커로 통과시킨다(키보드로는 그대로 고른다). */
  passThrough?: boolean;
  /** 선택 상태를 `aria-pressed`로 알린다. 생략하면 토글 버튼이 아니다(묶음). */
  pressed?: boolean;
  /** 누른 마커 요소를 넘긴다(팝업을 닫을 때 그 자리로 포커스를 돌려주는 데 쓴다). */
  onClick: (element: HTMLElement) => void;
  children: ReactNode;
};

/**
 * 라이브러리 `Marker`(role=button, Enter·Space, interactionId)에 교통 지도 접근성을 더한다.
 * 라이브러리는 children을 `마커 요소 > div > children`으로 portal한다. 마커 요소는 MapLibre가 쓰기 전에
 * 이미 정해지므로(같은 div가 `new Marker({ element })`로 넘어간다) 두 단계 위가 마커 요소다.
 */
export function MapMarkerButton({ lngLat, ariaLabel, interactionId, className, title, zIndex, isCluster, passThrough = false, pressed, onClick, children }: MapMarkerButtonProps) {
  const contentRef = useRef<HTMLSpanElement | null>(null);
  useLayoutEffect(() => {
    const host = contentRef.current?.parentElement?.parentElement;
    if (!host) return;
    if (pressed === undefined) host.removeAttribute("aria-pressed");
    else host.setAttribute("aria-pressed", String(pressed));
    host.style.pointerEvents = passThrough ? "none" : "";
  }, [pressed, passThrough]);
  return <Marker lngLat={lngLat} ariaLabel={ariaLabel} interactionId={interactionId} className={className} zIndex={zIndex} isCluster={isCluster}
    onClick={(_event, _context, marker) => onClick(marker.getElement())}>
    <span ref={contentRef} className="map-marker-content" title={title}>{children}</span>
  </Marker>;
}

/** Map 공용 마커 배지(24px 원 + maki 글리프). `createMarkerElement`가 만든 요소를 그대로 붙인다. */
export function MarkerBadge({ markerIcon, markerColor, selected = false }: { markerIcon: string; markerColor: string | null; selected?: boolean }) {
  const hostRef = useRef<HTMLSpanElement | null>(null);
  useLayoutEffect(() => {
    const host = hostRef.current;
    if (host === null) return;
    const element = createMarkerElement({ markerIcon, markerColor, size: 24 });
    // 접근 이름은 바깥 마커 버튼이 갖는다. 배지는 장식이다.
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

/**
 * Map 겹친 지점 팝업과 같은 옵션(닫기 버튼, 지도 클릭으로 닫지 않음)의 라이브러리 `Popup`.
 * Escape는 팝업 안 어디에 포커스가 있든(목록 버튼·닫기 버튼) 팝업을 닫는다.
 */
export function OverlapPopup({ lngLat, onClose, children }: { lngLat: [number, number]; onClose: () => void; children: ReactNode }) {
  const contentRef = useRef<HTMLDivElement | null>(null);
  const onCloseRef = useRef(onClose);
  useLayoutEffect(() => { onCloseRef.current = onClose; });
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      const popup = contentRef.current?.closest(".maplibregl-popup");
      if (!popup || !(event.target instanceof Node) || !popup.contains(event.target)) return;
      event.preventDefault();
      event.stopPropagation();
      onCloseRef.current();
    };
    document.addEventListener("keydown", handleKeyDown, true);
    return () => document.removeEventListener("keydown", handleKeyDown, true);
  }, []);
  return <Popup lngLat={lngLat} closeButton closeOnClick={false} maxWidth="260px" className="map-overlap-popup" onClose={onClose}>
    <div ref={contentRef}>{children}</div>
  </Popup>;
}

/**
 * 카메라 이동 요청. `id`가 요청의 정체다 — 같은 위치·확대라도 id가 바뀌면 다시 이동한다(손으로 옮긴 뒤
 * 같은 묶음·장소를 다시 누른 경우). 같은 id의 재렌더는 사용자가 옮긴 화면을 되돌리지 않는다.
 */
export type CameraTarget = { center: [number, number]; zoom: number; id: string | number };

/** 지도가 준비된 뒤 첫 요청은 바로 옮기고(초기 카메라), 그 뒤 요청은 부드럽게 옮긴다. */
export function CameraRequest({ target }: { target: CameraTarget | undefined }) {
  const map = useMap();
  const appliedRef = useRef<string | number | undefined>(undefined);
  const firstRef = useRef(true);
  const lng = target?.center[0];
  const lat = target?.center[1];
  const zoom = target?.zoom;
  const id = target?.id;
  useEffect(() => {
    if (map === null) return;
    const first = firstRef.current;
    firstRef.current = false;
    if (lng === undefined || lat === undefined || zoom === undefined || id === undefined || appliedRef.current === id) return;
    appliedRef.current = id;
    const camera = { center: [lng, lat] as [number, number], zoom: Math.min(zoom, map.getMaxZoom()) };
    if (first) map.jumpTo(camera);
    else map.easeTo(camera);
  }, [map, lng, lat, zoom, id]);
  return null;
}

/** Map과 같은 확대/축소 버튼(나침반 없음, 오른쪽 위). 축척은 라이브러리 `scale`(150px·미터, 오른쪽 아래)을 쓴다. */
export function ZoomButtons() {
  const map = useMap();
  useEffect(() => {
    if (map === null) return;
    const control = new maplibregl.NavigationControl({ showCompass: false });
    map.addControl(control, "top-right");
    // e2e 훅(Map과 같다): 컨테이너 DOM에 지도 인스턴스를 매달아 Playwright가 카메라·bounds를 단언할 수 있게 한다.
    const container = map.getContainer() as HTMLElement & { _maplibreMap?: maplibregl.Map };
    container._maplibreMap = map;
    return () => {
      delete container._maplibreMap;
      try { map.removeControl(control); } catch { /* 지도가 이미 지워졌다 */ }
    };
  }, [map]);
  return null;
}

/** 지도를 만들지 못했을 때(키 없음·WebGL 없음) 지도 자리에 보인다. 오류는 키를 가려 한 번 남긴다. */
export function MapUnavailable({ info }: { info: VWorldMapFallbackInfo }) {
  useEffect(() => {
    if (info.error) console.warn("[TransportMap] 지도를 초기화하지 못했습니다", redactVWorldText(info.error.message));
  }, [info.error]);
  return <p className="empty-state">{info.reason === "missing-api-key"
    ? "VWorld 지도 키가 없어 지도를 표시하지 못합니다. 위의 목록 보기에서 장소를 선택해 주세요."
    : "이 브라우저에서 지도를 표시하지 못합니다. 위의 목록 보기에서 장소를 선택해 주세요."}</p>;
}

const WMTS_TILE = /\/req\/wmts\/1\.0\.0\/[^/?#]+\/([^?#]+)/;

/**
 * VWorld 배경지도 상태. 라이브러리 `transformRequest`로 요청한 타일을, `onError`(타일 protocol이 대체
 * 이미지로 메운 실패도 여기로 온다)로 실패한 타일을 센다. `onIdle`마다 그 사이 요청한 타일이 모두 실패했으면
 * 배경지도를 불러오지 못한 것으로, 하나라도 성공했으면 회복한 것으로 본다. 타일 하나의 실패(서비스 영역
 * 밖·일시 오류)로는 화면 안내를 띄우지 않는다.
 */
export function useVWorldBasemapHealth() {
  const [basemapFailed, setBasemapFailed] = useState(false);
  const requestedRef = useRef(new Set<string>());
  const failedRef = useRef(new Map<string, string>());
  const transformRequest = useCallback<RequestTransformFunction>((url) => {
    const tile = WMTS_TILE.exec(url)?.[1];
    if (tile) requestedRef.current.add(tile);
    return { url };
  }, []);
  const onError = useCallback((event: MapErrorEvent) => {
    const error = event.error as { message?: string; url?: string } | undefined;
    const tile = error?.url ? WMTS_TILE.exec(error.url)?.[1] : undefined;
    if (tile && isVWorldTileError(event)) {
      // 타일마다 남기지 않고 idle에 한 줄로 요약한다. URL은 키를 가린 것만 갖고 있는다.
      failedRef.current.set(tile, redactVWorldUrl(error?.url ?? ""));
      return;
    }
    console.warn("[TransportMap]", redactVWorldText(error?.message) ?? "unknown map error", redactVWorldUrl(error?.url) ?? "");
  }, []);
  const onIdle = useCallback(() => {
    const requested = requestedRef.current.size;
    const failures = [...failedRef.current].filter(([tile]) => requestedRef.current.has(tile));
    requestedRef.current = new Set();
    failedRef.current = new Map();
    if (requested === 0) return;
    if (failures.length) console.warn(`[TransportMap] VWorld 타일 ${failures.length}/${requested}개를 불러오지 못했습니다(대체 이미지로 표시)`, failures[0][1]);
    setBasemapFailed(failures.length >= requested);
  }, []);
  return { basemapFailed, transformRequest, onError, onIdle };
}
