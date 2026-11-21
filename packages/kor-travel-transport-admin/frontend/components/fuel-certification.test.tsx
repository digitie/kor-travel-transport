import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";
import { FuelCertificationBadges, FuelCertificationMarks } from "./fuel-certification";
import { fuelCertifications } from "@/lib/fuel-certification";

test("true인 인증만 정해진 순서로 돌려주고 false·미확인(null)은 표시하지 않는다", () => {
  expect(fuelCertifications({ is_kpetro: true, is_electronic: true }).map((item) => item.label)).toEqual(["품질인증", "믿음주유소"]);
  expect(fuelCertifications({ is_kpetro: null, is_electronic: true }).map((item) => item.label)).toEqual(["믿음주유소"]);
  expect(fuelCertifications({ is_kpetro: false, is_electronic: null })).toEqual([]);
  expect(fuelCertifications({})).toEqual([]);
});

test("상세 배지는 아이콘·글자·설명을, 마커 표시는 접근 이름 없이 서로 다른 아이콘만 그린다", () => {
  const place = { is_kpetro: true, is_electronic: true };
  const badges = renderToStaticMarkup(<FuelCertificationBadges place={place} />);
  expect(badges).toContain('aria-label="주유소 인증"');
  expect(badges).toContain("품질인증");
  expect(badges).toContain("전산보고 주유소");
  const marks = renderToStaticMarkup(<FuelCertificationMarks place={place} />);
  expect(marks).toContain('aria-hidden="true"');
  expect(marks.match(/class="fuel-cert-mark"/g)).toHaveLength(2);
  expect(marks).toContain("lucide-badge-check");
  expect(marks).toContain("lucide-receipt-text");
  expect(renderToStaticMarkup(<FuelCertificationMarks place={{ is_kpetro: false }} />)).toBe("");
  expect(renderToStaticMarkup(<FuelCertificationBadges place={{}} />)).toBe("");
});
