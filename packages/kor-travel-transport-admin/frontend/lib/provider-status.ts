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
export function providerStatusLabel(item: {status: string; isolated_rows?: number | null; error_code?: string | null}, fallback: (status: string) => string): string {
  const isolated = isolatedRows(item);
  // 오류 코드가 함께 오면(방어) 실패 쪽 문구를 그대로 쓴다 — 빨간 "부분 성공" 배지를 만들지 않는다.
  if (isolated === null || item.error_code) return fallback(item.status);
  const label = `부분 성공(격리 ${isolated.toLocaleString("ko-KR")}건)`;
  return item.status.startsWith("shared_job_") ? `공동 작업 ${label}` : label;
}

/** 공동 job 상태 문구. 격리만 있는 부분 성공 실행은 "일부 실패"가 아니라 "부분 성공(격리 N건)"이다. */
export function jobStatusLabel(item: {job_status?: string | null; job_isolated_rows?: number | null}, fallback: (status: string) => string): string {
  if (!item.job_status) return "이력 없음";
  const isolated = typeof item.job_isolated_rows === "number" && item.job_isolated_rows > 0 ? item.job_isolated_rows : null;
  return isolated === null ? fallback(item.job_status) : `부분 성공(격리 ${isolated.toLocaleString("ko-KR")}건)`;
}

/** 운영 상태 목록의 오류 안내. 실행 소실(collection_lost)은 원인 미상 실패와 달리 같은 회차를 재시도로 이어 할 수 있다. */
export function providerErrorMessage(item: {source: string; error_code?: string | null}): string | null {
  if (!item.error_code) return null;
  if (item.source === "fuel_latest_prices") {
    return item.error_code === "read_model_refresh_pending"
      ? "유가 원본이 최신 가격 읽기 모델보다 새롭습니다. 다음 고속도로 수집에서 갱신합니다."
      : "유가 원본은 저장됐지만 최신 가격 읽기 모델 갱신이 지연됩니다. 상단 경고와 다음 재시도 시각을 확인해 주세요.";
  }
  if (item.error_code === "collection_lost") {
    return "실행 소실 · 수집 실행이 결과를 남기지 못하고 끝났습니다(작업자 재시작·강제 종료). 마지막 정상 자료는 그대로입니다. 실패한 실행의 재시도로 저장된 진행분에서 이어 할 수 있습니다.";
  }
  return "수집 실패 · Dagster 실행 로그에서 원인을 확인해 주세요.";
}
