/** 단위 테스트 공용 표본(옥천군 29곳 휘발유). 앱 코드에서 import하지 않는다. */
export const sampleDistribution = {
  product_code: "B027", generated_at: "2026-11-21T22:00:00Z", update_pending: false, minimum_sample: 3,
  sido_value: "15", sigungu_value: "1501", sido_name: "충북", sigungu_name: "옥천군",
  grade_rule: [{ grade: "A+", label: "제일싸요", percentile_below: 10 }, { grade: "D", label: "제일 비싸요", percentile_below: null }],
  sigungu: {
    scope: "sigungu", label: "옥천군", station_count: 29, minimum_price: 1819, average_price: 1883, maximum_price: 1998,
    sufficient: true, bin_width: 20,
    histogram: [{ start: 1800, end: 1820, count: 1 }, { start: 1820, end: 1840, count: 4 }, { start: 1840, end: 1860, count: 14 },
      { start: 1860, end: 1880, count: 0 }, { start: 1880, end: 1900, count: 8 }, { start: 1980, end: 2000, count: 2 }],
    quantiles: Array.from({ length: 11 }, (_, index) => ({ percent: index * 10, price: 1819 + index * 17.9 })),
  },
  sido: { scope: "sido", label: "충북", station_count: 500, minimum_price: 1700, average_price: 1870, maximum_price: 2300 },
  nationwide: { scope: "nationwide", label: "전국", station_count: 11000, minimum_price: 1765, average_price: 1854, maximum_price: 2549 },
  station: null,
};
