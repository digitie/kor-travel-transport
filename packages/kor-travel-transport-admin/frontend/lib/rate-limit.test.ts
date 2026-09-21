import { afterEach, describe, expect, it } from "vitest";

import { clearFailedLogins, loginRateLimited, recordFailedLogin, resetLoginRateLimitForTests } from "./rate-limit";

afterEach(resetLoginRateLimitForTests);

describe("로그인 rate limit", () => {
  it("10분 창에서 다섯 번 실패한 뒤 요청을 제한한다", () => {
    for (let index = 0; index < 5; index += 1) recordFailedLogin("client", 1000);
    expect(loginRateLimited("client", 1001)).toBe(true);
    expect(loginRateLimited("client", 1000 + 10 * 60 * 1000)).toBe(false);
  });
  it("성공하면 같은 client의 실패 횟수를 지운다", () => {
    recordFailedLogin("client"); clearFailedLogins("client");
    expect(loginRateLimited("client")).toBe(false);
  });
});
