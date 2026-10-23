// 서버간 service export 계약. 브라우저 호출 경로나 토큰을 추가하지 않는다.
export type ExportAdminAddress = {
  legal_dong_code?: string | null;
  admin_dong_code?: string | null;
  sido_name?: string | null;
  sigungu_name?: string | null;
  legal_dong_name?: string | null;
  road_address?: string | null;
  parcel_address?: string | null;
  postal_code?: string | null;
  provider: "vworld" | "kakao";
  resolved_at: string;
};

export type ExportAddressBlock = { admin?: ExportAdminAddress | null };


export type ServiceExportMeta = {
  generated_at: string;
  source_collected_at: string | null;
  source_status: "ok" | "stale" | "failed";
  item_count: number;
};

export type FuelPriceHistoryExportPage = {
  meta: ServiceExportMeta;
  station_key: string;
  items: { product_code: string; observed_at: string; price: number | null }[];
  next_cursor: string | null;
  has_more: boolean;
};


export type ServiceExportProblemDetails = {
  type: string;
  title: string;
  status: number;
  detail: string;
  instance: string;
  meta: ServiceExportMeta;
};


export type HighwayTrafficCurrentExportPage = {
  meta: ServiceExportMeta;
  snapshot_id: string;
  snapshot_expires_at: string;
  total_count: number;
  items: {
    identity_key: string;
    source: string;
    route_no: string | null;
    route_name: string | null;
    conzone_id: string | null;
    conzone_name: string | null;
    direction: string | null;
    speed: number | null;
    free_flow_speed: number | null;
    congestion_level: string | null;
    observed_at: string;
    collected_at: string;
  }[];
  next_cursor: string | null;
  has_more: boolean;
};


export type BusTerminalExportPage = {
  meta: ServiceExportMeta;
  snapshot_id: string;
  snapshot_expires_at: string;
  total_count: number;
  items: {
    natural_key: string;
    source: string;
    service_type: string;
    terminal_id: string;
    name: string;
    city_name: string | null;
    latitude: number | null;
    longitude: number | null;
    location_source: string | null;
    manual_location_revision: string | null;
    admin: ExportAdminAddress | null;
  }[];
  next_cursor: string | null;
  has_more: boolean;
};


export type FerryPortExportPage = {
  meta: ServiceExportMeta;
  snapshot_id: string;
  snapshot_expires_at: string;
  total_count: number;
  items: {
    natural_key: string;
    source: string;
    port_id: string;
    name: string;
    latitude: number | null;
    longitude: number | null;
    location_source: string | null;
    location_point_count: number;
    manual_location_revision: string | null;
    admin: ExportAdminAddress | null;
  }[];
  next_cursor: string | null;
  has_more: boolean;
};
