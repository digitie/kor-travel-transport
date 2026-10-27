export type MappingCode = { operator_code: string; line_code: string; station_code: string };
export type MappingTarget = { rail_station_id: number | null; rail_station_identity_key: string | null; match_method: "manual" | "exact_identity" | "station_number_and_name" | "unmatched" };
export type MappingStation = MappingCode & MappingTarget & { operator_name: string; line_name: string; station_name: string };
export type MappingPlace = { id: number; identity_key: string; operator_name: string | null; line_name: string | null; station_number: string | null; station_name: string | null };
export type ManualMapping = MappingCode & { rail_station_identity_key: string; note: string };
export type MappingCounts = { station_count: number; mapped_count: number; automatic_mapped_count: number; manual_mapped_count: number; unmatched_count: number };
export type MappingDocument = MappingCounts & { schema_version: 1; revision: string; catalog_sha256: string | null; catalog_updated_at: string | null; mappings_updated_at: string | null; stations: MappingStation[]; places: MappingPlace[]; mappings: ManualMapping[] };
export type AutomaticMappingPreview = { schema_version: 1; generated_at: string; expected_revision: string; candidate_revision: string; catalog_sha256: string;
  before: MappingCounts; after: MappingCounts; has_changes: boolean; can_apply: boolean;
  changes: (MappingCode & { operator_name: string; line_name: string; station_name: string; change_type: "added" | "removed" | "retargeted" | "method_changed"; before: MappingTarget; after: MappingTarget })[];
  manual_conflicts: (MappingCode & { rail_station_identity_key: string; reason: "manual_code_override" | "manual_target_reserved"; reserved_by: MappingCode })[];
  blockers: { code: string; message: string; operator_code: string | null; line_code: string | null; station_code: string | null }[];
};
export type AutomaticMappingApply = { schema_version: 1; status: "applied" | "unchanged"; previous_revision: string; revision: string; changed_link_count: number; summary: MappingCounts };
export class MappingRequestError extends Error { constructor(message: string, public status: number) { super(message); } }
const path = "/api/admin/rail-station-mappings";
async function request<T>(url: string, signal: AbortSignal, payload?: unknown): Promise<T> {
  const response = await fetch(url, { cache: "no-store", signal, ...(payload ? { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) } : {}) });
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: unknown } | null;
    throw new MappingRequestError(typeof body?.detail === "string" ? body.detail : `요청에 실패했습니다 (${response.status}).`, response.status);
  }
  return response.json() as Promise<T>;
}
export const readMappings = (signal: AbortSignal) => request<MappingDocument>(path, signal);
export const saveMappings = (expected_revision: string, mappings: ManualMapping[], signal: AbortSignal) => request<MappingDocument>(path, signal, { expected_revision, mappings });
export const previewAutomaticMappings = (signal: AbortSignal) => request<AutomaticMappingPreview>(path + "/automatic", signal);
export const applyAutomaticMappings = (preview: Pick<AutomaticMappingPreview, "expected_revision" | "candidate_revision">, signal: AbortSignal) => request<AutomaticMappingApply>(path + "/automatic", signal, { expected_revision: preview.expected_revision, candidate_revision: preview.candidate_revision });
