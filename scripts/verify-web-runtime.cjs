// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Youn-sok Choi (digitie)
"use strict";

// 실제 새 이미지 안에서 USER node로 실행한다. 서버·로그인·외부 요청은 시작하지 않는다.
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { createRequire } = require("node:module");
const { execFileSync } = require("node:child_process");

function check(condition, code) {
  if (!condition) {
    const error = new Error(code);
    error.code = code;
    throw error;
  }
}

function file(root, relative) {
  const result = path.resolve(root, relative);
  check(result.startsWith(path.resolve(root) + path.sep), "RUNTIME_PATH");
  fs.accessSync(result, fs.constants.R_OK);
  return result;
}

function json(root, relative) {
  return JSON.parse(fs.readFileSync(file(root, relative), "utf8"));
}

function hash(filename) {
  return crypto.createHash("sha256").update(fs.readFileSync(filename)).digest("hex");
}

function writable(directory) {
  fs.accessSync(directory, fs.constants.R_OK | fs.constants.W_OK | fs.constants.X_OK);
  const filename = path.join(directory, ".runtime-probe-" + crypto.randomUUID());
  const value = crypto.randomBytes(16);
  fs.writeFileSync(filename, value, { flag: "wx", mode: 0o600 });
  try {
    check(fs.readFileSync(filename).equals(value), "RUNTIME_CACHE_WRITE");
  } finally {
    fs.unlinkSync(filename);
  }
}

function inspectFiles(root, role) {
  check(["frontend", "transport-admin-web"].includes(role), "RUNTIME_ROLE");
  const pkg = json(root, "package.json");
  const request = createRequire(path.join(root, "package.json"));
  const next = JSON.parse(fs.readFileSync(request.resolve("next/package.json"), "utf8"));
  check(next.version === pkg.dependencies.next, "RUNTIME_NEXT_VERSION");
  const cli = request.resolve("next/dist/bin/next");
  fs.accessSync(cli, fs.constants.R_OK | fs.constants.X_OK);
  const bin = file(root, "node_modules/.bin/next");
  fs.accessSync(bin, fs.constants.X_OK);
  check(fs.realpathSync(bin) === fs.realpathSync(cli), "RUNTIME_NEXT_BIN");
  check(pkg.scripts.start.startsWith("next start"), "RUNTIME_START");
  file(root, "package-lock.json");
  file(root, ".npmrc");
  file(root, "next.config.ts");
  file(root, "tsconfig.json");
  check(fs.readFileSync(file(root, ".next/BUILD_ID"), "utf8").trim().length > 0, "RUNTIME_BUILD_ID");
  check(fs.statSync(file(root, "public")).isDirectory(), "RUNTIME_PUBLIC");
  check(fs.statSync(file(root, ".next/static")).isDirectory(), "RUNTIME_STATIC");
  json(root, ".next/routes-manifest.json");
  json(root, ".next/required-server-files.json");
  const routes = json(root, ".next/server/app-paths-manifest.json");
  check(Object.keys(routes).length > 0, "RUNTIME_ROUTES");
  for (const entry of Object.values(routes)) {
    check(typeof entry === "string" && !entry.split("/").includes(".."), "RUNTIME_ROUTE_PATH");
    file(root, ".next/server/" + entry);
  }
  // 이번 변경은 설치 profile을 prune하지 않는다. 이 검사는 최소 의존성 집합의 증명은 아니다.
  request.resolve("typescript");
  const workers = {};
  if (role === "transport-admin-web") {
    file(root, "proxy.ts");
    const parking = request.resolve("@kor-travel/parking-ui/api");
    fs.accessSync(parking, fs.constants.R_OK);
    for (const name of ["maplibre-gl-worker.mjs", "maplibre-gl-shared.mjs"]) {
      const original = path.join(path.dirname(request.resolve("maplibre-gl/package.json")), "dist", name);
      const served = file(root, "public/maplibre/" + name);
      check(hash(served) === hash(original), "RUNTIME_WORKER_BYTES");
      workers[name] = hash(served);
    }
  }
  writable(path.join(root, ".next/cache"));
  return { packageName: pkg.name, next: next.version, compiledRoutes: Object.keys(routes).length, workers };
}

function verifyIdentity(identity, env, pkg, expectedRevision, role) {
  check(["frontend", "transport-admin-web"].includes(role), "RUNTIME_ROLE");
  check(/^[a-f0-9]{40}$/.test(expectedRevision), "RUNTIME_REVISION");
  check(identity.uid === 1000 && identity.gid === 1000, "RUNTIME_USER");
  check(env.NODE_ENV === "production", "RUNTIME_NODE_ENV");
  check(env.HOME === "/home/node" && env.NPM_CONFIG_CACHE === "/home/node/.npm" &&
    env.XDG_CACHE_HOME === "/home/node/.cache", "RUNTIME_HOME");
  check(identity.node === pkg.engines.node && identity.npm === pkg.engines.npm, "RUNTIME_TOOLCHAIN");
  const name = role === "frontend" ? "RELEASE_SHA" : "TRANSPORT_ADMIN_RELEASE_SHA";
  check(env[name] === expectedRevision, "RUNTIME_RELEASE");
}

async function main(argv) {
  check(argv.length === 2, "RUNTIME_ARGUMENTS");
  const [role, expectedRevision] = argv;
  const root = "/app";
  const pkg = json(root, "package.json");
  const identity = {
    uid: process.getuid(),
    gid: process.getgid(),
    node: process.versions.node,
    npm: execFileSync("npm", ["--version"], { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }).trim(),
  };
  verifyIdentity(identity, process.env, pkg, expectedRevision, role);
  const facts = inspectFiles(root, role);
  writable(process.env.NPM_CONFIG_CACHE);
  writable(process.env.XDG_CACHE_HOME);
  // 실제 Next loader/native binding으로 TypeScript config를 읽는다. 코드나 ENV 원문은 출력하지 않는다.
  const request = createRequire(path.join(root, "package.json"));
  const loadConfig = request("next/dist/server/config").default;
  const phase = request("next/constants").PHASE_PRODUCTION_SERVER;
  const config = await loadConfig(phase, root);
  check(config.reactStrictMode === true, "RUNTIME_NEXT_CONFIG");
  if (role === "transport-admin-web") {
    check(config.transpilePackages.includes("@kor-travel/parking-ui"), "RUNTIME_PARKING_CONFIG");
  }
  console.log(JSON.stringify({ status: "PASS", scope: "image-files-config-cache-only", role,
    ...identity, ...facts, releaseMatches: true, actualHTTPBrowserAuthClaimed: false }));
}

module.exports = { inspectFiles, verifyIdentity };
if (require.main === module) {
  main(process.argv.slice(2)).catch((error) => {
    // 입력·config·ENV·module 오류 원문에는 키가 포함될 수 있으므로 고정 코드만 남긴다.
    const code = typeof error.code === "string" && /^RUNTIME_[A-Z_]+$/.test(error.code) ? error.code : "RUNTIME_PROBE_FAILED";
    console.error(JSON.stringify({ status: "FAIL", code }));
    process.exitCode = 1;
  });
}
