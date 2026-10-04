import { NextRequest, NextResponse } from "next/server";

import { hasAdminSession } from "@/lib/auth";
import { scopedDagsterRequest } from "@/lib/dagster-scope";
import { isAllowedOrigin } from "@/lib/origin";
import { readBounded } from "@/lib/bounded-stream";

export async function POST(request: NextRequest) {
  if (!(await hasAdminSession(request))) return NextResponse.json({ errors: [{ message: "로그인이 필요합니다." }] }, { status: 401 });
  if (!isAllowedOrigin(request)) return NextResponse.json({ errors: [{ message: "허용되지 않은 요청입니다." }] }, { status: 403 });
  let body: string;
  try { body = await readBounded(request.body, 4096); }
  catch { return NextResponse.json({ errors: [{ message: "Dagster 요청을 읽지 못했습니다." }] }, { status: 413 }); }
  // 이름 붙은 작업(lib/dagster-scope.ts)만 지나간다. query 본문과 이 location의 범위는 여기서 채운다 — 공용
  // webserver에 브라우저의 GraphQL 문서를 그대로 넘기면 다른 프로젝트의 run·schedule을 보고 바꿀 수 있다.
  let parsed: unknown = null;
  try { parsed = JSON.parse(body); } catch { parsed = null; }
  const scoped = scopedDagsterRequest(parsed);
  if (!scoped.ok) return NextResponse.json({ errors: [{ message: scoped.message }] }, { status: 400, headers: { "cache-control": "no-store, private" } });
  try {
    const base = (process.env.TRANSPORT_DAGSTER_INTERNAL_URL ?? "http://127.0.0.1:11002").replace(/\/$/, "");
    const response = await fetch(new URL(`${base}/graphql`), { method: "POST", headers: { accept: "application/json", "content-type": "application/json" }, body: scoped.body, cache: "no-store", signal: AbortSignal.timeout(10_000) });
    const result = await readBounded(response.body, 4_194_304);
    return new NextResponse(result, { status: response.status, headers: { "cache-control": "no-store, private", "content-type": "application/json" } });
  } catch { return NextResponse.json({ errors: [{ message: "Dagster에 연결하지 못했습니다." }] }, { status: 502 }); }
}
