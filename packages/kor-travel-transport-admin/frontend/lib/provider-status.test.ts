import {expect, test} from "vitest";
import {needsProviderAttention} from "./provider-status";

test.each(["failed", "upstream_error", "not_collected", "shared_job_failed", "shared_job_upstream_error", "shared_job_not_collected"])("%s는 오류 코드가 없어도 확인이 필요하다", (status) => {
  expect(needsProviderAttention({enabled: true, status, error_code: null})).toBe(true);
});
test("정상과 비활성은 확인 필요 집계에서 제외한다", () => {
  expect(needsProviderAttention({enabled: true, status: "shared_job_success", error_code: null})).toBe(false);
  expect(needsProviderAttention({enabled: false, status: "shared_job_not_collected", error_code: null})).toBe(false);
});
