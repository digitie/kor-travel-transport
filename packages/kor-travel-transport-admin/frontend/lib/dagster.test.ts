import { expect, test } from "vitest";
import { statusLabel } from "./dagster";

test("수집 전 보호 대기는 성공이나 장애로 표시하지 않는다", () => {
  expect(statusLabel("throttled")).toBe("호출 보호 대기");
  expect(statusLabel("not_collected")).toBe("수집 이력 없음");
});
