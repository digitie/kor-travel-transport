import { TransportError } from "./journey";

/** 기존 지도 reader의 경로를 공개 유가 BFF의 한정된 연산으로 바꾼다. */
export async function publicFuelGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  const [pathname, query] = path.split("?", 2);
  const operation = pathname === "features/places" ? "places"
    : pathname.startsWith("fuel/") ? pathname.slice(5) : pathname;
  if (!/^(places|stations|statistics|health|stations\/[1-9][0-9]*\/price-history)$/.test(operation)) {
    throw new TransportError("허용되지 않은 유가 조회입니다.", 404, 0);
  }
  const response = await fetch(`/api/public/fuel/${operation}${query ? `?${query}` : ""}`, {
    cache: "no-store", credentials: "omit", signal,
  });
  if (!response.ok) {
    const seconds = Number(response.headers.get("retry-after") ?? "0");
    throw new TransportError("유가 정보를 불러오지 못했습니다. 다시 확인해 주세요.", response.status,
      Number.isFinite(seconds) ? Math.max(0, seconds) : 0);
  }
  return response.json() as Promise<T>;
}
