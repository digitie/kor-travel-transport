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
