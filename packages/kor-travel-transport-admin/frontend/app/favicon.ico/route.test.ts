import { afterEach, expect, test, vi } from "vitest";
import { GET } from "./route";

afterEach(() => vi.unstubAllEnvs());

test("공개 유가(fuel) 실행은 /favicon.ico로 ICO 아이콘을 낸다", async () => {
  vi.stubEnv("TRANSPORT_UI_MODE", "fuel");
  const response = GET();
  expect(response.status).toBe(200);
  expect(response.headers.get("content-type")).toBe("image/x-icon");
  const bytes = new Uint8Array(await response.arrayBuffer());
  // ICO 머리: reserved 0, type 1(icon), 이미지 3개(16·32·48).
  expect([...bytes.slice(0, 6)]).toEqual([0, 0, 1, 0, 3, 0]);
  expect(bytes.length).toBeGreaterThan(1000);
});

test("관리 화면 실행은 예전처럼 favicon이 없다(404)", () => {
  vi.stubEnv("TRANSPORT_UI_MODE", "admin");
  expect(GET().status).toBe(404);
  vi.stubEnv("TRANSPORT_UI_MODE", "");
  expect(GET().status).toBe(404);
});
