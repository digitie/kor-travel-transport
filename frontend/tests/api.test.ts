import { buildApiClient } from "@/lib/api";

describe("api client", () => {
  test("requests the airports endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [{ code: "GMP", name_ko: "김포국제공항", name_en: "Gimpo", source: "kac", parking_lots: [] }],
    });

    vi.stubGlobal("fetch", fetchMock);
    const client = buildApiClient("http://localhost:8000");
    await client.getAirports();

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/v1/airports",
      expect.objectContaining({ cache: "no-store" })
    );
  });

  test("uses the consolidated bootstrap and analytics endpoints", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({}),
    });

    vi.stubGlobal("fetch", fetchMock);
    const client = buildApiClient("http://localhost:8000");
    await client.getDashboardBootstrap("GMP");
    await client.getDashboardAnalytics("GMP", 12);

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "http://localhost:8000/v1/dashboard/bootstrap?airport_code=GMP",
      expect.objectContaining({ cache: "no-store" })
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "http://localhost:8000/v1/dashboard/analytics?airport_code=GMP&parking_lot_id=12",
      expect.objectContaining({ cache: "no-store" })
    );
  });

  test("the public api client offers no backup operations (ADR-012)", () => {
    const client = buildApiClient("http://localhost:8000");
    expect(Object.keys(client).filter((name) => /backup|restore/i.test(name))).toEqual([]);
  });

  test("the public api client offers no manual collection (ADR-012)", () => {
    // 공개 프록시는 v1/admin/collect를 중계하지 않고 브라우저에는 관리자 토큰도 없다(#61).
    const client = buildApiClient("http://localhost:8000");
    expect(client).not.toHaveProperty("runCollector");
  });

  test("uses the same-origin backend proxy when the API base URL is not explicitly passed", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ generated_at: "2026-04-26T00:00:00.000Z", items: [] }),
    });

    vi.stubGlobal("fetch", fetchMock);

    const client = buildApiClient();
    await client.getCurrent("GMP");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/backend/v1/parking/current?airport_code=GMP",
      expect.objectContaining({ cache: "no-store" })
    );
  });

  test("requests lot-specific analytics endpoints when a parking lot is selected", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [],
    });

    vi.stubGlobal("fetch", fetchMock);
    const client = buildApiClient("http://localhost:8000");
    await client.getByHour("GMP", 12);
    await client.getByWeekday("GMP", 12);
    await client.getByWeekdayHour("GMP", 12);
    await client.getThresholdEvents("GMP", 12);
    await client.getThresholdInsights("GMP", { parkingLotId: 12, days: 21, intervalMinutes: 10 });
    await client.getTimeSeries("GMP", { parkingLotId: 12, days: 7 });
    await client.getHolidayPatterns("GMP", { parkingLotId: 12, limit: 8 });

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "http://localhost:8000/v1/parking/analytics/by-hour?airport_code=GMP&parking_lot_id=12",
      expect.objectContaining({ cache: "no-store" })
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "http://localhost:8000/v1/parking/analytics/by-weekday?airport_code=GMP&parking_lot_id=12",
      expect.objectContaining({ cache: "no-store" })
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "http://localhost:8000/v1/parking/analytics/by-weekday-hour?airport_code=GMP&parking_lot_id=12",
      expect.objectContaining({ cache: "no-store" })
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      "http://localhost:8000/v1/parking/analytics/threshold-events?airport_code=GMP&parking_lot_id=12",
      expect.objectContaining({ cache: "no-store" })
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      5,
      "http://localhost:8000/v1/parking/analytics/threshold-insights?airport_code=GMP&parking_lot_id=12&days=21&interval_minutes=10",
      expect.objectContaining({ cache: "no-store" })
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      6,
      "http://localhost:8000/v1/parking/analytics/timeseries?airport_code=GMP&parking_lot_id=12&days=7&interval_minutes=10&future_hours=0",
      expect.objectContaining({ cache: "no-store" })
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      7,
      "http://localhost:8000/v1/parking/analytics/holiday-patterns?airport_code=GMP&parking_lot_id=12&limit=8",
      expect.objectContaining({ cache: "no-store" })
    );
  });

  test("requests an explicit date range instead of days when both are given", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ items: [] }),
    });

    vi.stubGlobal("fetch", fetchMock);
    const client = buildApiClient("http://localhost:8000");
    await client.getTimeSeries("GMP", { parkingLotId: 12, startDate: "2026-05-01", endDate: "2026-05-07" });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/v1/parking/analytics/timeseries?airport_code=GMP&parking_lot_id=12&start_date=2026-05-01&end_date=2026-05-07&interval_minutes=10&future_hours=0",
      expect.objectContaining({ cache: "no-store" })
    );
  });

  test("requests the holiday summary endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        generated_at: "2026-05-09T00:00:00.000Z",
        start_date: "2026-04-27",
        end_date: "2026-05-17",
        source: "sample_holiday_info",
        status: "sample",
        error_message: null,
        sentence: "5/5 (화) 어린이날 입니다.",
        items: [],
      }),
    });

    vi.stubGlobal("fetch", fetchMock);
    const client = buildApiClient("http://localhost:8000");
    await client.getHolidaySummary();

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/v1/holidays/summary",
      expect.objectContaining({ cache: "no-store" })
    );
  });

  test("requests the flight status endpoint for chart markers", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        generated_at: "2026-04-26T00:00:00.000Z",
        airport_code: "GMP",
        local_date: "2026-04-26",
        source: "sample_flight_status",
        status: "sample",
        error_message: null,
        items: [],
      }),
    });

    vi.stubGlobal("fetch", fetchMock);
    const client = buildApiClient("http://localhost:8000");
    await client.getFlightStatus("GMP");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/v1/flights/status?airport_code=GMP",
      expect.objectContaining({ cache: "no-store" })
    );
  });

  test("requests the collector status endpoint", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          scheduler_enabled: true,
          collect_interval_seconds: 300,
          effective_collect_interval_seconds: 180,
          scheduler_safety_buffer_seconds: 120,
          manual_collect_enabled: true,
          manual_collect_min_interval_seconds: 300,
          client_mode: "live",
          enabled_sources: ["kac_parking"],
          data_go_kr_service_key_configured: true,
          supported_airport_codes: ["GMP", "PUS", "CJU"],
          latest_snapshot_observed_at: "2026-04-25T00:20:00.000Z",
          latest_snapshot_collected_at: "2026-04-25T00:30:00.000Z",
          manual_collect_available_at: "2026-04-25T00:35:00.000Z",
          manual_collect_blocked: false,
          last_run: null,
          recent_runs: [],
        }),
      });

    vi.stubGlobal("fetch", fetchMock);
    const client = buildApiClient("http://localhost:8000");

    await client.getCollectorStatus();

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "http://localhost:8000/v1/admin/collector-status",
      expect.objectContaining({ cache: "no-store" })
    );
  });
});
