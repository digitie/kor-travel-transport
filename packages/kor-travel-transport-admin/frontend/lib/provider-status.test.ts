import {expect, test} from "vitest";
import {isolatedRows, jobStatusLabel, needsProviderAttention, providerStatusLabel} from "./provider-status";

test.each(["failed", "upstream_error", "not_collected", "shared_job_failed", "shared_job_upstream_error", "shared_job_not_collected"])("%s는 오류 코드가 없어도 확인이 필요하다", (status) => {
  expect(needsProviderAttention({enabled: true, status, error_code: null})).toBe(true);
});
test("정상과 비활성은 확인 필요 집계에서 제외한다", () => {
  expect(needsProviderAttention({enabled: true, status: "shared_job_success", error_code: null})).toBe(false);
  expect(needsProviderAttention({enabled: false, status: "shared_job_not_collected", error_code: null})).toBe(false);
});

test("격리만 있는 부분 성공은 공항·고속도로 모두 같은 문구이고 확인 필요로 세지 않는다", () => {
  const fallback = (status: string) => `fallback:${status}`;
  expect(providerStatusLabel({status: "shared_job_partial_success", isolated_rows: 1}, fallback)).toBe("공동 작업 부분 성공(격리 1건)");
  expect(providerStatusLabel({status: "partial_success", isolated_rows: 1250}, fallback)).toBe("부분 성공(격리 1,250건)");
  expect(providerStatusLabel({status: "failed", isolated_rows: null}, fallback)).toBe("fallback:failed");
  expect(isolatedRows({isolated_rows: 0})).toBeNull();
  expect(needsProviderAttention({enabled: true, status: "shared_job_partial_success", error_code: null})).toBe(false);
  expect(needsProviderAttention({enabled: true, status: "partial_success", error_code: null})).toBe(false);
});

test("공동 job 상태도 격리만 있으면 부분 성공이고, 오류 코드가 함께 오면 실패 문구를 쓴다", () => {
  const fallback = (status: string) => `fallback:${status}`;
  expect(jobStatusLabel({job_status: "partial_success", job_isolated_rows: 4}, fallback)).toBe("부분 성공(격리 4건)");
  expect(jobStatusLabel({job_status: "partial_success", job_isolated_rows: null}, fallback)).toBe("fallback:partial_success");
  expect(jobStatusLabel({job_status: null}, fallback)).toBe("이력 없음");
  expect(providerStatusLabel({status: "shared_job_partial_success", isolated_rows: 1, error_code: "collection_failed"}, fallback))
    .toBe("fallback:shared_job_partial_success");
});
