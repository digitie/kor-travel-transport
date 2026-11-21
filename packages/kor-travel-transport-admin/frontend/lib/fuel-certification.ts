import { BadgeCheck, ShieldCheck, type LucideIcon } from "lucide-react";

/**
 * 주유소 인증 표시. backend `FUEL_FACILITY_LABELS`가 facilities에 넣는 라벨과 같아야 한다.
 * - 품질인증: 오피넷 KPETRO_YN, 한국석유관리원 품질인증프로그램 협약 주유소
 * - 믿음주유소: 오피넷 KPETRO_DP_YN, 석유 수급·거래 상황을 전산으로 보고하는 주유소
 */
export const FUEL_CERTIFICATIONS: readonly { label: string; description: string; Icon: LucideIcon; tone: string }[] = [
  { label: "품질인증", description: "한국석유관리원 품질인증 주유소", Icon: ShieldCheck, tone: "quality" },
  { label: "믿음주유소", description: "석유 거래를 전산으로 보고하는 믿음주유소", Icon: BadgeCheck, tone: "trust" },
];
const CERTIFICATION_LABELS = new Set(FUEL_CERTIFICATIONS.map((item) => item.label));

export function fuelCertifications(facilities: readonly string[] | undefined) {
  return FUEL_CERTIFICATIONS.filter((item) => facilities?.includes(item.label));
}

/** 인증 라벨을 뺀 편의시설 목록. 인증은 배지로 따로 보여 준다. */
export function fuelAmenities(facilities: readonly string[] | undefined) {
  return (facilities ?? []).filter((label) => !CERTIFICATION_LABELS.has(label));
}
