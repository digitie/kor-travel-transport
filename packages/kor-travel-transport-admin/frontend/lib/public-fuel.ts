import { z } from "zod";
import { TransportError } from "./journey";

/** 기존 지도 reader의 경로를 공개 유가 BFF의 한정된 연산으로 바꾼다. */
export async function publicFuelGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  const [pathname, query] = path.split("?", 2);
  const operation = pathname === "features/places" ? "places"
    : pathname.startsWith("fuel/") ? pathname.slice(5) : pathname;
  if (!/^(places|stations|statistics|price-distribution|area-catalog|health|stations\/[1-9][0-9]*\/price-history)$/.test(operation)) {
    throw new TransportError("허용되지 않은 유가 조회입니다.", 404, 0);
  }
  const response = await fetch(`/api/public/fuel/${operation}${query ? `?${query}` : ""}`, {
    cache: "no-store", credentials: "omit", signal,
  });
  if (!response.ok) {
    const seconds = Number(response.headers.get("retry-after") ?? "0");
    // backend가 준 한국어 안내(혼잡·시한 초과)는 그대로 보여 준다. 그 밖의 본문은 내부 표현일 수 있어 쓰지 않는다.
    const body = await response.json().catch(() => null) as { detail?: unknown } | null;
    const message = typeof body?.detail === "string" && /[가-힣]/.test(body.detail)
      ? body.detail : "유가 정보를 불러오지 못했습니다. 다시 확인해 주세요.";
    throw new TransportError(message, response.status, Number.isFinite(seconds) ? Math.max(0, seconds) : 0);
  }
  return response.json() as Promise<T>;
}

export type FuelRefreshBounds = {
  min_longitude: number;
  min_latitude: number;
  max_longitude: number;
  max_latitude: number;
};

export type FuelRefreshRequest = { station_id: number } | {
  viewport: FuelRefreshBounds & { product_codes?: string[] };
};

const fuelRefreshResponse = z.object({
  results: z.array(z.object({
    station_id: z.number().int().positive(),
    status: z.enum(["updated", "unchanged", "cooldown", "unsupported", "rate_limited", "error"]),
  })).max(9),
});

export async function refreshPublicFuel(target: FuelRefreshRequest) {
  const response = await fetch("/api/public/fuel/refresh", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(target),
    cache: "no-store",
    credentials: "omit",
  });
  if (!response.ok) throw refreshError(response.status);
  const payload: unknown = await response.json();
  const streamedError = streamedRefreshError.safeParse(payload);
  if (streamedError.success) throw refreshError(streamedError.data.error_status);
  return fuelRefreshResponse.parse(payload);
}

const streamedRefreshError = z.object({ error_status: z.number().int().min(400).max(599) });

function refreshError(status: number) {
  const detail = status === 429 ? "잠시 뒤 다시 시도해 주세요."
    : status === 409 || status === 422 ? "지도 범위를 좁힌 뒤 다시 시도해 주세요."
    : "유가를 업데이트하지 못했습니다.";
  return new TransportError(detail, status, 0);
}
