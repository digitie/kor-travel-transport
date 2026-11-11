import { expect, test } from "vitest";
import { hasCoordinates } from "./journey";
import { parkingHours, parkingNumber, parkingPagePath, publicParkingPlace, type PublicParkingItem } from "./public-parking";
import { collectionSourceLabel, placeKindLabel } from "./transport-presentation";

test("0과 미제공을 구분하고 운영시간을 임의로 보완하지 않는다", () => {
  expect(parkingNumber(0, "원")).toBe("0원");
  expect(parkingNumber(1200, "면")).toBe("1,200면");
  for (const value of [undefined, null, NaN, -1]) expect(parkingNumber(value, "원")).toBe("미제공");
  expect(parkingHours(null, null)).toBe("미제공");
  expect(parkingHours("09:00", null)).toBe("09:00 ~ 종료 미제공");
  expect(parkingHours("00:00", "24:00")).toBe("00:00 ~ 24:00");
});

test("검색과 cursor를 인코딩하고 임의 경로·수집 API로 바꾸지 않는다", () => {
  const url = new URL(parkingPagePath(" 수지 & 중앙 ", "a/b+="), "http://test/");
  expect(url.pathname).toBe("/transport/parking-lots");
  expect(url.searchParams.get("q")).toBe("수지 & 중앙");
  expect(url.searchParams.get("cursor")).toBe("a/b+=");
  expect(url.searchParams.get("limit")).toBe("100");
});

test("좌표 없는 주차장도 장소로 남기며 정적 총면수를 잔여면으로 바꾸지 않는다", () => {
  const item = { id: 12, name: "중앙주차장", source: "datagokr_parking_lots", provider_id: "P-12",
    latitude: null, longitude: null, capacity: 0, fee_info: "유료", road_address: null,
    land_address: "시험 지번", collected_at: "2026-11-03T00:00:00Z" } as PublicParkingItem;
  const place = publicParkingPlace(item);
  expect(place.kind).toBe("public_parking_lot");
  expect(hasCoordinates(place)).toBe(false);
  expect(place.parking_capacity).toBe(0);
  expect(place.address).toBe("시험 지번");
  expect(place).not.toHaveProperty("available_spaces");
  expect(placeKindLabel(place.kind)).toBe("일반 주차장");
  expect(collectionSourceLabel(place.source)).toBe("전국주차장정보 표준데이터");
});
