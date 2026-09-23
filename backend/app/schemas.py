from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ParkingLotSummary(BaseModel):
    id: int
    source_lot_id: str
    legacy_source_lot_id: str | None = None
    name: str
    terminal: str | None = None
    category: str | None = None
    is_active: bool


class AirportSummary(BaseModel):
    code: str
    name_ko: str
    name_en: str | None = None
    source: str
    parking_lots: list[ParkingLotSummary]


class ParkingStatus(BaseModel):
    airport_code: str
    airport_name: str
    parking_lot_id: int
    parking_lot_name: str
    terminal: str | None = None
    category: str | None = None
    observed_at: datetime
    collected_at: datetime
    occupied_spaces: int
    total_spaces: int
    available_spaces: int
    congestion_label: str | None = None
    congestion_ratio: float | None = None
    status_level: str


class ParkingCurrentResponse(BaseModel):
    generated_at: datetime
    items: list[ParkingStatus]


class HistoryPoint(BaseModel):
    observed_at: datetime
    occupied_spaces: int
    total_spaces: int
    available_spaces: int


class ParkingHistoryResponse(BaseModel):
    items: list[HistoryPoint]


class HighwayTrafficItem(BaseModel):
    source: str
    identity_key: str
    observed_at: datetime
    collected_at: datetime
    route_no: str | None = None
    route_name: str | None = None
    conzone_id: str | None = None
    conzone_name: str | None = None
    direction: str | None = None
    speed: float | None = None
    free_flow_speed: float | None = None
    congestion_level: str | None = None


class HighwayTrafficResponse(BaseModel):
    generated_at: datetime
    days: int
    route_no: str | None = None
    items: list[HighwayTrafficItem]


class HighwayIncidentItem(BaseModel):
    source: str
    identity_key: str
    observed_at: datetime
    collected_at: datetime
    occurred_date: str | None = None
    occurred_time: str | None = None
    incident_type: str | None = None
    incident_type_code: str | None = None
    direction: str | None = None
    message: str | None = None
    point_name: str | None = None
    route_no: str | None = None
    route_name: str | None = None
    process_status: str | None = None
    process_status_code: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    congestion_length: float | None = None
    series_no: int | None = None


class HighwayIncidentResponse(BaseModel):
    generated_at: datetime
    days: int
    route_no: str | None = None
    items: list[HighwayIncidentItem]


class FuelPriceItem(BaseModel):
    product_code: str
    price: float | None = None
    provider_updated_at: datetime | None = None
    observed_at: datetime
    collected_at: datetime


class FuelStationItem(BaseModel):
    """유가 기준정보. 지역 필드는 검색 문맥이며 실제 위치는 주소·좌표를 확인한다."""

    source: str
    identity_key: str
    source_station_id: str | None = None
    name: str
    brand_code: str | None = None
    brand_name: str | None = None
    phone: str | None = None
    address: str | None = None
    business_number: str | None = None
    cb_code: str | None = None
    station_type: str | None = None
    query_level: str
    sido_value: str
    sido_name: str
    sigungu_value: str
    sigungu_name: str
    dong_value: str | None = None
    dong_name: str | None = None
    katec_x: float | None = None
    katec_y: float | None = None
    longitude: float | None = None
    latitude: float | None = None
    source_kinds: list[str]
    is_illegal: bool | None = None
    is_self: bool | None = None
    is_24h: bool | None = None
    is_kpetro: bool | None = None
    is_electronic: bool | None = None
    is_good: bool | None = None
    is_good_strong: bool | None = None
    is_region_franchise: bool | None = None
    has_carwash: bool | None = None
    has_maintenance: bool | None = None
    has_cvs: bool | None = None
    cs_yn: bool | None = None
    discount_info: str | None = None
    save_event_info: str | None = None
    representative_event_info: str | None = None
    on_event_info: str | None = None
    other_business_info: str | None = None
    first_seen_at: datetime
    last_seen_at: datetime
    prices: list[FuelPriceItem]


class FuelStationResponse(BaseModel):
    generated_at: datetime
    days: int
    sido_value: str | None = None
    sigungu_value: str | None = None
    product_code: str | None = None
    items: list[FuelStationItem]


class TransportPlaceMapItem(BaseModel):
    """kor-travel-map·PinVi가 지도 marker로 바로 소비할 저장 장소 요약."""

    id: int
    kind: Literal["airport", "fuel_station", "rail_station", "ferry_port", "rest_area"]
    source: str
    provider_id: str | None = None
    name: str
    longitude: float
    latitude: float
    subtitle: str | None = None
    brand_name: str | None = None
    latest_price: float | None = None
    price_product_code: str | None = None
    line_names: list[str] = Field(default_factory=list)
    address: str | None = None
    updated_at: datetime
    location_source: str | None = None
    location_point_count: int | None = None
    parking_lot_count: int | None = None
    parking_available_spaces: int | None = None
    parking_total_spaces: int | None = None
    parking_observed_at: datetime | None = None


class TransportPlaceMapResponse(BaseModel):
    generated_at: datetime
    kind: str | None = None
    total: int = 0
    truncated: bool = False
    items: list[TransportPlaceMapItem]


class FerryOperationItem(BaseModel):
    vessel_name: str | None = None
    departure_port_name: str | None = None
    arrival_port_name: str | None = None
    departure_planned_time: str | None = None
    arrival_planned_time: str | None = None
    fare: str | None = None


class FerryOperationResponse(BaseModel):
    port_id: str
    service_date: date
    fetched_at: datetime
    items: list[FerryOperationItem]


class TransportCollectionRunStatus(BaseModel):
    id: int
    started_at: datetime
    finished_at: datetime | None = None
    status: str
    trigger: str
    error: str | None = None


class TransportCollectorStatus(BaseModel):
    scheduler_enabled: bool
    collection_enabled: bool
    collect_interval_seconds: int
    client_mode: str
    enabled_sources: list[str]
    last_fuel_success_at: datetime | None = None
    next_fuel_due_at: datetime | None = None
    last_fuel_error: str | None = None
    last_run: TransportCollectionRunStatus | None = None
    sources: list["TransportSourceStatus"] = Field(default_factory=list)


class TransportSourceStatus(BaseModel):
    source: str
    last_started_at: datetime | None = None
    last_success_at: datetime | None = None
    next_due_at: datetime | None = None
    last_error: str | None = None


class HighwayTrafficStatistics(BaseModel):
    route_no: str | None = None
    direction: str | None = None
    observations: int
    average_speed: float | None = None
    minimum_speed: float | None = None
    maximum_speed: float | None = None
    average_free_flow_speed: float | None = None
    latest_observed_at: datetime | None = None


class HighwayIncidentStatistics(BaseModel):
    route_no: str | None = None
    incidents: int
    latest_observed_at: datetime | None = None


class FuelPriceStatistics(BaseModel):
    product_code: str
    stations: int
    observations: int
    average_price: float | None = None
    minimum_price: float | None = None
    maximum_price: float | None = None
    latest_observed_at: datetime | None = None
    latest_collected_at: datetime | None = None


class TransportStatisticsResponse(BaseModel):
    generated_at: datetime
    days: int
    route_no: str | None = None
    traffic: list[HighwayTrafficStatistics]
    incidents: list[HighwayIncidentStatistics]
    fuel_prices: list[FuelPriceStatistics]


class TransportCollectionSummary(BaseModel):
    collection_run_id: int
    status: str
    client_mode: str
    raw_response_count: int
    traffic_snapshot_count: int
    incident_snapshot_count: int
    fuel_station_count: int
    fuel_price_count: int
    errors: list[str]


class TimeSeriesPoint(BaseModel):
    bucket_at: datetime
    available_spaces: int
    occupied_spaces: int
    total_spaces: int
    lot_observations: int


class ParkingTimeSeriesResponse(BaseModel):
    generated_at: datetime
    airport_code: str | None = None
    parking_lot_id: int | None = None
    days: int
    interval_minutes: int
    future_hours: int = 0
    start_date: str | None = None
    end_date: str | None = None
    items: list[TimeSeriesPoint]


class FlightStatusItem(BaseModel):
    airport_code: str
    direction: str
    flight_number: str
    codeshare_flight_numbers: list[str] = Field(default_factory=list)
    airline: str | None = None
    scheduled_at: datetime
    estimated_at: datetime | None = None
    marker_at: datetime
    origin_airport: str
    destination_airport: str
    status: str | None = None
    line_type: str | None = None


class FlightStatusResponse(BaseModel):
    generated_at: datetime
    airport_code: str
    local_date: str
    source: str
    status: str
    error_message: str | None = None
    items: list[FlightStatusItem]


class HourlyBucket(BaseModel):
    hour: int
    average_available_spaces: float
    min_available_spaces: int
    max_available_spaces: int
    observations: int


class WeekdayBucket(BaseModel):
    weekday: int
    weekday_name: str
    average_available_spaces: float
    min_available_spaces: int
    max_available_spaces: int
    observations: int


class WeekdayHourBucket(BaseModel):
    hour: int
    average_available_spaces: float | None = None
    min_available_spaces: int | None = None
    max_available_spaces: int | None = None
    observations: int


class WeekdayHourlyPattern(BaseModel):
    weekday: int
    weekday_name: str
    average_available_spaces: float | None = None
    min_available_spaces: int | None = None
    max_available_spaces: int | None = None
    observations: int
    hourly_buckets: list[WeekdayHourBucket]


class HolidayItemSummary(BaseModel):
    local_date: str
    name: str
    weekday: int
    weekday_name: str


class HolidaySummaryResponse(BaseModel):
    generated_at: datetime
    start_date: str
    end_date: str
    source: str
    status: str
    error_message: str | None = None
    sentence: str
    items: list[HolidayItemSummary]


class HolidayPatternItem(BaseModel):
    local_date: str
    name: str
    day_type: Literal["holiday", "saturday", "sunday"] = "holiday"
    weekday: int
    weekday_name: str
    average_available_spaces: float | None = None
    min_available_spaces: int | None = None
    max_available_spaces: int | None = None
    observations: int
    hourly_buckets: list[WeekdayHourBucket]


class HolidayPatternResponse(BaseModel):
    generated_at: datetime
    airport_code: str | None = None
    parking_lot_id: int | None = None
    source: str
    status: str
    error_message: str | None = None
    items: list[HolidayPatternItem]


class ThresholdEvent(BaseModel):
    parking_lot_id: int
    parking_lot_name: str
    airport_code: str
    airport_name: str
    threshold: int
    direction: str
    crossed_at: datetime
    previous_available_spaces: int
    current_available_spaces: int


class ThresholdWeekdayTime(BaseModel):
    threshold: int
    weekday: int
    weekday_name: str
    typical_minutes_of_day: int | None = None
    sample_count: int


class ThresholdDateHistoryItem(BaseModel):
    threshold: int
    local_date: str
    weekday: int
    weekday_name: str
    crossed_at: datetime
    minutes_of_day: int
    available_spaces: int


class ThresholdInsightsResponse(BaseModel):
    generated_at: datetime
    airport_code: str | None = None
    parking_lot_id: int | None = None
    days: int
    interval_minutes: int
    weekday_items: list[ThresholdWeekdayTime]
    history_items: list[ThresholdDateHistoryItem]


class FeeCalculationRequest(BaseModel):
    airport_code: str
    parking_lot_id: int | None = None
    vehicle_size: Literal["small", "large"] = Field(default="small")
    entry_at: datetime
    exit_at: datetime

    @model_validator(mode="after")
    def validate_interval(self) -> "FeeCalculationRequest":
        if self.exit_at <= self.entry_at:
            raise ValueError("출차 시각은 입차 시각보다 늦어야 합니다.")
        return self


class FeeBreakdown(BaseModel):
    date: str
    day_type: str
    duration_minutes: int
    applied_fee: int


class FeeCalculationResponse(BaseModel):
    supported: bool
    airport_code: str
    vehicle_size: str
    total_fee: int | None = None
    currency: str = "KRW"
    message: str | None = None
    breakdown: list[FeeBreakdown] = Field(default_factory=list)


class CollectionSummary(BaseModel):
    collection_run_id: int
    status: str
    client_mode: str
    raw_response_count: int
    snapshot_count: int
    fee_rule_count: int
    errors: list[str]


class CollectionRunStatus(BaseModel):
    id: int
    started_at: datetime
    finished_at: datetime | None = None
    status: str
    trigger: str
    error_message: str | None = None
    raw_response_count: int
    snapshot_count: int


class CollectorStatusResponse(BaseModel):
    scheduler_enabled: bool
    collect_interval_seconds: int
    effective_collect_interval_seconds: int
    scheduler_safety_buffer_seconds: int
    manual_collect_enabled: bool
    manual_collect_min_interval_seconds: int
    client_mode: str
    enabled_sources: list[str]
    data_go_kr_service_key_configured: bool
    supported_airport_codes: list[str]
    latest_snapshot_observed_at: datetime | None = None
    latest_snapshot_collected_at: datetime | None = None
    earliest_snapshot_observed_at: datetime | None = None
    manual_collect_available_at: datetime | None = None
    manual_collect_blocked: bool = False
    upstream_rate_limited: bool = False
    upstream_rate_limited_until: datetime | None = None
    last_run: CollectionRunStatus | None = None
    recent_runs: list[CollectionRunStatus]


class HealthResponse(BaseModel):
    status: str
    database: str
    seeded: bool
    release_sha: str


class BackupFile(BaseModel):
    filename: str
    size_bytes: int
    created_at: datetime


class BackupListResponse(BaseModel):
    items: list[BackupFile]


class BackupRestoreResponse(BaseModel):
    status: Literal["restored"]
    restored_from: BackupFile
    pre_restore_backup: BackupFile


class DashboardBootstrapResponse(BaseModel):
    """The minimum payload required to paint the first dashboard view."""

    airports: list[AirportSummary]
    current: ParkingCurrentResponse
    collector: CollectorStatusResponse
    holidays: HolidaySummaryResponse


class DashboardAnalyticsResponse(BaseModel):
    """Cached, lazy-loaded analytics returned in one network round trip."""

    threshold_events: list[ThresholdEvent]
    threshold_insights: ThresholdInsightsResponse
    weekday_hour_patterns: list[WeekdayHourlyPattern]
    holiday_patterns: HolidayPatternResponse
    time_series: ParkingTimeSeriesResponse
