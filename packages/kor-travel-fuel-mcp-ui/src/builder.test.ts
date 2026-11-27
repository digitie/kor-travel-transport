// @ts-expect-error 검사용 Node ESM은 별도 선언 파일을 만들지 않는다.
import { projectNodeBuilder } from "../project-node-builder.mjs";
import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
describe("혼합 Dockerfile의 Node 정책 범위",()=>{
 const source=readFileSync(new URL("../../../backend/Dockerfile",import.meta.url),"utf8");
 it("실제 Node RUN 전체를 보존하고 Python runtime을 제외한다",()=>{const s=projectNodeBuilder(source);expect(s).toContain("npm ci --engine-strict");expect(s).toContain("npm run type-check && npm run build");expect(s).not.toContain("python -m venv");});
 it("추가 Node stage와 범위 밖 npm을 거부한다",()=>{expect(()=>projectNodeBuilder(source+"\nFROM node:26 AS extra\nRUN npm test\n")).toThrow();expect(()=>projectNodeBuilder(source+"\nRUN npm install bad\n")).toThrow();});
});
