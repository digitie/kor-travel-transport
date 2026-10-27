import { readFileSync } from "node:fs";

// 공개 앱과 관리자 /parking이 함께 쓰는 parking.css의 경계. `@scope`를 모르는 브라우저(iOS 16 Safari,
// Firefox ESR 140, Chromium 118 미만)는 at-rule 블록 전체를 버려 화면 스타일이 통째로 사라진다. Lightning CSS는
// `@scope`를 내리지 않지만 nesting은 빌드 대상에 맞춰 `:where(.parking-radar) <selector>`로 평탄화한다.
// `:where()`는 특이도를 더하지 않아 `@scope` 때의 특이도와 관리자 `.parking-admin` override 우선순위를 지킨다.
const css = readFileSync("src/parking.css", "utf8").replace(/\/\*[\s\S]*?\*\//g, "");

describe("parking.css 경계", () => {
  test("@scope 대신 특이도 0인 :where(.parking-radar) nesting wrapper를 쓴다", () => {
    expect(css).not.toMatch(/@scope\b/);
    expect(css.trimStart().startsWith(":where(.parking-radar) {")).toBe(true);
  });

  test("wrapper 하나가 파일 끝까지 모든 규칙을 감싼다", () => {
    const body = css.trim();
    let depth = 0;
    let firstClose = -1;
    for (let index = 0; index < body.length; index += 1) {
      if (body[index] === "{") depth += 1;
      if (body[index] === "}") {
        depth -= 1;
        if (depth === 0 && firstClose < 0) firstClose = index;
      }
    }
    expect(depth).toBe(0);
    expect(firstClose).toBe(body.length - 1);
  });
});
