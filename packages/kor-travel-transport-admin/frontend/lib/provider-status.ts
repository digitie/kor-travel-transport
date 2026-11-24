/** 공용 Dagster에서 수행한 같은 상태도 동일하게 집계한다. */
export function needsProviderAttention(item: {enabled: boolean; status: string; error_code?: string | null}) {
  const status = item.status.replace(/^shared_job_/, "");
  return item.enabled && Boolean(item.error_code || ["failed", "upstream_error", "not_collected"].includes(status));
}

/** 무효 원천 행만 격리한 부분 성공(유효 행은 저장)이면 그 건수. 공항·고속도로 모두 같은 문구로 보인다. */
export function isolatedRows(item: {isolated_rows?: number | null}): number | null {
  return typeof item.isolated_rows === "number" && item.isolated_rows > 0 ? item.isolated_rows : null;
}

/** 운영 상태 목록의 상태 문구. 격리만 있는 부분 성공은 실패가 아니라 "부분 성공(격리 N건)"이다. */
export function providerStatusLabel(item: {status: string; isolated_rows?: number | null}, fallback: (status: string) => string): string {
  const isolated = isolatedRows(item);
  if (isolated === null) return fallback(item.status);
  const label = `부분 성공(격리 ${isolated.toLocaleString("ko-KR")}건)`;
  return item.status.startsWith("shared_job_") ? `공동 작업 ${label}` : label;
}
