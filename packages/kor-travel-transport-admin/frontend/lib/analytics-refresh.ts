import type { StatusTone } from "@/lib/status-label";

/** `/v1/transport/providers`의 `airport_analytics_cache`(backend `AnalyticsRefreshStatus`). */
export type AnalyticsRefreshStatus = {
  status: "ok" | "empty" | "delayed" | "stale" | "missing";
  alerting: boolean;
  generated_at: string | null;
  pending_since: string | null;
  pending_seconds: number | null;
  generated_age_seconds?: number | null;
  warn_after_seconds: number;
  fallback_after_seconds: number;
};

export type AnalyticsRefreshView = { label: string; tone: StatusTone; detail: string; alerting: boolean };

function minutes(seconds: number | null | undefined) {
  return Math.max(0, Math.floor((seconds ?? 0) / 60));
}

/**
 * 공항 통계 사전집계(대시보드 묶음) 갱신 상태의 운영 화면 문구.
 * 경보(delayed·stale·missing)면 같은 판정으로 공항 수집 run에 `kortravel/analytics-refresh` 태그가 붙는다(run은 SUCCESS).
 */
export function analyticsRefreshView(
  value: AnalyticsRefreshStatus | null | undefined,
  clock: (iso: string | null) => string,
): AnalyticsRefreshView | null {
  if (!value) return null;
  const pending = minutes(value.pending_seconds);
  const fallback = minutes(value.fallback_after_seconds);
  switch (value.status) {
    case "ok":
      if (!value.generated_at) {
        // 첫 사전집계를 만드는 중(관측 뒤 경보 기준 안).
        return { label: "첫 갱신 대기", tone: "neutral", alerting: false, detail: `첫 관측 뒤 ${pending}분째 사전집계를 기다립니다.` };
      }
      return {
        label: "정상", tone: "success", alerting: false,
        detail: pending > 0 ? `${clock(value.generated_at)} 생성 · 새 적재 ${pending}분째 갱신 대기` : `${clock(value.generated_at)} 생성`,
      };
    case "delayed":
      return {
        label: "갱신 지연", tone: "warning", alerting: true,
        detail: `새 적재가 ${pending}분째 사전집계에 반영되지 않았습니다. ${fallback}분을 넘기면 대시보드가 원본 계산으로 느려집니다.`,
      };
    case "stale":
      return {
        label: "원본 계산 중", tone: "destructive", alerting: true,
        detail: pending >= fallback
          ? `사전집계 갱신이 ${pending}분째 밀려 대시보드가 원본에서 계산합니다(느림·504 위험).`
          : `사전집계가 ${minutes(value.generated_age_seconds)}분째(${clock(value.generated_at)} 생성) 갱신되지 않아 대시보드가 원본에서 계산합니다.`,
      };
    case "missing":
      return { label: "사전집계 없음", tone: "destructive", alerting: true, detail: "관측은 있는데 기본 사전집계가 없습니다." };
    case "empty":
      return { label: "관측 없음", tone: "neutral", alerting: false, detail: "아직 공항 주차 관측이 없습니다." };
    default:
      return null;
  }
}
