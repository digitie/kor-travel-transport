import { describe, expect, it } from "vitest";
import {
  currentScope, historyPath, kstDay, listScope, missingRegionName, parseStatisticsView, plausiblePoints, publicMapHref, regionOptions, resolveRegion, sigunguGroups, statisticsPath,
  statisticsAgeHours, statisticsViewQuery, trendSummary, type PublicFuelMetrics, type PublicFuelTrendPoint,
} from "./public-fuel-statistics";

const metric = (scope_key: string, label: string): PublicFuelMetrics => ({ scope_key, label, generated_at: "2026-11-27T00:31:44Z",
  station_count: 1, average_price: 1800, minimum_price: 1700, maximum_price: 1900 });
const point = (day: string, average_price: number, minimum_price: number | null = average_price - 100, maximum_price: number | null = average_price + 100): PublicFuelTrendPoint => ({
  product_code: "B027", day, first_day: day, last_day: day, day_count: 1, generated_at: `${day}T00:00:00Z`, average_price, minimum_price, maximum_price, station_count: 10 });

describe("화면 상태 URL", () => {
  it("모르는 값은 기본값으로 두고 기본값은 query에서 뺀다", () => {
    expect(parseStatisticsView(new URLSearchParams("scope=x&product=ZZZ&period=7"))).toEqual({ area: "nationwide", region: "", product: "B027", period: "30" });
    const view = parseStatisticsView({ scope: "sigungu", region: '["서울특별시","강남구"]', product: ["D047", "B027"], period: "365" });
    expect(view).toEqual({ area: "sigungu", region: '["서울특별시","강남구"]', product: "D047", period: "365" });
    expect(parseStatisticsView(new URLSearchParams(statisticsViewQuery(view)))).toEqual(view);
    expect(statisticsViewQuery({ area: "nationwide", region: "ignored", product: "B027", period: "30" })).toBe("");
    expect(parseStatisticsView({ region: "x".repeat(513) }).region).toBe("");
  });
});

describe("요청 경로", () => {
  it("고속도로 전체 노선은 highways, 노선은 highway로 읽는다", () => {
    expect(listScope("highway")).toBe("highway");
    expect(currentScope({ area: "highway", region: "" })).toBe("highways");
    expect(currentScope({ area: "highway", region: "all" })).toBe("highways");
    expect(currentScope({ area: "highway", region: '["0010"]' })).toBe("highway");
    expect(currentScope({ area: "sido", region: "" })).toBe("sido");
  });
  it("공개 세대 KST 날짜까지 기간만큼 일 단위로, 전체는 auto로 묻는다", () => {
    expect(kstDay("2026-11-26T15:30:00Z")).toBe("2026-11-27");
    expect(kstDay(null)).toBeNull();
    const days = new URLSearchParams(historyPath("sido", '["서울특별시"]', "B027", "30", "2026-11-27").split("?")[1]);
    expect(Object.fromEntries(days)).toEqual({ scope: "sido", scope_key: '["서울특별시"]', product_code: "B027", to: "2026-11-27", bucket: "day", from: "2026-10-29" });
    expect(new URLSearchParams(historyPath("sido", "k", "B027", "365", "2026-11-27").split("?")[1]).get("from")).toBe("2025-11-28");
    const all = new URLSearchParams(historyPath("nationwide", "all", "D047", "all", "2026-11-27").split("?")[1]);
    expect(all.get("bucket")).toBe("auto"); expect(all.has("from")).toBe(false);
    expect(historyPath("nationwide", "all", "B027", "30", "2026-11-27")).toMatch(/^fuel\/statistics\/history\?/);
  });
});

describe("지역 선택지", () => {
  const sigungu = [metric('["서울특별시","중구"]', "서울 중구"), metric('["서울특별시","강남구"]', "서울 강남구"),
    metric('["부산광역시","중구"]', "부산 중구"), metric("not-json", "깨진 키")];
  it("시군구를 시도별로 묶고 이름순으로 정렬한다(깨진 key는 뺀다)", () => {
    expect(sigunguGroups(sigungu)).toEqual([
      { sido: "부산광역시", label: "부산", sigungu: [{ key: '["부산광역시","중구"]', label: "중구" }] },
      { sido: "서울특별시", label: "서울", sigungu: [{ key: '["서울특별시","강남구"]', label: "강남구" }, { key: '["서울특별시","중구"]', label: "중구" }] },
    ]);
  });
  it("URL의 지역이 응답에 없으면 서울(없으면 첫 항목)로 바꾸고, 있으면 그대로 쓴다", () => {
    expect(resolveRegion({ area: "sigungu", region: "" }, sigungu)).toBe('["서울특별시","강남구"]');
    expect(resolveRegion({ area: "sigungu", region: '["부산광역시","없는구"]' }, sigungu)).toBe('["부산광역시","중구"]');
    expect(resolveRegion({ area: "sigungu", region: '["서울특별시","중구"]' }, sigungu)).toBe('["서울특별시","중구"]');
    expect(resolveRegion({ area: "sido", region: "" }, [metric('["경기도"]', "경기"), metric('["서울특별시"]', "서울")])).toBe('["서울특별시"]');
    expect(resolveRegion({ area: "highway", region: '["9999"]' }, [metric('["0010"]', "경부선")])).toBe("all");
    expect(resolveRegion({ area: "highway", region: '["0010"]' }, [metric('["0010"]', "경부선")])).toBe('["0010"]');
    expect(resolveRegion({ area: "nationwide", region: "x" }, [metric("all", "전국")])).toBe("all");
  });
});

describe("기간 요약", () => {
  it("처음·마지막 평균 변화와 제공된 최저·최고만 쓴다", () => {
    const summary = trendSummary([point("2026-11-03", 1810, null, null), point("2026-11-01", 1800, 1650, 1990), point("2026-11-02", 1790, 1640, 2000)])!;
    expect(summary.first.day).toBe("2026-11-01"); expect(summary.last.day).toBe("2026-11-03");
    expect(summary.change).toBe(10); expect(summary.changePercent).toBe(0.56);
    expect(summary.lowest).toMatchObject({ price: 1640, point: { day: "2026-11-02" } });
    expect(summary.highest).toMatchObject({ price: 2000 });
    expect(summary.dayCount).toBe(3);
  });
  it("점 하나는 변화가 없고, 점이 없으면 null이다", () => {
    expect(trendSummary([point("2026-11-01", 1800)])?.changePercent).toBeNull();
    expect(trendSummary([])).toBeNull();
    expect(trendSummary([{ ...point("2026-11-01", 1800), minimum_price: null, maximum_price: null }])).toMatchObject({ lowest: null, highest: null });
  });
  it("주·월 점의 기록 일수를 더한다", () => {
    expect(trendSummary([{ ...point("2026-10-26", 1800), day_count: 7 }, { ...point("2026-11-02", 1810), day_count: 3 }])?.dayCount).toBe(10);
  });
});

describe("이상값·안내", () => {
  it("평균의 70% 미만 최저·160% 초과 최고만 뺀다(운영 실제 범위 0.83~1.38은 그대로)", () => {
    const { points, excluded } = plausiblePoints([point("2026-11-01", 1830, 1037, 1990), point("2026-11-02", 1830, 1500, 3000), point("2026-11-03", 1853, 1540, 2549)]);
    expect(excluded).toBe(2);
    expect(points.map(row => [row.minimum_price, row.maximum_price])).toEqual([[null, 1990], [1500, null], [1540, 2549]]);
    expect(trendSummary([point("2026-11-01", 1830, 184, 1990), point("2026-11-02", 1830, 1700, 1990)])?.lowest?.price).toBe(1700);
  });
  it("요청한 지역이 응답에 없으면 그 이름을 돌려준다", () => {
    expect(missingRegionName({ area: "sigungu", region: '["서울특별시","마포구"]' }, '["서울특별시","강남구"]')).toBe("마포구");
    expect(missingRegionName({ area: "sido", region: '["세종특별자치시"]' }, '["서울특별시"]')).toBe("세종특별자치시");
    expect(missingRegionName({ area: "highway", region: '["0140"]' }, "all")).toBe("선택한 노선");
    expect(missingRegionName({ area: "sigungu", region: "" }, '["서울특별시","강남구"]')).toBeNull();
    expect(missingRegionName({ area: "sido", region: '["서울특별시"]' }, '["서울특별시"]')).toBeNull();
  });
  it("현재 값은 30일 이력 없이 읽고, 노선 미제공 묶음은 풀어 쓴 이름으로 맨 뒤에 둔다", () => {
    expect(statisticsPath("sigungu", "B027")).toBe("fuel/statistics?scope=sigungu&product_code=B027&include_history=false");
    expect(regionOptions([metric('["7001"]', "노선 미제공"), metric('["0010"]', "경부선")]).map(row => row.label)).toEqual(["경부선", "노선 정보가 없는 휴게소"]);
  });
});

describe("보조", () => {
  it("한국 안 좌표만 공개 지도 링크로 만든다", () => {
    expect(publicMapHref({ name: "a", longitude: 127.1, latitude: 37.5 })).toBe("/?longitude=127.1&latitude=37.5");
    expect(publicMapHref({ name: "a", longitude: 0, latitude: 0 })).toBeNull();
    expect(publicMapHref({ name: "a" })).toBeNull();
  });
  it("통계 나이를 시간으로 잰다", () => {
    expect(statisticsAgeHours("2026-11-27T00:00:00Z", Date.parse("2026-11-28T12:00:00Z"))).toBe(36);
    expect(statisticsAgeHours(null)).toBeNull();
  });
});
