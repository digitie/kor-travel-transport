// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Youn-sok Choi (digitie)
"use strict";
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { inspectFiles, verifyIdentity } = require("./verify-web-runtime.cjs");

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "transport-runtime-contract-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const entries = {
    "package.json": JSON.stringify({ name: "fixture-only", dependencies: { next: "16.4.6" }, scripts: { start: "next start" } }),
    "package-lock.json": "{}",
    ".npmrc": "engine-strict=true",
    "next.config.ts": "export default { reactStrictMode: true };",
    "tsconfig.json": "{}",
    ".next/BUILD_ID": "fixture-build",
    ".next/routes-manifest.json": "{}",
    ".next/required-server-files.json": "{}",
    ".next/server/app-paths-manifest.json": JSON.stringify({ "/page": "app/page.js" }),
    ".next/server/app/page.js": "module.exports = {};",
    "node_modules/next/package.json": JSON.stringify({ name: "next", version: "16.4.6" }),
    "node_modules/next/dist/bin/next.js": "fixture-not-a-server",
    "node_modules/typescript/package.json": JSON.stringify({ main: "index.js" }),
    "node_modules/typescript/index.js": "",
    "node_modules/@kor-travel/parking-ui/package.json": JSON.stringify({ exports: { "./api": "./api.ts" } }),
    "node_modules/@kor-travel/parking-ui/api.ts": "export {};",
    "node_modules/maplibre-gl/package.json": JSON.stringify({ name: "maplibre-gl" }),
    "node_modules/maplibre-gl/dist/maplibre-gl-worker.mjs": "export const fixtureWorker = true;",
    "node_modules/maplibre-gl/dist/maplibre-gl-shared.mjs": "export const fixtureShared = true;",
    "public/maplibre/maplibre-gl-worker.mjs": "export const fixtureWorker = true;",
    "public/maplibre/maplibre-gl-shared.mjs": "export const fixtureShared = true;",
    "proxy.ts": "export {};",
  };
  for (const [name, content] of Object.entries(entries)) {
    const target = path.join(root, name);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.writeFileSync(target, content);
  }
  fs.chmodSync(path.join(root, "node_modules/next/dist/bin/next.js"), 0o755);
  fs.mkdirSync(path.join(root, "node_modules/.bin"), { recursive: true });
  fs.symlinkSync("../next/dist/bin/next.js", path.join(root, "node_modules/.bin/next"));
  for (const directory of [".next/static", ".next/cache"]) fs.mkdirSync(path.join(root, directory), { recursive: true });
  return root;
}

test("실제 fixture 파일을 읽고 cache를 쓰고 거둔다. 이미지 수용 결과가 아니다", (t) => {
  const root = fixture(t);
  const facts = inspectFiles(root, "transport-admin-web");
  assert.equal(facts.compiledRoutes, 1);
  assert.equal(Object.keys(facts.workers).length, 2);
  assert.deepEqual(fs.readdirSync(path.join(root, ".next/cache")), []);
});
for (const missing of ["proxy.ts", "next.config.ts", "node_modules/typescript/index.js",
  "node_modules/@kor-travel/parking-ui/api.ts", "public/maplibre/maplibre-gl-shared.mjs", ".next/server/app/page.js"]) {
  test("누락 runtime 파일 거절: " + missing, (t) => {
    const root = fixture(t);
    fs.unlinkSync(path.join(root, missing));
    assert.throws(() => inspectFiles(root, "transport-admin-web"));
  });
}
test("복사된 worker가 설치 산출물과 다르면 거절", (t) => {
  const root = fixture(t);
  fs.writeFileSync(path.join(root, "public/maplibre/maplibre-gl-worker.mjs"), "wrong");
  assert.throws(() => inspectFiles(root, "transport-admin-web"), { code: "RUNTIME_WORKER_BYTES" });
});
test("깨진 shared parking symlink는 성공 처리하지 않는다", (t) => {
  const root = fixture(t);
  const target = path.join(root, "node_modules/@kor-travel/parking-ui");
  fs.rmSync(target, { recursive: true });
  fs.symlinkSync("/missing-transport-runtime-fixture", target);
  assert.throws(() => inspectFiles(root, "transport-admin-web"));
});
test("non-root 사용자가 쓸 수 없는 cache는 거절", (t) => {
  const root = fixture(t);
  const cache = path.join(root, ".next/cache");
  fs.chmodSync(cache, 0o555);
  try {
    assert.throws(() => inspectFiles(root, "transport-admin-web"), { code: "EACCES" });
  } finally {
    fs.chmodSync(cache, 0o755);
  }
});
test("non-root 사용자가 읽을 수 없는 config는 거절", (t) => {
  const root = fixture(t);
  const config = path.join(root, "next.config.ts");
  fs.chmodSync(config, 0o000);
  try {
    assert.throws(() => inspectFiles(root, "transport-admin-web"), { code: "EACCES" });
  } finally {
    fs.chmodSync(config, 0o644);
  }
});
test("직접 Compose start에 필요한 next 실행 권한이 없으면 거절", (t) => {
  const root = fixture(t);
  fs.chmodSync(path.join(root, "node_modules/next/dist/bin/next.js"), 0o644);
  assert.throws(() => inspectFiles(root, "transport-admin-web"), { code: "EACCES" });
});
test("npm start의 .bin/next가 없으면 거절", (t) => {
  const root = fixture(t);
  fs.unlinkSync(path.join(root, "node_modules/.bin/next"));
  assert.throws(() => inspectFiles(root, "transport-admin-web"), { code: "ENOENT" });
});
const sha = "a".repeat(40);
const goodEnv = { NODE_ENV: "production", HOME: "/home/node", NPM_CONFIG_CACHE: "/home/node/.npm",
  XDG_CACHE_HOME: "/home/node/.cache", TRANSPORT_ADMIN_RELEASE_SHA: sha };
const goodIdentity = { uid: 1000, gid: 1000, node: "22.23.1", npm: "12.0.1" };
const pkg = { engines: { node: "22.23.1", npm: "12.0.1" } };
test("실제 관측 필드의 정상 profile 허용", () => {
  verifyIdentity(goodIdentity, goodEnv, pkg, sha, "transport-admin-web");
});
for (const [name, identity, env] of [
  ["root", { ...goodIdentity, uid: 0 }, goodEnv],
  ["root group", { ...goodIdentity, gid: 0 }, goodEnv],
  ["ambient npm", { ...goodIdentity, npm: "11.0.0" }, goodEnv],
  ["stale revision", goodIdentity, { ...goodEnv, TRANSPORT_ADMIN_RELEASE_SHA: "b".repeat(40) }],
  ["root HOME", goodIdentity, { ...goodEnv, HOME: "/root" }],
]) {
  test("잘못된 실제 profile 거절: " + name, () => {
    assert.throws(() => verifyIdentity(identity, env, pkg, sha, "transport-admin-web"));
  });
}
