import { expect, test } from "vitest";
import { fuelBrand } from "./fuel-brands";

test.each([["SKE", "sk.gif"], ["GSC", "gs.gif"], ["HDO", "hy.gif"], ["SOL", "soil.gif"], ["NHO", "nho.gif"], ["RTO", "rto.gif"], ["RTE", "rto.gif"], ["RTX", "rtx.gif"]])("제공기관 상표 %s를 확인된 원본 이미지로 연결한다", (code, image) => {
  expect(fuelBrand(code, "다른 이름").image).toBe(image);
});
test.each(["S-OIL", "s oil", "에쓰오일"])("정확한 이름 별칭 %s를 정규화한다", (name) => expect(fuelBrand(null, name).code).toBe("SOL"));
test("자가상표·미확인 코드와 비슷한 이름을 유명 정유사로 추측하지 않는다", () => {
  expect(fuelBrand("ETC", "SK에너지").image).toBeNull();
  expect(fuelBrand("RTX").name).toContain("고속도로알뜰");
  expect(fuelBrand("unknown", "GS칼텍스").image).toBeNull();
  expect(fuelBrand(null, "SK할인주유소").image).toBeNull();
  expect(fuelBrand("RTO").name).toBe("알뜰주유소");
  expect(fuelBrand().name).toBe("상표 미제공");
});
