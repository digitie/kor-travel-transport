import { expect, test } from "@playwright/test";
import { request as httpRequest } from "node:http";
import { request as httpsRequest } from "node:https";
import { brotliDecompressSync, gunzipSync } from "node:zlib";

/**
 * 30일 전체 이력(`days=30`, limit 없음)은 backend 본문을 스트림으로 넘기는 별도 프록시 경로(pages API)다.
 * App Router route handler는 응답의 content-encoding을 버리고 서버 압축을 다시 건다 — backend 압축 본문을
 * 그대로 넘기면 gzip이 두 겹이 돼 브라우저가 JSON을 읽지 못했다(2026-11-24 운영 검증).
 * 운영 공개 URL에서도 돌릴 수 있게 압축 응답만 받는다(비압축 75MB 요청은 하지 않는다).
 */
const HISTORY_PATH = "/api/backend/v1/parking/history?days=30";

function baseUrl(): string {
  return process.env.E2E_BASE_URL ?? "http://127.0.0.1:3000";
}

/** gzip만 받겠다고 보내고 받은 바이트·헤더를 그대로 돌려준다(자동 해제 없이). */
function rawGet(path: string, acceptEncoding: string): Promise<{ status: number; encoding: string | undefined; body: Buffer }> {
  const url = new URL(path, baseUrl());
  const send = url.protocol === "https:" ? httpsRequest : httpRequest;
  return new Promise((resolve, reject) => {
    const req = send(url, { headers: { "accept-encoding": acceptEncoding, accept: "application/json" } }, (response) => {
      const chunks: Buffer[] = [];
      response.on("data", (chunk: Buffer) => chunks.push(chunk));
      response.on("end", () => resolve({
        status: response.statusCode ?? 0,
        encoding: response.headers["content-encoding"],
        body: Buffer.concat(chunks),
      }));
      response.on("error", reject);
    });
    req.on("error", reject);
    req.end();
  });
}

test.describe("30일 전체 이력 응답 압축", () => {
  test.setTimeout(180_000);

  for (const acceptEncoding of ["gzip", "br, gzip"]) {
    test(`${acceptEncoding} 요청은 한 겹만 압축된다`, async () => {
      const started = Date.now();
      const response = await rawGet(HISTORY_PATH, acceptEncoding);
      expect(response.status).toBe(200);
      // 압축을 아예 하지 않는 퇴행(75MB 원문)도 잡는다.
      expect(["gzip", "br"]).toContain(response.encoding);
      if (acceptEncoding === "gzip") expect(response.encoding).toBe("gzip");
      const once = response.encoding === "br" ? brotliDecompressSync(response.body) : gunzipSync(response.body);
      // 두 겹이면 한 번 푼 결과가 다시 gzip 머리(1f 8b)로 시작한다.
      expect(once.subarray(0, 2).toString("hex")).not.toBe("1f8b");
      const parsed = JSON.parse(once.toString("utf8")) as { items: { observed_at?: string }[] };
      expect(Array.isArray(parsed.items)).toBe(true);
      // 질의(days=30)가 유실돼 기본 기간으로 퇴행하지 않았는지 — 첫 관측이 25일보다 오래됐다.
      const first = parsed.items[0]?.observed_at;
      if (first) expect(Date.now() - Date.parse(first)).toBeGreaterThan(25 * 86_400_000);
      test.info().annotations.push({
        type: "transfer",
        description: `${acceptEncoding}: ${response.encoding} ${response.body.length}B ${Date.now() - started}ms`,
      });
    });
  }

  test("브라우저 fetch가 전체 이력을 JSON으로 읽는다", async ({ page }) => {
    await page.goto("/");
    const result = await page.evaluate(async (path) => {
      const response = await fetch(path, { headers: { accept: "application/json" } });
      const text = await response.text();
      try {
        const parsed = JSON.parse(text) as { items?: unknown };
        return { status: response.status, isArray: Array.isArray(parsed.items), head: "" };
      } catch {
        return { status: response.status, isArray: false, head: text.slice(0, 16) };
      }
    }, HISTORY_PATH);
    expect(result).toEqual({ status: 200, isArray: true, head: "" });
  });
});
