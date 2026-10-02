export type ParkingLot = {
  id: number;
  source_lot_id: string;
  legacy_source_lot_id: string | null;
  name: string;
  terminal: string | null;
  category: string | null;
  is_active: boolean;
};

export type Airport = {
  code: string;
  name_ko: string;
  name_en: string | null;
  source: string;
  parking_lots: ParkingLot[];
};

export type ParkingStatus = {
  airport_code: string;
  airport_name: string;
  parking_lot_id: number;
  parking_lot_name: string;
  terminal: string | null;
  category: string | null;
  observed_at: string;
  collected_at: string;
  occupied_spaces: number;
  total_spaces: number;
  available_spaces: number;
  congestion_label: string | null;
  congestion_ratio: number | null;
  status_level: "full" | "critical" | "warning" | "busy" | "stable";
};

export type ParkingCurrentResponse = {
  generated_at: string;
  items: ParkingStatus[];
};

export type CollectionSummary = {
  collection_run_id: number;
  status: string;
  client_mode: string;
  raw_response_count: number;
  snapshot_count: number;
  fee_rule_count: number;
  errors: string[];
};

export type CollectionRunStatus = {
  id: number;
  started_at: string;
  finished_at: string | null;
  status: string;
  trigger: string;
  error_message: string | null;
  raw_response_count: number;
  snapshot_count: number;
};

export type CollectorStatusResponse = {
  scheduler_enabled: boolean;
  collect_interval_seconds: number;
  effective_collect_interval_seconds: number;
  scheduler_safety_buffer_seconds: number;
  manual_collect_enabled: boolean;
  manual_collect_min_interval_seconds: number;
  client_mode: string;
  enabled_sources: string[];
  data_go_kr_service_key_configured: boolean;
  supported_airport_codes: string[];
  latest_snapshot_observed_at: string | null;
  latest_snapshot_collected_at: string | null;
  earliest_snapshot_observed_at: string | null;
  manual_collect_available_at: string | null;
  manual_collect_blocked: boolean;
   upstream_rate_limited: boolean;
   upstream_rate_limited_until: string | null;
  last_run: CollectionRunStatus | null;
  recent_runs: CollectionRunStatus[];
};

export type TimeSeriesPoint = {
  bucket_at: string;
  available_spaces: number;
  occupied_spaces: number;
  total_spaces: number;
  lot_observations: number;
};

export type ParkingTimeSeriesResponse = {
  generated_at: string;
  airport_code: string | null;
  parking_lot_id: number | null;
  days: number;
  interval_minutes: number;
  future_hours?: number;
  start_date?: string | null;
  end_date?: string | null;
  items: TimeSeriesPoint[];
};

export type FlightStatusItem = {
  airport_code: string;
  direction: "departure" | "arrival" | "unknown";
  flight_number: string;
  codeshare_flight_numbers?: string[];
  airline: string | null;
  scheduled_at: string;
  estimated_at: string | null;
  marker_at: string;
  origin_airport: string;
  destination_airport: string;
  status: string | null;
  line_type: string | null;
};

export type FlightStatusResponse = {
  generated_at: string;
  airport_code: string;
  local_date: string;
  source: string;
  status: string;
  error_message: string | null;
  items: FlightStatusItem[];
};

export type HourlyBucket = {
  hour: number;
  average_available_spaces: number;
  min_available_spaces: number;
  max_available_spaces: number;
  observations: number;
};

export type WeekdayBucket = {
  weekday: number;
  weekday_name: string;
  average_available_spaces: number;
  min_available_spaces: number;
  max_available_spaces: number;
  observations: number;
};

export type WeekdayHourBucket = {
  hour: number;
  average_available_spaces: number | null;
  min_available_spaces: number | null;
  max_available_spaces: number | null;
  observations: number;
};

export type WeekdayHourlyPattern = {
  weekday: number;
  weekday_name: string;
  average_available_spaces: number | null;
  min_available_spaces: number | null;
  max_available_spaces: number | null;
  observations: number;
  hourly_buckets: WeekdayHourBucket[];
};

export type HolidayItemSummary = {
  local_date: string;
  name: string;
  weekday: number;
  weekday_name: string;
};

export type HolidaySummaryResponse = {
  generated_at: string;
  start_date: string;
  end_date: string;
  source: string;
  status: string;
  error_message: string | null;
  sentence: string;
  items: HolidayItemSummary[];
};

export type HolidayPatternItem = {
  local_date: string;
  name: string;
  day_type: "holiday" | "saturday" | "sunday";
  weekday: number;
  weekday_name: string;
  average_available_spaces: number | null;
  min_available_spaces: number | null;
  max_available_spaces: number | null;
  observations: number;
  hourly_buckets: WeekdayHourBucket[];
};

export type HolidayPatternResponse = {
  generated_at: string;
  airport_code: string | null;
  parking_lot_id: number | null;
  source: string;
  status: string;
  error_message: string | null;
  items: HolidayPatternItem[];
};

export type ThresholdEvent = {
  parking_lot_id: number;
  parking_lot_name: string;
  airport_code: string;
  airport_name: string;
  threshold: number;
  direction: "down" | "up";
  crossed_at: string;
  previous_available_spaces: number;
  current_available_spaces: number;
};

export type ThresholdWeekdayTime = {
  threshold: number;
  weekday: number;
  weekday_name: string;
  typical_minutes_of_day: number | null;
  sample_count: number;
};

export type ThresholdDateHistoryItem = {
  threshold: number;
  local_date: string;
  weekday: number;
  weekday_name: string;
  crossed_at: string;
  minutes_of_day: number;
  available_spaces: number;
};

export type ThresholdInsightsResponse = {
  generated_at: string;
  airport_code: string | null;
  parking_lot_id: number | null;
  days: number;
  interval_minutes: number;
  weekday_items: ThresholdWeekdayTime[];
  history_items: ThresholdDateHistoryItem[];
};

export type FeeCalculationRequest = {
  airport_code: string;
  parking_lot_id?: number | null;
  vehicle_size: "small" | "large";
  entry_at: string;
  exit_at: string;
};

export type FeeBreakdown = {
  date: string;
  day_type: string;
  duration_minutes: number;
  applied_fee: number;
};

export type FeeCalculationResponse = {
  supported: boolean;
  airport_code: string;
  vehicle_size: string;
  total_fee: number | null;
  currency: string;
  message: string | null;
  breakdown: FeeBreakdown[];
};

export type DashboardBootstrapResponse = {
  airports: Airport[];
  current: ParkingCurrentResponse;
  collector: CollectorStatusResponse;
  holidays: HolidaySummaryResponse;
};

export type DashboardAnalyticsResponse = {
  threshold_events: ThresholdEvent[];
  threshold_insights: ThresholdInsightsResponse;
  weekday_hour_patterns: WeekdayHourlyPattern[];
  holiday_patterns: HolidayPatternResponse;
  time_series: ParkingTimeSeriesResponse;
};
