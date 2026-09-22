import { describe, expect, it } from "vitest";

import { collectionSourceLabel, fuelProductLabel, highwayRouteLabel } from "./transport-presentation";

describe("교통 화면용 표현 변환", () => {
  it("오피넷 유종 코드를 사람이 읽는 이름으로 바꾼다", () => {
    expect(fuelProductLabel("B027")).toBe("휘발유");
    expect(fuelProductLabel("K015")).toBe("자동차용부탄(LPG)");
  });

  it("고속도로는 저장된 노선명을 우선 표시한다", () => {
    expect(highwayRouteLabel("0010", "경부고속도로")).toBe("경부고속도로");
    expect(highwayRouteLabel("0010")).toBe("0010번 고속도로");
  });

  it("수집 소스를 서비스 이름으로 표시한다", () => {
    expect(collectionSourceLabel("transport_dagster_highway")).toBe("고속도로 소통·돌발 정보");
  });
});
