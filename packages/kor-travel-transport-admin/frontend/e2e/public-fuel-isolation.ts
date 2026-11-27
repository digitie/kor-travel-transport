import type { Page } from "@playwright/test";
import { MAP_FALLBACK_IMAGE } from "../lib/map-fallback";

const TILE = Buffer.from(MAP_FALLBACK_IMAGE.split(",")[1], "base64");

/**
 * 공개 유가 격리 e2e의 외부 요청 차단. 외부 호스트는 막되 VWorld 배경지도 타일(WMTS)만 1px 성공 이미지로 채운다.
 *
 * 타일까지 막으면 VWorld 키로 빌드한 서버에서는 지도 첫 idle 뒤(시험 단계와 무관한 시각) "지도 타일 오류" 알림이 범위 요약 위 줄
 * (`.map-feedback`, 34.5px)에 생겨 요약 전체가 내려간다. 요약 위치를 전후로 재거나 같은 줄의 두 요소를 차례로 재는 검사가 그 순간에
 * 걸리면 34.5px 어긋남으로 실패했다(FUEL-PUBLIC-MAP-RETRY-E2E, 부하 중 public-fuel-ui2 "가격 아이콘 하나"). 키 없이 빌드하면
 * "지도 키 없음" 알림이 처음부터 있어 이 차이가 숨는다 — 빌드 키에 따라 결과가 갈리지 않게 타일은 늘 성공시킨다.
 */
export async function isolatePublicFuel(page: Page) {
  await page.route((url) => /^https?:$/.test(url.protocol) && !["127.0.0.1", "localhost"].includes(url.hostname), (route) => route.abort());
  // 나중에 등록한 route가 먼저 처리된다.
  await page.route("https://api.vworld.kr/req/wmts/**", (route) => route.fulfill({
    contentType: "image/png", headers: { "access-control-allow-origin": "*" }, body: TILE,
  }));
}
