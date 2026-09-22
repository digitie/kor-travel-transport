import { describe, expect, it } from "vitest";

import { transportUpstreamUrl } from "./upstream";

describe("transport upstream URL", () => {
  it("허용한 transport read endpoint와 반복 query를 그대로 만든다", () => {
    const url = transportUpstreamUrl(["transport", "highways", "traffic"], new URLSearchParams([["route_no", "1"], ["route_no", "10"]]));
    expect(url?.toString()).toContain("/v1/transport/highways/traffic?route_no=1&route_no=10");
  });
  it("admin write endpoint는 upstream URL을 만들지 않는다", () => {
    expect(transportUpstreamUrl(["admin", "collect"], new URLSearchParams())).toBeNull();
  });
});
