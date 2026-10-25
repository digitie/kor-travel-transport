import type {
  Airport,
  CollectorStatusResponse,
  DashboardAnalyticsResponse,
  DashboardBootstrapResponse,
  FeeCalculationRequest,
  FeeCalculationResponse,
  FlightStatusResponse,
  HolidayPatternResponse,
  HolidaySummaryResponse,
  HourlyBucket,
  ParkingCurrentResponse,
  ParkingTimeSeriesResponse,
  ThresholdEvent,
  ThresholdInsightsResponse,
  WeekdayBucket,
  WeekdayHourlyPattern,
} from "./types";

const DEFAULT_API_BASE_PATH = "/api/backend";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function resolveDefaultApiBaseUrl(): string {
  const configured = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
  if (configured) {
    return configured;
  }

  return DEFAULT_API_BASE_PATH;
}

function buildAnalyticsUrl(
  baseUrl: string,
  path: string,
  airportCode: string,
  options: {
    parkingLotId?: number | null;
    days?: number;
    intervalMinutes?: number;
    futureHours?: number;
    startDate?: string;
    endDate?: string;
  } = {}
): string {
  const params = new URLSearchParams({ airport_code: airportCode });
  if (options.parkingLotId != null) {
    params.set("parking_lot_id", String(options.parkingLotId));
  }
  if (options.startDate && options.endDate) {
    params.set("start_date", options.startDate);
    params.set("end_date", options.endDate);
  } else if (options.days != null) {
    params.set("days", String(options.days));
  }
  if (options.intervalMinutes != null) {
    params.set("interval_minutes", String(options.intervalMinutes));
  }
  if (options.futureHours != null) {
    params.set("future_hours", String(options.futureHours));
  }
  return `${baseUrl}${path}?${params.toString()}`;
}

async function readErrorMessage(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: string };
    if (payload.detail) {
      return payload.detail;
    }
  } catch {
    // Ignore JSON parse failures and fall back to a generic message.
  }
  return `API request failed: ${response.status}`;
}

async function getJson<T>(url: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  const isMultipart = typeof FormData !== "undefined" && init?.body instanceof FormData;
  if (!isMultipart && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(url, {
    ...init,
    headers,
    cache: "no-store",
  });

  if (!response.ok) {
    throw new ApiError(await readErrorMessage(response), response.status);
  }

  return response.json() as Promise<T>;
}

export function buildApiClient(apiBaseUrl?: string, versionPrefix: "/v1" | "" = "/v1") {
  const baseUrl = `${(apiBaseUrl ?? resolveDefaultApiBaseUrl()).replace(/\/$/, "")}${versionPrefix}`;

  return {
    getAirports(): Promise<Airport[]> {
      return getJson<Airport[]>(`${baseUrl}/airports`);
    },
    getDashboardBootstrap(airportCode?: string): Promise<DashboardBootstrapResponse> {
      const params = airportCode ? `?airport_code=${encodeURIComponent(airportCode)}` : "";
      return getJson<DashboardBootstrapResponse>(`${baseUrl}/dashboard/bootstrap${params}`);
    },
    getCurrent(airportCode: string): Promise<ParkingCurrentResponse> {
      return getJson<ParkingCurrentResponse>(`${baseUrl}/parking/current?airport_code=${airportCode}`);
    },
    getCollectorStatus(): Promise<CollectorStatusResponse> {
      return getJson<CollectorStatusResponse>(`${baseUrl}/admin/collector-status`);
    },
    getDashboardAnalytics(
      airportCode: string,
      parkingLotId: number | null = null
    ): Promise<DashboardAnalyticsResponse> {
      return getJson<DashboardAnalyticsResponse>(
        buildAnalyticsUrl(baseUrl, "/dashboard/analytics", airportCode, { parkingLotId })
      );
    },
    getFlightStatus(airportCode: string): Promise<FlightStatusResponse> {
      const params = new URLSearchParams({ airport_code: airportCode });
      return getJson<FlightStatusResponse>(`${baseUrl}/flights/status?${params.toString()}`);
    },
    getHolidaySummary(): Promise<HolidaySummaryResponse> {
      return getJson<HolidaySummaryResponse>(`${baseUrl}/holidays/summary`);
    },
    getByHour(airportCode: string, parkingLotId: number | null = null): Promise<HourlyBucket[]> {
      return getJson<HourlyBucket[]>(buildAnalyticsUrl(baseUrl, "/parking/analytics/by-hour", airportCode, { parkingLotId }));
    },
    getByWeekday(airportCode: string, parkingLotId: number | null = null): Promise<WeekdayBucket[]> {
      return getJson<WeekdayBucket[]>(
        buildAnalyticsUrl(baseUrl, "/parking/analytics/by-weekday", airportCode, { parkingLotId })
      );
    },
    getByWeekdayHour(airportCode: string, parkingLotId: number | null = null): Promise<WeekdayHourlyPattern[]> {
      return getJson<WeekdayHourlyPattern[]>(
        buildAnalyticsUrl(baseUrl, "/parking/analytics/by-weekday-hour", airportCode, { parkingLotId })
      );
    },
    getTimeSeries(
      airportCode: string,
      options: {
        parkingLotId?: number | null;
        days?: number;
        intervalMinutes?: number;
        futureHours?: number;
        startDate?: string;
        endDate?: string;
      } = {}
    ): Promise<ParkingTimeSeriesResponse> {
      const { parkingLotId = null, days = 7, intervalMinutes = 10, futureHours = 0, startDate, endDate } = options;
      return getJson<ParkingTimeSeriesResponse>(
        buildAnalyticsUrl(baseUrl, "/parking/analytics/timeseries", airportCode, {
          parkingLotId,
          days,
          intervalMinutes,
          futureHours,
          startDate,
          endDate,
        })
      );
    },
    getHolidayPatterns(
      airportCode: string,
      options: { parkingLotId?: number | null; limit?: number } = {}
    ): Promise<HolidayPatternResponse> {
      const params = new URLSearchParams({ airport_code: airportCode });
      if (options.parkingLotId != null) {
        params.set("parking_lot_id", String(options.parkingLotId));
      }
      if (options.limit != null) {
        params.set("limit", String(options.limit));
      }
      return getJson<HolidayPatternResponse>(`${baseUrl}/parking/analytics/holiday-patterns?${params.toString()}`);
    },
    getThresholdEvents(airportCode: string, parkingLotId: number | null = null): Promise<ThresholdEvent[]> {
      return getJson<ThresholdEvent[]>(
        buildAnalyticsUrl(baseUrl, "/parking/analytics/threshold-events", airportCode, { parkingLotId })
      );
    },
    getThresholdInsights(
      airportCode: string,
      options: { parkingLotId?: number | null; days?: number; intervalMinutes?: number } = {}
    ): Promise<ThresholdInsightsResponse> {
      const { parkingLotId = null, days = 21, intervalMinutes = 10 } = options;
      return getJson<ThresholdInsightsResponse>(
        buildAnalyticsUrl(baseUrl, "/parking/analytics/threshold-insights", airportCode, {
          parkingLotId,
          days,
          intervalMinutes,
        })
      );
    },
    async calculateFee(payload: FeeCalculationRequest): Promise<FeeCalculationResponse> {
      return getJson<FeeCalculationResponse>(`${baseUrl}/fees/calculate`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
    },
  };
}
