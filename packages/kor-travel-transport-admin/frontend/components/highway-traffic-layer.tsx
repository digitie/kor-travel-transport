"use client";
import { useEffect, useLayoutEffect, useMemo, useRef } from "react";
import { useMap } from "vworld-map-web";
import type { MapMouseEvent } from "maplibre-gl";
import { highwayFeatures, type HighwayRoadTraffic } from "@/lib/highway-map";

const SOURCE = "its-selected-road", LAYER = "its-selected-road-lines";
export function HighwayTrafficLayer({ data, selectedIndex, selectionRevision, onSelect, onVisibleCount }: {
  data: HighwayRoadTraffic | null; selectedIndex: number | null; selectionRevision: number;
  onSelect: (index: number) => void; onVisibleCount: (count: number) => void;
}) {
  const map = useMap();
  const geojson = useMemo(() => highwayFeatures(data?.items ?? []), [data]);
  const cameraRequested = useRef(selectedIndex !== null);
  const currentData = useRef(data);
  useLayoutEffect(() => {
    if (currentData.current !== data) { currentData.current = data; cameraRequested.current = false; }
    // 상세를 닫아도 이미 요청한 카메라는 보존한다. 새 노선 응답만 전체 맞춤을 다시 허용한다.
    if (selectedIndex !== null) cameraRequested.current = true;
  }, [selectedIndex, data]);
  useEffect(() => {
    if (!map) return;
    let fitted = false;
    const count = () => {
      if (map.getLayer(LAYER)) onVisibleCount(new Set(map.queryRenderedFeatures({ layers: [LAYER] }).map((feature) => feature.id)).size);
    };
    const install = () => {
      if (!map.isStyleLoaded()) return;
      if (!map.getSource(SOURCE)) map.addSource(SOURCE, { type: "geojson", data: geojson });
      if (!map.getLayer(LAYER)) map.addLayer({ id: LAYER, type: "line", source: SOURCE,
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": ["get", "color"], "line-width": 5, "line-opacity": .9 } });
      if (!fitted && geojson.features.length) {
        fitted = true;
        // 늦은 레이어 설치가 목록에서 선택한 구간의 카메라를 전체 노선으로 덮지 않는다.
        if (cameraRequested.current) { count(); return; }
        const points = geojson.features.flatMap((feature) => feature.geometry.coordinates);
        const bounds: [[number, number], [number, number]] = [[Infinity, Infinity], [-Infinity, -Infinity]];
        for (const [lng, lat] of points) {
          bounds[0][0] = Math.min(bounds[0][0], lng); bounds[0][1] = Math.min(bounds[0][1], lat);
          bounds[1][0] = Math.max(bounds[1][0], lng); bounds[1][1] = Math.max(bounds[1][1], lat);
        }
        map.fitBounds(bounds, { padding: 35, maxZoom: 12, duration: 0 });
      }
      count();
    };
    const click = (event: MapMouseEvent) => {
      if (event.originalEvent.target instanceof Element && event.originalEvent.target.closest("button, a, [role=button]")) return;
      if (!map.getLayer(LAYER)) return;
      const found = map.queryRenderedFeatures(event.point, { layers: [LAYER] })[0];
      if (found) onSelect(Number(found.properties.index));
    };
    // styledata는 타일 준비보다 먼저 올 수 있다. 최초 load/유휴와 스타일 교체 뒤에도 설치한다.
    map.on("load", install); map.on("style.load", install); map.on("idle", install); map.on("click", click); install();
    return () => {
      map.off("load", install); map.off("style.load", install); map.off("idle", install); map.off("click", click);
      if (map.getLayer(LAYER)) map.removeLayer(LAYER);
      if (map.getSource(SOURCE)) map.removeSource(SOURCE);
    };
  }, [map, geojson, onSelect, onVisibleCount]);
  useEffect(() => {
    if (!map || selectedIndex == null) return;
    const path = data?.items[selectedIndex]?.path;
    // 이 레이어는 VWorldMapView의 load 이후 자식으로 mount된다.
    if (path?.length) map.easeTo({ center: path[Math.floor(path.length / 2)], zoom: Math.max(11, map.getZoom()) });
  }, [map, selectedIndex, data, selectionRevision]);
  return null;
}
