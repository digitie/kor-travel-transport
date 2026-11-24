import { formatDateTimeWithZone, parseApiDate } from "./format";

/**
 * 기간 분석의 "분석 기준" 시각 표시 규칙.
 *
 * 공항 수집과 사전집계 갱신은 한 job에서 돈다(수집 4~9분 + 갱신 운영 ARM 약 5분, 이전 run이 끝나야 다음 run).
 * 그래서 다음 갱신이 보이기 직전 사전집계는 정상이어도 약 20분까지 늙는다. 30분을 넘기면 갱신이 밀린 것으로 보고
 * 경고 톤으로 바꾼다(backend는 갱신 실패 뒤 최대 40분, 새 적재가 없으면 최대 2시간까지 직전 사전집계를 낸다).
 *
 * 나이는 서버가 잰 값(`analytics_age_seconds`)에 응답을 받은 뒤 흐른 시간만 더한다. 브라우저 시계가 틀려도
 * 판정이 뒤집히지 않고, 재조회가 실패해 화면이 멈춰도 나이는 계속 는다.
 */
export const ANALYTICS_BASIS_LATE_MINUTES = 30;

export type AnalyticsBasis = { dateTime: string; label: string; ageMinutes: number; late: boolean };

export function analyticsBasis(
  generatedAt: string | null,
  serverAgeSeconds: number | null,
  receivedAt: number | null,
  now: number,
): AnalyticsBasis | null {
  if (!generatedAt) return null;
  const generated = parseApiDate(generatedAt).getTime();
  if (Number.isNaN(generated)) return null;
  const elapsed = receivedAt === null ? 0 : Math.max(0, now - receivedAt);
  // 서버 나이가 없으면(필드 추가 전 backend) 받은 시각 기준 브라우저 계산으로 대신한다.
  const baseMs = typeof serverAgeSeconds === "number" ? serverAgeSeconds * 1000 : Math.max(0, (receivedAt ?? now) - generated);
  const ageMinutes = Math.floor((baseMs + elapsed) / 60_000);
  return {
    dateTime: new Date(generated).toISOString(),
    label: formatDateTimeWithZone(generatedAt),
    ageMinutes,
    late: ageMinutes >= ANALYTICS_BASIS_LATE_MINUTES,
  };
}
