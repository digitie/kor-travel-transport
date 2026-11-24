import { formatAxisTimeLabel, parseApiDate } from "./format";

/**
 * 기간 분석의 "기준 시각" 표시 규칙.
 *
 * 공항 수집은 5분마다 돌고, 수집 직후 사전집계를 다시 만든다(운영 ARM 수 분). 그래서 평소에도 기준 시각이
 * 현재보다 10~15분 늦을 수 있다. 20분을 넘기면 사전집계 갱신이 밀리거나 실패한 것으로 보고 경고 톤으로 바꾼다
 * (backend는 갱신 실패 뒤 최대 40분, 원천 장애 때 최대 2시간까지 직전 사전집계를 낸다).
 */
export const ANALYTICS_BASIS_LATE_MINUTES = 20;

export type AnalyticsBasis = { time: string; lateMinutes: number | null; late: boolean };

export function analyticsBasis(generatedAt: string | null, receivedAt: number | null): AnalyticsBasis | null {
  if (!generatedAt) return null;
  const generated = parseApiDate(generatedAt).getTime();
  if (Number.isNaN(generated)) return null;
  const lateMinutes = receivedAt === null ? null : Math.max(0, Math.floor((receivedAt - generated) / 60_000));
  return {
    time: formatAxisTimeLabel(generatedAt),
    lateMinutes,
    late: lateMinutes !== null && lateMinutes >= ANALYTICS_BASIS_LATE_MINUTES,
  };
}
