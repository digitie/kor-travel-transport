import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";
import { FuelStatisticsCard, FuelViewportSummary, type FuelViewportStatistics } from "./fuel-statistics";

const metrics: FuelViewportStatistics = { product_code: "B027", station_count: 1000, average_price: 1700,
  minimum_price: 1600, maximum_price: 1800, price_spread: 200, standard_deviation: 50,
  saving_50l: 5000, cheapest_station_count: 2, generated_at: "2026-10-21T01:00:00Z",
  cheapest_station: { name: "최저가 주유소", address: "서울" } };

test("평균·최저·편차·절감액과 동률 주유소를 표시한다", () => {
  const html = renderToStaticMarkup(<FuelStatisticsCard title="휘발유" metrics={metrics} />);
  for (const value of ["1,700", "1,600", "5,000", "최저가 주유소", "외 1곳", "가격 표준편차"]) expect(html).toContain(value);
});

test("지도 재조회 중 이전 범위의 통계를 표시하지 않는다", () => {
  const html = renderToStaticMarkup(<FuelViewportSummary items={[metrics]} pending />);
  expect(html).toContain("통계 조회 중");
  expect(html).not.toContain("최저가 주유소");
  expect(html).toContain('aria-busy="true"');
});

test("지도 범위 통계는 마커 개수 대신 API의 전체 주유소 개수를 쓴다", () => {
  const html = renderToStaticMarkup(<FuelViewportSummary items={[metrics]} pending={false} />);
  expect(html).toContain("1,000개 주유소");
  expect(html).toContain("휘발유");
});
