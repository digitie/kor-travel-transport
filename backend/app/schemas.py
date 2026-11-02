from __future__ import annotations

from datetime import date, datetime
from math import isfinite
from typing import Any, Literal

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
    airport_code: str
    parking_lot_id: int
    observed_at: datetime
    occupied_spaces: int
    total_spaces: int
    available_spaces: int


class ParkingHistoryResponse(BaseModel):
    items: list[HistoryPoint]
    next_cursor: str | None = None


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
    fuel_prices_stale: bool = Field(default=False, description="확인된 최신 유가 읽기 모델 지연 여부. false는 직후 발생한 늦은 원본 커밋까지 보증하지 않습니다.")
    fuel_prices_last_refreshed_at: datetime | None = Field(default=None, description="주유소별 가격 읽기 모델의 마지막 성공 갱신 시각(UTC).")
    items: list[FuelStationItem]


class ManualPlaceLocationRequest(BaseModel):
    """관리자만 기존 기준정보 행의 좌표를 보정한다."""

    kind: Literal["ferry_port", "bus_terminal"]
    id: int = Field(gt=0)
    source: str = Field(min_length=1, max_length=40)
    provider_id: str = Field(min_length=1, max_length=120)
    expected_name: str = Field(min_length=1, max_length=200)
    expected_city_name: str | None = Field(max_length=120)
    expected_latitude: float | None = Field(ge=-90, le=90, allow_inf_nan=False)
    expected_longitude: float | None = Field(ge=-180, le=180, allow_inf_nan=False)
    expected_location_source: str | None = Field(max_length=80)
    expected_manual_revision: str | None = Field(max_length=64)
    latitude: float = Field(ge=32, le=39.5, allow_inf_nan=False)
    longitude: float = Field(ge=124, le=132, allow_inf_nan=False)
    note: str = Field(min_length=5, max_length=500)


class TransportPlaceMapItem(BaseModel):
    """kor-travel-map·PinVi가 지도 marker로 바로 소비할 저장 장소 요약."""

    id: int
    kind: Literal["fuel_station", "rail_station", "ferry_port", "bus_terminal", "airport", "rest_area", "highway_incident"]
    source: str
    provider_id: str | None = None
    city_name: str | None = None
    name: str
    longitude: float | None
    latitude: float | None
    subtitle: str | None = None
    brand_name: str | None = None
    brand_code: str | None = None
    latest_price: float | None = None
    price_product_code: str | None = None
    prices: list[FuelPriceItem] = Field(default_factory=list)
    phone: str | None = None
    facilities: list[str] = Field(default_factory=list)
    station_type: str | None = None
    line_names: list[str] = Field(default_factory=list)
    address: str | None = None
    updated_at: datetime
    location_source: str | None = None
    manual_location_revision: str | None = None
    location_point_count: int | None = None

    @model_validator(mode="after")
    def valid_map_coordinates(self) -> "TransportPlaceMapItem":
        # 기존 DB 원본은 보존하고 모든 지도 소비자에 유효한 좌표 쌍만 제공한다.
        if (self.longitude is None or self.latitude is None
                or not isfinite(self.longitude) or not isfinite(self.latitude)
                or not -180 <= self.longitude <= 180 or not -90 <= self.latitude <= 90):
            self.longitude = self.latitude = None
        return self


class TransportPlaceMapCluster(BaseModel):
    """저배율 지도에서 좌표별 장소 요약으로 쓰는 클러스터."""

    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    count: int = Field(ge=1)
    kind_counts: dict[str, int] = Field(default_factory=dict)


class FuelCheapestStation(BaseModel):
    station_key: str
    name: str
    address: str | None = None
    longitude: float | None = None
    latitude: float | None = None


class FuelStatisticsMetrics(BaseModel):
    station_count: int
    average_price: float
    minimum_price: float
    maximum_price: float
    price_spread: float
    standard_deviation: float
    saving_50l: float
    cheapest_station: FuelCheapestStation | None = None
    cheapest_station_count: int


class FuelViewportStatistics(FuelStatisticsMetrics):
    update_pending: bool = False
    product_code: str
    generated_at: datetime


class FuelStatisticsGroup(FuelStatisticsMetrics):
    scope_key: str
    label: str
    generated_at: datetime


class FuelStatisticsHistory(BaseModel):
    day: date
    generated_at: datetime
    average_price: float
    station_count: int


class FuelStatisticsResponse(BaseModel):
    scope: str
    product_code: str
    history_scope_key: str | None = None
    generated_at: datetime | None = None
    update_pending: bool = False
    items: list[FuelStatisticsGroup]
    history: list[FuelStatisticsHistory]


class FuelRegionSummary(BaseModel):
    scope: str
    region_key: str
    label: str
    source: str
    product_code: str
    longitude: float
    latitude: float
    average_price: float
    station_count: int


class TransportPlaceMapResponse(BaseModel):
    fuel_regions: list[FuelRegionSummary] = Field(default_factory=list)
    generated_at: datetime
    kind: str | None = None
    total: int = 0
    truncated: bool = False
    clustered: bool = False
    fuel_statistics: list[FuelViewportStatistics] = Field(default_factory=list)
    kind_totals: dict[str, int] = Field(default_factory=dict)
    clusters: list[TransportPlaceMapCluster] = Field(default_factory=list)
    fuel_prices_stale: bool = Field(default=False, description="확인된 최신 유가 읽기 모델 지연 여부. false는 직후 발생한 늦은 원본 커밋까지 보증하지 않습니다.")
    fuel_prices_last_refreshed_at: datetime | None = Field(default=None, description="주유소별 가격 읽기 모델의 마지막 성공 갱신 시각(UTC).")
    available_sources: list[str] = Field(default_factory=list)
    items: list[TransportPlaceMapItem]


class KricStationMappingCode(BaseModel):
    operator_code: str = Field(min_length=1, max_length=80)
    operator_name: str = Field(min_length=1, max_length=160)
    line_code: str = Field(min_length=1, max_length=80)
    line_name: str = Field(min_length=1, max_length=160)
    station_code: str = Field(min_length=1, max_length=80)
    station_name: str = Field(min_length=1, max_length=160)
    rail_station_id: int | None = None
    rail_station_identity_key: str | None = None
    match_method: Literal["manual", "exact_identity", "station_number_and_name", "unmatched"]


class KricStationPlaceOption(BaseModel):
    id: int
    identity_key: str
    operator_name: str | None = None
    line_name: str | None = None
    station_number: str | None = None
    station_name: str | None = None


class KricStationManualMapping(BaseModel):
    operator_code: str = Field(min_length=1, max_length=80)
    line_code: str = Field(min_length=1, max_length=80)
    station_code: str = Field(min_length=1, max_length=80)
    rail_station_identity_key: str = Field(min_length=1, max_length=400)
    note: str = Field(default="", max_length=500)


class KricStationMappingResponse(BaseModel):
    schema_version: Literal[1] = 1
    revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    catalog_sha256: str | None = None
    catalog_updated_at: datetime | None = None
    mappings_updated_at: datetime | None = None
    station_count: int
    mapped_count: int
    automatic_mapped_count: int
    manual_mapped_count: int
    unmatched_count: int
    stations: list[KricStationMappingCode]
    places: list[KricStationPlaceOption]
    mappings: list[KricStationManualMapping]


class KricStationMappingSaveRequest(BaseModel):
    expected_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    mappings: list[KricStationManualMapping] = Field(max_length=1108)


class KricAutomaticMappingCounts(BaseModel):
    """장소 개수가 아닌 active 공식 catalog 코드 기준의 연결 현황."""

    station_count: int = Field(ge=0, description="active 공식 catalog 코드 수")
    mapped_count: int = Field(ge=0)
    automatic_mapped_count: int = Field(ge=0)
    manual_mapped_count: int = Field(ge=0, description="실제 유효한 수동 연결 수")
    unmatched_count: int = Field(ge=0)


class KricAutomaticMappingCodeKey(BaseModel):
    operator_code: str
    line_code: str
    station_code: str


class KricAutomaticMappingTarget(BaseModel):
    rail_station_id: int | None = None
    rail_station_identity_key: str | None = None
    match_method: Literal["manual", "exact_identity", "station_number_and_name", "unmatched"]


class KricAutomaticMappingChange(KricAutomaticMappingCodeKey):
    operator_name: str
    line_name: str
    station_name: str
    change_type: Literal["added", "removed", "retargeted", "method_changed"]
    before: KricAutomaticMappingTarget
    after: KricAutomaticMappingTarget


class KricAutomaticMappingConflict(KricAutomaticMappingCodeKey):
    rail_station_identity_key: str
    reason: Literal["manual_code_override", "manual_target_reserved"]
    reserved_by: KricAutomaticMappingCodeKey


class KricAutomaticMappingBlocker(BaseModel):
    code: str
    message: str
    operator_code: str | None = None
    line_code: str | None = None
    station_code: str | None = None


class KricAutomaticMappingPreview(BaseModel):
    schema_version: Literal[1] = 1
    generated_at: datetime
    expected_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    catalog_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    before: KricAutomaticMappingCounts
    after: KricAutomaticMappingCounts
    has_changes: bool
    can_apply: bool
    changes: list[KricAutomaticMappingChange] = Field(default_factory=list)
    manual_conflicts: list[KricAutomaticMappingConflict] = Field(default_factory=list)
    blockers: list[KricAutomaticMappingBlocker] = Field(default_factory=list)


class KricAutomaticMappingApplyRequest(BaseModel):
    model_config = {"extra": "forbid"}

    expected_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_revision: str = Field(pattern=r"^[0-9a-f]{64}$")


class KricAutomaticMappingApplyResponse(BaseModel):
    schema_version: Literal[1] = 1
    status: Literal["applied", "unchanged"]
    previous_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    changed_link_count: int = Field(ge=0)
    summary: KricAutomaticMappingCounts


class RailDepartureItem(BaseModel):
    train_number: str | None = None
    departure_time: str | None = None
    arrival_time: str | None = None
    origin_name: str | None = None
    destination_name: str | None = None


class RailDepartureSummary(BaseModel):
    place_id: int
    station_name: str
    line_name: str | None = None
    status: Literal["unlinked", "day_unresolved", "not_collected", "stored"]
    collected_at: datetime | None = None
    stale: bool = False
    next_departure: RailDepartureItem | None = None
    departure_count: int = 0


class RailTimetableItem(RailDepartureSummary):
    upcoming_departures: list[RailDepartureItem] = Field(default_factory=list)
    items: list[RailDepartureItem] = Field(default_factory=list)


class RailTimetableResponse(BaseModel):
    generated_at: datetime
    day_code: Literal["7", "8", "9"] | None = None
    basis: Literal["calendar", "selected_period", "calendar_unavailable", "overnight_unresolved"]
    items: list[RailTimetableItem]


class RailDepartureSummaryResponse(BaseModel):
    generated_at: datetime
    day_code: Literal["7", "8", "9"] | None = None
    basis: Literal["calendar", "selected_period", "calendar_unavailable", "overnight_unresolved"]
    items: list[RailDepartureSummary]


class FerryReferenceRow(BaseModel):
    record_id: str
    kind: Literal["route", "facility", "terminal"]
    name: str | None = None
    departure: str | None = None
    arrival: str | None = None
    calls: str | None = None
    segment: str | None = None
    address: str | None = None
    telephone: str | None = None
    source_year: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class FerryReferenceData(BaseModel):
    dataset: Literal["passenger_routes", "ferry_routes", "ferry_facilities", "official_terminals"]
    title: str
    source: str
    source_url: str
    source_version: str
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    collected_at: datetime
    items: list[FerryReferenceRow]


class FerryReferenceState(BaseModel):
    dataset: str
    title: str
    last_attempt_at: datetime | None = None
    last_error: str | None = None
    data: FerryReferenceData | None = None


class FerryReferenceResponse(BaseModel):
    items: list[FerryReferenceState]


class FerryOperationItem(BaseModel):
    vessel_name: str | None = None
    departure_port_name: str | None = None
    arrival_port_name: str | None = None
    departure_planned_time: str | None = None
    arrival_planned_time: str | None = None
    fare: str | None = None


class FerryOperationResponse(BaseModel):
    port_id: str
    port_name: str | None = None
    service_date: date
    fetched_at: datetime
    items: list[FerryOperationItem]


class FerryStoredTimetableResponse(BaseModel):
    service_date: date
    items: list[FerryOperationResponse]
    missing_port_ids: list[str]


class BusTerminalItem(BaseModel):
    id: int
    service_type: Literal["express", "intercity"]
    terminal_id: str
    terminal_name: str | None = None
    city_name: str | None = None
    longitude: float | None = None
    latitude: float | None = None
    location_source: str | None = None
    updated_at: datetime


class BusTerminalResponse(BaseModel):
    generated_at: datetime
    service_type: Literal["express", "intercity"]
    query: str | None = None
    offset: int
    limit: int
    total: int
    next_offset: int | None = None
    items: list[BusTerminalItem]


class BusTimetableItem(BaseModel):
    route_id: str | None = None
    departure_terminal_name: str | None = None
    arrival_terminal_name: str | None = None
    departure_planned_time: str | None = None
    arrival_planned_time: str | None = None
    grade_name: str | None = None
    adult_fare: int | None = None


class BusConnectionsResponse(BaseModel):
    service_type: Literal["express", "intercity"]
    terminal_id: str
    direction: Literal["departure", "arrival"]
    service_date: date
    coverage: Literal["stored_routes"] = "stored_routes"
    truncated: bool = False
    items: list[BusTerminalItem]


class BusTimetableResponse(BaseModel):
    service_type: Literal["express", "intercity"]
    departure_terminal_id: str
    arrival_terminal_id: str
    service_date: date
    fetched_at: datetime
    total: int | None = None
    truncated: bool = False
    stored: bool = False
    stale: bool = False
    refresh_status: Literal["stored_only", "rate_limited", "not_configured", "upstream_error"] | None = None
    items: list[BusTimetableItem]


class HighwayRoad(BaseModel):
    road_id: str
    road_number: str
    name: str


class HighwayRoadCatalog(BaseModel):
    fetched_at: datetime
    source_url: str
    stale: bool = False
    items: list[HighwayRoad]


class HighwayTrafficLink(BaseModel):
    link_id: str
    section_id: str
    section_name: str
    direction: str
    speed_kmh: float | None
    length_m: float
    path: list[tuple[float, float]] = Field(default_factory=list, max_length=20_000)


class HighwayRoadTraffic(BaseModel):
    fetched_at: datetime
    source_url: str
    stale: bool = False
    road_id: str
    road_number: str
    road_name: str
    direction: str
    complete: Literal[False] = False
    items: list[HighwayTrafficLink]


class GeneralRailCode(BaseModel):
    code: str
    name: str


class GeneralRailStation(BaseModel):
    station_id: str
    station_name: str


class GeneralRailCatalogResponse(BaseModel):
    fetched_at: datetime
    stale: bool = False
    cities: list[GeneralRailCode]
    train_classes: list[GeneralRailCode]


class GeneralRailStationsResponse(BaseModel):
    fetched_at: datetime
    stale: bool = False
    city_code: str
    items: list[GeneralRailStation]


class GeneralRailGuideStation(BaseModel):
    provider_id: str
    station_code: str | None = None
    station_name: str
    address: str | None = None
    phone: str | None = None
    longitude: float | None = None
    latitude: float | None = None


class GeneralRailGuideResponse(BaseModel):
    fetched_at: datetime
    stale: bool = False
    kind: Literal["ktx", "main"]
    category_code: str
    categories: list[GeneralRailCode]
    total: int
    items: list[GeneralRailGuideStation]


class GeneralRailTrip(BaseModel):
    train_number: str | None = None
    departure_station_name: str | None = None
    arrival_station_name: str | None = None
    departure_planned_time: str | None = None
    arrival_planned_time: str | None = None
    grade_name: str | None = None
    adult_fare: int | None = None


class GeneralRailTimetableResponse(BaseModel):
    fetched_at: datetime
    stale: bool = False
    service_date: date
    departure_station_id: str
    arrival_station_id: str
    total: int | None = None
    truncated: bool = False
    items: list[GeneralRailTrip]


class ProviderCollectionStatus(BaseModel):
    source: str
    job_status: str | None = None
    name: str
    job_name: str | None = None
    mode: Literal["scheduled", "on_demand", "unconnected"] = "scheduled"
    enabled: bool
    status: str
    interval_seconds: int | None = None
    last_started_at: datetime | None = None
    last_success_at: datetime | None = None
    next_due_at: datetime | None = None
    error_code: str | None = None


class KricCoverage(BaseModel):
    station_count: int
    linked_station_count: int
    expected_snapshots: int
    stored_snapshots: int
    fresh_snapshots: int
    oldest_collected_at: datetime | None = None


class ProviderStatusResponse(BaseModel):
    generated_at: datetime
    items: list[ProviderCollectionStatus]
    ferry_window_start: date
    ferry_window_end: date
    ferry_expected_snapshots: int
    ferry_stored_snapshots: int
    kric_coverage: KricCoverage | None = None


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
    fuel_prices_stale: bool = Field(default=False, description="확인된 최신 유가 읽기 모델 지연 여부. 상태 행이 없어도 원본이 있으면 참입니다.")
    last_fuel_success_at: datetime | None = None
    next_fuel_due_at: datetime | None = None
    last_fuel_error: str | None = None
    last_run: TransportCollectionRunStatus | None = None
    recent_runs: list[TransportCollectionRunStatus] = Field(default_factory=list)
    running_run_count: int = 0
    running_runs: list[TransportCollectionRunStatus] = Field(default_factory=list)
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


class ParkingOutlookLot(BaseModel):
    parking_lot_id: int
    parking_lot_name: str
    sample_days: int
    observations: int
    average_available_spaces: float
    minimum_available_spaces: int
    maximum_available_spaces: int
    full_days: int
    full_day_ratio: float
    minimum_capacity: int
    maximum_capacity: int
    latest_observed_at: datetime


class ParkingOutlookResponse(BaseModel):
    generated_at: datetime
    airport_code: str
    arrival_at: datetime
    history_days: int
    weekday: int
    hour: int
    items: list[ParkingOutlookLot]


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
        if self.entry_at.tzinfo is None or self.exit_at.tzinfo is None:
            raise ValueError("입출차 시각에는 시간대가 필요합니다.")
        if self.exit_at <= self.entry_at:
            raise ValueError("출차 시각은 입차 시각보다 늦어야 합니다.")
        if (self.exit_at - self.entry_at).total_seconds() > 366 * 86400:
            raise ValueError("요금 계산 기간은 최대 366일입니다.")
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
    reason_code: str | None = None
    official_url: str | None = None
    rule_updated_at: datetime | None = None
    parking_lot_id: int | None = None
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


# --- 내부 서비스 export (ADR-013) -------------------------------------------------
# `/v1/service/exports/*`는 kor-travel-map 같은 내부 소비자가 저장 데이터를 일괄로 읽는 경로다.
# 응답은 concierge export와 같은 무-envelope 모양 `{items, next_cursor, has_more}`이고
# cursor는 불투명 문자열이다. 원본 provider 행은 `raw`로 그대로 넘긴다(소비자의 lineage 증거).


class ExportCollectionState(BaseModel):
    """이 export가 근거로 삼는 transport 수집의 상태. 오류 문구는 노출하지 않는다.

    `failed`·`stale`은 "이 집합을 낼 수 없다"는 503 사유라 200 본문에서는 언제나 false다.
    `last_attempt_failed`는 마지막 수집 시도가 실패했는지의 사실이다 — 참조 데이터는 마지막 성공이 stale
    기준 안이면 그 뒤 시도가 실패해도 마지막 성공 수집의 집합을 200으로 내고 이 값을 true로 둔다(ADR-013).
    """

    source: str
    last_success_at: datetime | None = None
    failed: bool
    stale: bool
    last_attempt_failed: bool


class ExportFuelPrice(BaseModel):
    product_code: str
    price: float | None = None
    provider_updated_at: datetime | None = None
    observed_at: datetime
    collected_at: datetime


class ExportAdminAddress(BaseModel):
    """현재 좌표와 일치하는 마지막 reverse 주소. resolved_at은 실제 확인 시각이다."""

    legal_dong_code: str | None = Field(default=None, pattern=r"^[0-9]{10}$")
    admin_dong_code: str | None = None
    sido_name: str | None = None
    sigungu_name: str | None = None
    legal_dong_name: str | None = None
    road_address: str | None = None
    parcel_address: str | None = None
    postal_code: str | None = None
    provider: Literal["vworld", "kakao"]
    resolved_at: datetime


class ExportFuelStation(BaseModel):
    natural_key: str = Field(description="오피넷 주유소 ID(uni_id). 안정 자연키")
    source: str
    name: str
    brand_code: str | None = None
    brand_name: str | None = None
    phone: str | None = None
    address: str | None = None
    longitude: float | None = None
    latitude: float | None = None
    is_self: bool | None = None
    is_24h: bool | None = None
    has_carwash: bool | None = None
    has_maintenance: bool | None = None
    has_cvs: bool | None = None
    first_seen_at: datetime
    last_seen_at: datetime
    prices: list[ExportFuelPrice]
    admin: ExportAdminAddress | None = None
    raw: dict | None = None


class FuelStationExportPage(BaseModel):
    generated_at: datetime
    collection: ExportCollectionState
    items: list[ExportFuelStation]
    next_cursor: str | None = None
    has_more: bool


class ExportRestArea(BaseModel):
    natural_key: str = Field(description="`name::route_name::direction`(strip→lower). 원천에 안정 ID가 없다")
    source: str
    name: str
    route_name: str | None = None
    direction: str | None = None
    longitude: float | None = None
    latitude: float | None = None
    has_gas_station: bool | None = None
    has_lpg_station: bool | None = None
    has_ev_charger: bool | None = None
    phone_number: str | None = None
    data_reference_date: str | None = None
    first_seen_at: datetime
    last_seen_at: datetime
    admin: ExportAdminAddress | None = None
    raw: dict | None = None


class RestAreaExportPage(BaseModel):
    generated_at: datetime
    collection: ExportCollectionState
    items: list[ExportRestArea]
    next_cursor: str | None = None
    has_more: bool


class ExportRestAreaFuelPrice(BaseModel):
    service_area_code: str = Field(description="한국도로공사 휴게소 코드. 안정 자연키")
    source: str
    service_area_code2: str | None = None
    service_area_name: str | None = None
    route_code: str | None = None
    route_name: str | None = None
    direction: str | None = None
    oil_company: str | None = None
    has_lpg: bool | None = None
    phone_number: str | None = None
    address: str | None = None
    gasoline_price: int | None = None
    diesel_price: int | None = None
    lpg_price: int | None = None
    observed_at: datetime = Field(description="원천에 관측 시각이 없어 transport 수집 시각")
    raw: dict | None = None


class RestAreaFuelPriceExportPage(BaseModel):
    generated_at: datetime
    collection: ExportCollectionState
    items: list[ExportRestAreaFuelPrice]
    next_cursor: str | None = None
    has_more: bool


class ExportHighwayIncident(BaseModel):
    identity_key: str
    source: str
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
    observed_at: datetime = Field(description="이 상태를 처음 관측한 시각")
    collected_at: datetime = Field(description="마지막으로 재관측한 시각(= 활성 집합 수집 시각)")
    raw: dict | None = None


class HighwayIncidentActiveSet(BaseModel):
    """마지막 성공 돌발 수집이 본 활성 사건 전체. 여기에 없는 사건은 해소된 것이다."""

    generated_at: datetime
    collection: ExportCollectionState
    collected_at: datetime
    items: list[ExportHighwayIncident]


class ExportAirport(BaseModel):
    code: str = Field(description="IATA 공항 코드. 안정 자연키")
    icao_code: str | None = None
    name_korean: str | None = None
    name_english: str
    municipality: str | None = None
    longitude: float | None = None
    latitude: float | None = None
    airport_type: str | None = None
    metadata_source: str | None = Field(default=None, description="좌표·메타데이터 출처(krairport 번들)")
    has_parking_data: bool = Field(description="transport가 이 공항의 주차 현황을 수집하는지")


class AirportExportResponse(BaseModel):
    generated_at: datetime
    items: list[ExportAirport]


class AddressRefreshSummary(BaseModel):
    total: int
    due: int
    failed: int
    last_resolved_at: str | None
    in_progress: bool
    manual_cycle: bool
    refresh_months: int
    configured: bool
    auto_enabled: bool
    items: list[dict[str, Any]]


class ServiceExportMeta(BaseModel):
    generated_at: datetime
    source_collected_at: datetime | None
    source_status: Literal["ok", "stale", "failed"]
    item_count: int


class ExportPriceHistoryItem(BaseModel):
    product_code: str
    observed_at: datetime
    price: float | None


class FuelPriceHistoryExportPage(BaseModel):
    meta: ServiceExportMeta
    station_key: str
    items: list[ExportPriceHistoryItem]
    next_cursor: str | None = None
    has_more: bool


class FuelPriceHistoryWindow(BaseModel):
    from_at: datetime
    to_at: datetime
    mode: Literal["rolling"] = "rolling"
    timezone: Literal["Asia/Seoul"] = "Asia/Seoul"


class FuelStationPriceHistoryResponse(BaseModel):
    """공개 저장 이력. 창은 UTC rolling 기간이며 화면 날짜만 KST로 표시한다."""

    meta: ServiceExportMeta
    station_id: int
    source: str
    provider_id: str | None
    brand_code: str | None
    brand_name: str | None
    window: FuelPriceHistoryWindow
    source_last_success_at: datetime
    source_revision: str
    latest: list[FuelPriceItem] = Field(description="현재 저장 가격. 조회 창 밖의 오래된 관측일 수 있어 이력 그래프와 구분합니다.")
    items: list[FuelPriceItem] = Field(description="창 안 실제 관측의 최신순 페이지. null/0은 유효 가격으로 그리지 않습니다.")
    next_cursor: str | None = None
    has_more: bool


class ExportHighwayTrafficCurrent(BaseModel):
    identity_key: str
    source: str
    route_no: str | None
    route_name: str | None
    conzone_id: str | None
    conzone_name: str | None
    direction: str | None
    speed: float | None
    free_flow_speed: float | None
    congestion_level: str | None
    observed_at: datetime
    collected_at: datetime


class HighwayTrafficCurrentExportPage(BaseModel):
    meta: ServiceExportMeta
    snapshot_id: str
    snapshot_expires_at: datetime
    total_count: int
    items: list[ExportHighwayTrafficCurrent]
    next_cursor: str | None
    has_more: bool


class ExportBusTerminalReference(BaseModel):
    natural_key: str
    source: str
    service_type: str
    terminal_id: str
    name: str
    city_name: str | None
    latitude: float | None
    longitude: float | None
    location_source: str | None
    manual_location_revision: str | None
    admin: ExportAdminAddress | None


class BusTerminalExportPage(BaseModel):
    meta: ServiceExportMeta
    snapshot_id: str
    snapshot_expires_at: datetime
    total_count: int
    items: list[ExportBusTerminalReference]
    next_cursor: str | None
    has_more: bool


class ExportFerryPortReference(BaseModel):
    natural_key: str
    source: str
    port_id: str
    name: str
    latitude: float | None
    longitude: float | None
    location_source: str | None
    location_point_count: int
    manual_location_revision: str | None
    admin: ExportAdminAddress | None


class FerryPortExportPage(BaseModel):
    meta: ServiceExportMeta
    snapshot_id: str
    snapshot_expires_at: datetime
    total_count: int
    items: list[ExportFerryPortReference]
    next_cursor: str | None
    has_more: bool


class ExportRailStationReference(BaseModel):
    natural_key: str
    source: str
    name: str
    operator_name: str | None
    line_name: str | None
    station_number: str | None
    latitude: float | None
    longitude: float | None
    operator_code: str | None
    line_code: str | None
    station_code: str | None
    code_station_name: str | None
    code_collected_at: datetime | None
    code_active: bool
    mapping_method: str | None
    mapping_revision: str
    admin: ExportAdminAddress | None


class RailStationExportPage(BaseModel):
    meta: ServiceExportMeta
    snapshot_id: str
    snapshot_expires_at: datetime
    total_count: int
    items: list[ExportRailStationReference]
    next_cursor: str | None
    has_more: bool


class ExportParkingCurrent(BaseModel):
    natural_key: str
    source: str
    airport_code: str
    lot_code: str
    name: str
    latitude: float | None
    longitude: float | None
    location_source: Literal["airport_anchor"]
    total_spaces: int
    occupied_spaces: int
    available_spaces: int
    observed_at: datetime
    collected_at: datetime


class ParkingCurrentExportPage(BaseModel):
    meta: ServiceExportMeta
    snapshot_id: str
    snapshot_expires_at: datetime
    total_count: int
    items: list[ExportParkingCurrent]
    next_cursor: str | None
    has_more: bool
