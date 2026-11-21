import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";
import { FuelCertificationBadges, FuelCertificationMarks } from "./fuel-certification";
import { fuelAmenities, fuelCertifications } from "@/lib/fuel-certification";

const facilities = ["셀프", "세차", "품질인증", "믿음주유소"];

test("인증 라벨은 편의시설과 분리하고 정해진 순서로 돌려준다", () => {
  expect(fuelCertifications(facilities).map((item) => item.label)).toEqual(["품질인증", "믿음주유소"]);
  expect(fuelCertifications(["믿음주유소"]).map((item) => item.label)).toEqual(["믿음주유소"]);
  expect(fuelAmenities(facilities)).toEqual(["셀프", "세차"]);
  expect(fuelCertifications(undefined)).toEqual([]);
});

test("상세 배지는 아이콘과 글자를 함께, 마커 표시는 접근 이름 없이 아이콘만 그린다", () => {
  const badges = renderToStaticMarkup(<FuelCertificationBadges facilities={facilities} />);
  expect(badges).toContain('aria-label="주유소 인증"');
  expect(badges).toContain("품질인증");
  expect(badges).toContain("믿음주유소");
  expect(badges.match(/<svg/g)).toHaveLength(2);
  const marks = renderToStaticMarkup(<FuelCertificationMarks facilities={facilities} />);
  expect(marks).toContain('aria-hidden="true"');
  expect(marks.match(/class="fuel-cert-mark"/g)).toHaveLength(2);
  expect(renderToStaticMarkup(<FuelCertificationMarks facilities={["셀프"]} />)).toBe("");
  expect(renderToStaticMarkup(<FuelCertificationBadges facilities={[]} />)).toBe("");
});
