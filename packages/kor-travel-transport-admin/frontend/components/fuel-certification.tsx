import { fuelCertifications } from "@/lib/fuel-certification";
import type { Place } from "@/lib/journey";
import { cn } from "@/lib/utils";

type Certified = Pick<Place, "is_kpetro" | "is_electronic">;

/** 마커용 작은 아이콘 묶음. 접근 이름과 hover 제목은 마커 버튼이 갖는다. */
export function FuelCertificationMarks({ place, className }: { place: Certified; className?: string }) {
  const items = fuelCertifications(place);
  if (!items.length) return null;
  return <span className={cn("fuel-cert-marks", className)} aria-hidden="true">
    {items.map(({ label, Icon, tone }) => <span key={label} className="fuel-cert-mark" data-tone={tone}><Icon size={11} strokeWidth={2.5} /></span>)}
  </span>;
}

/** 상세 패널용 아이콘 + 글자 배지. 설명은 화면 읽기 프로그램에도 전달한다. */
export function FuelCertificationBadges({ place }: { place: Certified }) {
  const items = fuelCertifications(place);
  if (!items.length) return null;
  return <ul className="fuel-cert-badges" aria-label="주유소 인증">
    {items.map(({ label, description, Icon, tone }) => <li key={label} className="fuel-cert-badge" data-tone={tone} title={description}>
      <Icon size={14} aria-hidden="true" />{label}<span className="sr-only"> · {description}</span>
    </li>)}
  </ul>;
}
