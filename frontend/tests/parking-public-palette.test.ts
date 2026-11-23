import { readFileSync } from "node:fs";
import path from "node:path";

// 공개 앱은 관리자와 같은 look을 쓴다. 공개 이미지는 frontend/만 복사해 관리자 팔레트를 import하지 못하므로
// src/app/tokens.css가 같은 값을 갖는다 — 한쪽만 바뀌면 여기서 빨갛게 된다.
const strip = (css: string) => css.replace(/\/\*[\s\S]*?\*\//g, "");
function lightRootValues(css: string): Map<string, string> {
  const body = strip(css);
  const root = body.match(/(?:^|\n):root\s*\{([\s\S]*?)\n\}/);
  if (!root) throw new Error(":root 블록이 없다");
  const values = new Map<string, string>();
  for (const match of root[1].matchAll(/(--[a-z0-9-]+)\s*:\s*([^;]+);/g)) values.set(match[1], match[2].trim().replace(/\s+/g, " "));
  return values;
}

const publicTokens = lightRootValues(readFileSync("src/app/tokens.css", "utf8"));
const adminPalette = lightRootValues(readFileSync(path.resolve("../packages/kor-travel-transport-admin/frontend/app/transport-palette.css"), "utf8"));
const adminGlobals = lightRootValues(readFileSync(path.resolve("../packages/kor-travel-transport-admin/frontend/app/globals.css"), "utf8"));

describe("공개 parking-radar 토큰 = transport 관리자 토큰", () => {
  const colorNames = [
    "--surface-page", "--surface-subtle", "--surface-muted", "--card", "--text-primary", "--text-secondary", "--text-tertiary",
    "--control-line", "--brand", "--brand-hover", "--brand-tint", "--brand-foreground", "--success", "--success-tint",
    "--warning", "--warning-tint", "--destructive", "--destructive-tint", "--focus",
  ];
  test.each(colorNames)("%s 값이 transport-palette.css와 같다", (name) => {
    expect(adminPalette.get(name)).toBeDefined();
    expect(publicTokens.get(name)).toBe(adminPalette.get(name));
  });

  test.each(["--radius-control", "--radius-panel", "--control-h"])("%s 값이 관리자 globals.css와 같다", (name) => {
    const strip0 = (value?: string) => value?.replace(/^0\./, ".");
    expect(adminGlobals.get(name)).toBeDefined();
    expect(strip0(publicTokens.get(name))).toBe(strip0(adminGlobals.get(name)));
  });

  test("카드 그림자를 쓰지 않는다(관리자는 hairline만)", () => {
    expect(publicTokens.get("--shadow-card")).toBe("none");
  });
});
