/** 내 위치 찾기 실패 종류. 사용자 문구는 종류마다 다르다(권한 거부는 다시 눌러도 풀리지 않는다). */
export type LocateFailure = "unsupported" | "insecure" | "denied" | "unavailable" | "timeout" | "outside";

/**
 * 위치 요청 단계. 먼저 캐시·저정밀(Wi-Fi/기지국) 위치로 빨리 답하고, 실패(시간 초과·확인 불가)하면
 * 고정밀(GPS)로 한 번 더 시도한다. `timeout`은 권한 허용 뒤부터 세므로 권한 창을 보는 시간은 포함되지 않는다.
 */
export const LOCATE_ATTEMPTS: readonly PositionOptions[] = [
  { enableHighAccuracy: false, maximumAge: 60_000, timeout: 10_000 },
  { enableHighAccuracy: true, maximumAge: 300_000, timeout: 15_000 },
];

/** 권한 창이 끝내 응답하지 않는 브라우저를 위한 안전 상한. 단계 timeout의 합보다 길게 둔다. */
export const LOCATE_WATCHDOG_MS = 30_000;

export const LOCATE_MESSAGES: Record<LocateFailure, string> = {
  unsupported: "이 브라우저에서는 위치를 사용할 수 없습니다.",
  insecure: "보안 연결(HTTPS)에서만 위치를 사용할 수 있습니다.",
  denied: "위치 권한이 거부되었습니다. 브라우저 설정에서 이 사이트의 위치 권한을 허용해 주세요.",
  unavailable: "현재 위치를 확인할 수 없습니다. 잠시 뒤 다시 시도해 주세요.",
  timeout: "위치 확인 시간이 초과되었습니다. 다시 시도해 주세요.",
  outside: "국내 위치에서만 주변 유가를 볼 수 있습니다.",
};

/** 다시 시도로 풀릴 수 있는 실패만 재시도 버튼을 보인다. */
export const RETRYABLE_LOCATE_FAILURES: ReadonlySet<LocateFailure> = new Set(["unavailable", "timeout"]);

const PERMISSION_DENIED = 1;
const TIMEOUT = 3;

/** 단계별로 위치를 요청한다. 권한 거부는 즉시 끝내고, 그 밖의 실패는 다음 단계로 넘긴다. */
export function requestUserPosition(
  geolocation: Geolocation, attempts: readonly PositionOptions[] = LOCATE_ATTEMPTS,
): Promise<GeolocationPosition> {
  return new Promise((resolve, reject) => {
    const attempt = (index: number) => {
      const onError = (error: Partial<GeolocationPositionError> | undefined) => {
        const code = error?.code;
        if (code === PERMISSION_DENIED) { reject("denied" satisfies LocateFailure); return; }
        if (index + 1 < attempts.length) { attempt(index + 1); return; }
        reject((code === TIMEOUT ? "timeout" : "unavailable") satisfies LocateFailure);
      };
      try { geolocation.getCurrentPosition(resolve, onError, attempts[index]); }
      catch { onError(undefined); }
    };
    attempt(0);
  });
}

export function isLocateFailure(value: unknown): value is LocateFailure {
  return typeof value === "string" && Object.hasOwn(LOCATE_MESSAGES, value);
}
