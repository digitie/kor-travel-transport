/** 공용 Dagster에서 수행한 같은 상태도 동일하게 집계한다. */
export function needsProviderAttention(item: {enabled: boolean; status: string; error_code?: string | null}) {
  const status = item.status.replace(/^shared_job_/, "");
  return item.enabled && Boolean(item.error_code || ["failed", "upstream_error", "not_collected"].includes(status));
}
