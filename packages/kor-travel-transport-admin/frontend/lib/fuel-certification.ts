import { BadgeCheck, ReceiptText, type LucideIcon } from "lucide-react";
import type { Place } from "@/lib/journey";

/**
 * 주유소 인증 표시. 장소 응답의 typed 필드(`is_kpetro`, `is_electronic`)가 true일 때만 보여 준다.
 * false와 null(원천 미확인)은 표시하지 않으며, "인증 아님"이라고 단정하지 않는다.
 * - 품질인증: 오피넷 KPETRO_YN 표시
 * - 전산보고: 오피넷 KPETRO_DP_YN 표시(석유 거래상황 전산보고)
 * 아이콘 모양과 색을 함께 달리해 색만으로 구분하지 않는다.
 */
export const FUEL_CERTIFICATIONS = [
  { field: "is_kpetro", label: "품질인증", description: "오피넷에 품질인증 주유소로 표시된 곳입니다.", Icon: BadgeCheck, tone: "quality" },
  { field: "is_electronic", label: "믿음주유소", description: "오피넷에 석유 거래상황 전산보고 주유소로 표시된 곳입니다.", Icon: ReceiptText, tone: "trust" },
] as const satisfies readonly { field: keyof Place; label: string; description: string; Icon: LucideIcon; tone: string }[];

export function fuelCertifications(place: Pick<Place, "is_kpetro" | "is_electronic">) {
  return FUEL_CERTIFICATIONS.filter((item) => place[item.field] === true);
}
