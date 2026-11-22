// 공개 유가(TRANSPORT_UI_MODE=fuel) 전용: "지역 이동" 대화상자가 처음 열릴 때 미리 고를 시/도·구/군/시.
// 관리 화면은 이 파일을 쓰지 않는다.

type Bounds = readonly [number, number, number, number];
export type FuelCatalogLike = { items: { sido_value: string; sigungu: { sigungu_value: string; bounds: Bounds }[] }[] };
export type FuelRegionDefault = { sido_value: string; sigungu_value?: string };

/**
 * 1) 지역 칩(고른 지역·지도 중심 시군구·화면 1순위)이 목록에 있으면 그것.
 * 2) 칩이 없으면(places 요청 실패·대기) 지금 지도 중심을 담는 시군구 중 범위가 가장 작은 것,
 *    담는 곳이 없으면(바다 등) 범위 가운데가 가장 가까운 시군구.
 * 3) 둘 다 없으면 undefined(첫 시/도, 구/군/시는 미선택).
 */
export function fuelRegionDefault(
  catalog: FuelCatalogLike | undefined,
  current?: { sido_value: string; sigungu_value: string },
  center?: readonly [number, number],
): FuelRegionDefault | undefined {
  if (!catalog) return undefined;
  if (current) {
    const sido = catalog.items.find(row => row.sido_value === current.sido_value);
    if (sido?.sigungu.some(row => row.sigungu_value === current.sigungu_value)) return { ...current };
    if (sido && !center) return { sido_value: sido.sido_value };
  }
  if (!center || !center.every(Number.isFinite)) return undefined;
  const [longitude, latitude] = center;
  const scale = Math.cos(latitude * Math.PI / 180);
  let containing: { choice: FuelRegionDefault; area: number } | undefined;
  let nearest: { choice: FuelRegionDefault; distance: number } | undefined;
  for (const sido of catalog.items) {
    for (const row of sido.sigungu) {
      const [west, south, east, north] = row.bounds;
      const choice = { sido_value: sido.sido_value, sigungu_value: row.sigungu_value };
      if (longitude >= west && longitude <= east && latitude >= south && latitude <= north) {
        const area = (east - west) * scale * (north - south);
        if (!containing || area < containing.area) containing = { choice, area };
      } else if (!containing) {
        const distance = Math.hypot(((west + east) / 2 - longitude) * scale, (south + north) / 2 - latitude);
        if (!nearest || distance < nearest.distance) nearest = { choice, distance };
      }
    }
  }
  return containing?.choice ?? nearest?.choice;
}
