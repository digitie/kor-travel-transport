from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "parking-radar"
    database_url: str = "postgresql+asyncpg://parking_radar:parking_radar@postgres:5432/parking_radar"
    app_timezone: str = "Asia/Seoul"
    enable_scheduler: bool = False
    seed_sample_data: bool = True
    collect_interval_seconds: int = Field(default=300, gt=0)
    scheduler_safety_buffer_seconds: int = Field(default=60, ge=0)
    manual_collect_enabled: bool = False
    manual_collect_min_interval_seconds: int = Field(default=300, ge=0)
    upstream_rate_limit_backoff_seconds: int = Field(default=3600, ge=0)
    api_timeout_seconds: int = Field(default=15, gt=0)
    data_go_kr_service_key: str | None = None
    kex_ex_api_key: str | None = None
    transport_collection_enabled: bool = False
    transport_collect_interval_seconds: int = Field(default=300, ge=300)
    transport_quota_backoff_seconds: int = Field(default=3600, ge=300)
    transport_route_nos_csv: str = ""
    transport_conzone_ids_csv: str = ""
    opinet_browser_enabled: bool = True
    opinet_query_level: str = "sigungu"
    opinet_browser_channel: str | None = None
    opinet_browser_timeout_ms: int = Field(default=60_000, gt=0)
    enable_flight_status_markers: bool = True
    flight_status_cache_seconds: int = 300
    holiday_cache_seconds: int = 86400
    enable_incheon_collection: bool = True
    enable_incheon_fee_collection: bool = False
    enable_fee_collection: bool = False
    airport_codes_csv: str = "CJJ,CJU,GMP,HIN,ICN,KUV,KWJ,MWX,PUS,RSU,TAE,USN,WJU,YNY"
    cors_origins_csv: str = "http://localhost:3000"
    trusted_hosts_csv: str = "localhost,127.0.0.1,testserver,backend"
    enable_api_docs: bool = True
    api_prefix: str = ""
    use_sample_client_when_no_key: bool = True
    backup_dir: str = "/app/backups"
    backup_retention_count: int = 14
    backup_command_timeout_seconds: int = 120
    backup_upload_timeout_seconds: int = Field(default=600, gt=0)
    backup_storage_limit_bytes: int = Field(default=8 * 1024 * 1024 * 1024, gt=0)
    release_sha: str = "unknown"

    @property
    def supported_airport_codes(self) -> list[str]:
        return [code.strip().upper() for code in self.airport_codes_csv.split(",") if code.strip()]

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins_csv.split(",") if origin.strip()]

    @property
    def trusted_hosts(self) -> list[str]:
        return [host.strip() for host in self.trusted_hosts_csv.split(",") if host.strip()]

    @property
    def transport_route_nos(self) -> list[str]:
        return [value.strip() for value in self.transport_route_nos_csv.split(",") if value.strip()]

    @property
    def transport_conzone_ids(self) -> list[str]:
        return [value.strip() for value in self.transport_conzone_ids_csv.split(",") if value.strip()]

    @property
    def effective_collect_interval_seconds(self) -> int:
        return max(1, self.collect_interval_seconds - self.scheduler_safety_buffer_seconds)


@lru_cache
def get_settings() -> Settings:
    return Settings()
