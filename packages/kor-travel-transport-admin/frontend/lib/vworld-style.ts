// kor-travel-map `packages/kor-travel-map-admin/frontend/src/lib/vworld-style.ts`
// (commit 399d6b6a844d0d806dc067ab29aaf8442840f789)의 사본이다. 교통 지도가 Map과 같은 방식으로
// VWorld 배경지도를 그리도록 style 생성 규칙을 그대로 가져왔다. 키가 비면 배경색만 있는 style로
// 지도를 계속 띄운다(마커는 그대로 보인다). 규칙을 바꿀 때는 Map 쪽과 함께 바꾼다.
import type { StyleSpecification } from "maplibre-gl";

// `digitie/maplibre-vworld-react` a7cb0f8의 vworld-map-core/web 경계를
// admin UI에 필요한 범위만 포팅한다. 외부 모노레포 전체를 npm dependency로
// 끌어오지 않고, VWorld URL/style 생성 규칙은 이 파일에서 단일화한다.
const VWORLD_ATTRIBUTION = "공간정보 오픈플랫폼 브이월드";
const VWORLD_WMTS_PATH = /(\/req\/wmts\/1\.0\.0\/)([^/?#]+)(\/)/;

type VWorldMapType = "base" | "satellite" | "hybrid" | "gray" | "midnight";

export type VWorldLayerType =
  | "Base"
  | "gray"
  | "midnight"
  | "Hybrid"
  | "Satellite";

const LAYER_TYPE_TO_MAP_TYPE: Record<VWorldLayerType, VWorldMapType> = {
  Base: "base",
  gray: "gray",
  midnight: "midnight",
  Hybrid: "hybrid",
  Satellite: "satellite",
};

const LAYER_PRESETS: Record<VWorldMapType, { maxZoom: number }> = {
  base: { maxZoom: 19 },
  gray: { maxZoom: 19 },
  midnight: { maxZoom: 19 },
  hybrid: { maxZoom: 18 },
  satellite: { maxZoom: 18 },
};

export function isVWorldApiKeyConfigured(
  apiKey: string | undefined,
): apiKey is string {
  const trimmed = apiKey?.trim();
  return trimmed !== undefined && trimmed.length > 0 && trimmed !== "CHANGE_ME";
}

export function buildVWorldStyle(
  apiKey: string | undefined,
  layerType: VWorldLayerType = "Base",
): StyleSpecification {
  if (isVWorldApiKeyConfigured(apiKey)) {
    return getClientVWorldStyle(apiKey, layerType);
  }
  return {
    version: 8,
    sources: {},
    layers: [
      {
        id: "bg",
        type: "background",
        paint: { "background-color": "#edf1f5" },
      },
    ],
  };
}

function vworldLayerName(mapType: VWorldMapType): string {
  switch (mapType) {
    case "gray":
      return "white";
    case "midnight":
      return "midnight";
    case "hybrid":
      return "Hybrid";
    case "satellite":
      return "Satellite";
    case "base":
    default:
      return "Base";
  }
}

export function getVWorldTileUrl(
  apiKey: string,
  layerType: VWorldLayerType,
): string {
  const mapType = LAYER_TYPE_TO_MAP_TYPE[layerType];
  const extension = mapType === "satellite" ? "jpeg" : "png";
  const layerName = vworldLayerName(mapType);
  return `https://api.vworld.kr/req/wmts/1.0.0/${encodeURIComponent(
    apiKey.trim(),
  )}/${layerName}/{z}/{y}/{x}.${extension}`;
}

export function getVWorldMaxZoom(layerType: VWorldLayerType): number {
  return LAYER_PRESETS[LAYER_TYPE_TO_MAP_TYPE[layerType]].maxZoom;
}

export function redactVWorldUrl(url: string): string;
export function redactVWorldUrl(url: string | undefined): string | undefined;
export function redactVWorldUrl(url: string | undefined): string | undefined {
  return url?.replace(VWORLD_WMTS_PATH, "$1***$3");
}


function getClientVWorldStyle(
  apiKey: string,
  layerType: VWorldLayerType,
): StyleSpecification {
  const maxzoom = getVWorldMaxZoom(layerType);
  const sources: StyleSpecification["sources"] = {};
  const layers: StyleSpecification["layers"] = [];

  const appendRasterLayer = (
    sourceId: string,
    layerId: string,
    sourceLayerType: VWorldLayerType,
  ) => {
    sources[sourceId] = {
      type: "raster",
      tiles: [getVWorldTileUrl(apiKey, sourceLayerType)],
      tileSize: 256,
      attribution: VWORLD_ATTRIBUTION,
      maxzoom,
    };
    layers.push({
      id: layerId,
      type: "raster",
      source: sourceId,
      minzoom: 0,
    });
  };

  if (layerType === "Hybrid") {
    appendRasterLayer(
      "vworld-satellite",
      "vworld-satellite-layer",
      "Satellite",
    );
  }
  appendRasterLayer("vworld-base", "vworld-base-layer", layerType);

  return {
    version: 8,
    sources,
    layers,
  };
}
