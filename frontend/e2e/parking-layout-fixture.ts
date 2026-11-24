import type { Page } from "@playwright/test";

// 운영 API 없이 공개 parking-radar 화면 배치를 검증하는 고정 응답이다.
// 주차장 이름·면수는 backend/app/services/sample_data.py의 표본을 따른다(긴 이름·P1/P2 묶음 포함).
type LotSeed = { id: number; name: string; terminal: string; total: number; available: number };
type AirportSeed = { code: string; name: string; lots: LotSeed[] };

export const PARKING_FIXTURE_AIRPORTS: AirportSeed[] = [
  { code: "GMP", name: "김포국제공항", lots: [
    { id: 1, name: "국내선 제1주차장", terminal: "국내선", total: 510, available: 42 },
    { id: 2, name: "국내선 제2주차장", terminal: "국내선", total: 640, available: 188 },
    { id: 3, name: "국제선 지하주차장", terminal: "국제선", total: 300, available: 120 },
    { id: 4, name: "국제선 주차빌딩", terminal: "국제선", total: 720, available: 655 },
  ] },
  { code: "PUS", name: "김해국제공항", lots: [
    { id: 11, name: "P1 여객주차장", terminal: "여객", total: 1540, available: 310 },
    { id: 12, name: "P2 여객주차장", terminal: "여객", total: 2453, available: 1210 },
    { id: 13, name: "P3 여객(화물)주차장", terminal: "여객/화물", total: 878, available: 77 },
  ] },
  { code: "ICN", name: "인천국제공항", lots: [
    { id: 21, name: "T1 단기주차장", terminal: "T1", total: 640, available: 35 },
    { id: 22, name: "T1 장기주차장 P1", terminal: "T1", total: 1280, available: 402 },
    { id: 23, name: "T1 장기주차장 P2", terminal: "T1", total: 1420, available: 880 },
    { id: 24, name: "T1 장기주차장 P3", terminal: "T1", total: 1290, available: 1001 },
    { id: 25, name: "T2 예약주차장", terminal: "T2", total: 320, available: 12 },
  ] },
];

function statusLevel(available: number, total: number) {
  const ratio = available / total;
  return ratio < 0.1 ? "critical" : ratio < 0.25 ? "warning" : ratio < 0.5 ? "busy" : "stable";
}

export type ParkingFixtureOptions = {
  /** `/dashboard/analytics`의 기간 분석 기준 시각. 주지 않으면 관측 시각과 같다. */
  analyticsGeneratedAt?: string | null;
};

export async function installParkingFixture(page: Page, options: ParkingFixtureOptions = {}) {
  const observedAt = new Date(Date.now() - 2 * 60_000).toISOString();
  const analyticsGeneratedAt = options.analyticsGeneratedAt === undefined ? observedAt : options.analyticsGeneratedAt;
  const airports = PARKING_FIXTURE_AIRPORTS.map((airport) => ({
    code: airport.code, name_ko: airport.name, name_en: airport.code, source: "kac",
    parking_lots: airport.lots.map((lot) => ({ id: lot.id, source_lot_id: `${airport.code}-${lot.id}`, legacy_source_lot_id: null, name: lot.name, terminal: lot.terminal, category: "short", is_active: true })),
  }));
  const items = PARKING_FIXTURE_AIRPORTS.flatMap((airport) => airport.lots.map((lot) => ({
    airport_code: airport.code, airport_name: airport.name, parking_lot_id: lot.id, parking_lot_name: lot.name, terminal: lot.terminal, category: "short",
    observed_at: observedAt, collected_at: observedAt, occupied_spaces: lot.total - lot.available, total_spaces: lot.total, available_spaces: lot.available,
    congestion_label: null, congestion_ratio: Math.round(((lot.total - lot.available) / lot.total) * 100), status_level: statusLevel(lot.available, lot.total),
  })));
  const collector = { scheduler_enabled: true, collect_interval_seconds: 300, manual_collect_enabled: false, manual_collect_min_interval_seconds: 300, client_mode: "live", enabled_sources: ["kac_parking"], data_go_kr_service_key_configured: true, supported_airport_codes: airports.map((airport) => airport.code), latest_snapshot_observed_at: observedAt, latest_snapshot_collected_at: observedAt, earliest_snapshot_observed_at: "2026-10-01T00:00:00Z", manual_collect_available_at: null, manual_collect_blocked: false, upstream_rate_limited: false, upstream_rate_limited_until: null, last_run: null, recent_runs: [], effective_collect_interval_seconds: 300, scheduler_safety_buffer_seconds: 0 };
  const holidays = { generated_at: observedAt, start_date: "2026-10-01", end_date: "2026-12-31", source: "fixture", status: "success", error_message: null, sentence: "다음 공휴일은 12/25 (금) 성탄절입니다.", items: [{ local_date: "2026-12-25", name: "성탄절", weekday: 4, weekday_name: "금" }] };
  const series = (airport: string, lot: number | null) => ({ generated_at: observedAt, airport_code: airport, parking_lot_id: lot, days: 7, interval_minutes: 60, future_hours: 0, items: Array.from({ length: 7 * 24 }, (_, index) => ({ bucket_at: new Date(Date.parse(observedAt) - (7 * 24 - index) * 3_600_000).toISOString(), available_spaces: 120 + Math.round(90 * Math.sin(index / 4)), occupied_spaces: 300, total_spaces: 510, lot_observations: 1 })) });
  const hourly = Array.from({ length: 24 }, (_, hour) => ({ hour, average_available_spaces: 80 + hour * 6, min_available_spaces: 40 + hour * 5, max_available_spaces: 120 + hour * 6, average_occupied_spaces: 300, average_congestion_ratio: 50, observations: 5 }));
  const analytics = (airport: string, lot: number | null) => ({
    threshold_events: [{ parking_lot_id: 1, parking_lot_name: "국내선 제1주차장", threshold: 50, crossed_at: observedAt, direction: "down", previous_available_spaces: 55, current_available_spaces: 45 }],
    threshold_insights: { generated_at: observedAt, airport_code: airport, parking_lot_id: lot, days: 21, interval_minutes: 10, weekday_items: [{ weekday: 0, weekday_name: "월", threshold: 50, typical_minutes_of_day: 600, sample_count: 2 }], history_items: [{ threshold: 50, local_date: "2026-11-20", weekday: 4, weekday_name: "금", crossed_at: observedAt, minutes_of_day: 600, available_spaces: 45 }] },
    weekday_hour_patterns: ["월", "화", "수", "목", "금", "토", "일"].map((weekday_name, weekday) => ({ weekday, weekday_name, hourly_buckets: hourly })),
    holiday_patterns: { generated_at: observedAt, airport_code: airport, parking_lot_id: lot, source: "fixture", status: "success", error_message: null, items: [{ local_date: "2026-10-09", name: "한글날", weekday: 4, weekday_name: "금", hourly_buckets: hourly }] },
    time_series: series(airport, lot),
    analytics_generated_at: analyticsGeneratedAt,
    analytics_age_seconds: analyticsGeneratedAt ? Math.max(0, Math.floor((Date.now() - Date.parse(analyticsGeneratedAt)) / 1000)) : null,
  });
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace(/^\/api\/(?:transport\/|backend\/v1\/|backend\/)/, "");
    const airport = url.searchParams.get("airport_code") ?? "GMP";
    const lot = Number(url.searchParams.get("parking_lot_id")) || null;
    if (path === "dashboard/bootstrap") return route.fulfill({ json: { airports, current: { generated_at: observedAt, items }, collector, holidays } });
    if (path === "admin/collector-status") return route.fulfill({ json: collector });
    if (path === "parking/current") return route.fulfill({ json: { generated_at: observedAt, items: items.filter((item) => item.airport_code === airport) } });
    if (path === "parking/outlook") return route.fulfill({ json: { generated_at: observedAt, weekday: 0, hour: 10, items: [] } });
    if (path === "dashboard/analytics") return route.fulfill({ json: analytics(airport, lot) });
    if (path === "parking/analytics/timeseries") return route.fulfill({ json: series(airport, lot) });
    if (path === "flights/status") return route.fulfill({ json: { generated_at: observedAt, airport_code: airport, local_date: observedAt.slice(0, 10), source: "fixture", status: "success", error_message: null, items: [] } });
    if (path === "fees/calculate") return route.fulfill({ json: { supported: true, airport_code: airport, vehicle_size: "small", total_fee: 12000, currency: "KRW", message: null, breakdown: [{ date: "2026-11-23", day_type: "weekday", duration_minutes: 360, applied_fee: 12000 }] } });
    if (path === "health") return route.fulfill({ json: { status: "ok" } });
    return route.fulfill({ status: 404, json: { detail: `fixture 미정의 경로: ${path}` } });
  });
}
