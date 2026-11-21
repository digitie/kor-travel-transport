import { fuelCertifications } from "@/lib/fuel-certification";
import { cn } from "@/lib/utils";

/** 마커용 작은 아이콘 묶음. 접근 이름은 마커 버튼의 aria-label이 갖는다. */
export function FuelCertificationMarks({ facilities, className }: { facilities: readonly string[] | undefined; className?: string }) {
  const items = fuelCertifications(facilities);
  if (!items.length) return null;
  return <span className={cn("fuel-cert-marks", className)} aria-hidden="true">
    {items.map(({ label, Icon, tone }) => <span key={label} className="fuel-cert-mark" data-tone={tone} title={label}><Icon size={11} strokeWidth={2.5} /></span>)}
  </span>;
}

/** 상세 패널용 아이콘 + 글자 배지. */
export function FuelCertificationBadges({ facilities }: { facilities: readonly string[] | undefined }) {
  const items = fuelCertifications(facilities);
  if (!items.length) return null;
  return <ul className="fuel-cert-badges" aria-label="주유소 인증">
    {items.map(({ label, description, Icon, tone }) => <li key={label} className="fuel-cert-badge" data-tone={tone} title={description}>
      <Icon size={14} aria-hidden="true" />{label}
    </li>)}
  </ul>;
}
