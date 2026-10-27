import { NextRequest, NextResponse } from "next/server";
import { hasAdminSession } from "@/lib/auth";
import { isAllowedOrigin } from "@/lib/origin";
import { boundedText, fetchNoStore } from "@/lib/upstream";

const headers = { "cache-control": "no-store, private" };
const denied = (detail: string, status: number) => NextResponse.json({ detail }, { status, headers });
async function forward(method: "GET" | "POST", body?: string) {
  const token = process.env.TRANSPORT_ADMIN_WRITE_TOKEN ?? "";
  if (token.length < 32) return denied("역 매핑 관리 기능이 설정되지 않았습니다.", 503);
  try {
    const target = new URL("/v1/transport/admin/rail-station-mappings/automatic", process.env.TRANSPORT_API_INTERNAL_URL ?? "http://127.0.0.1:12302");
    const response = await fetchNoStore(target, { method, headers: { "x-transport-admin-token": token, ...(body ? { "content-type": "application/json" } : {}) }, ...(body ? { body } : {}) });
    return new NextResponse(response.body, { status: response.status, headers: { ...headers, "content-type": response.headers.get("content-type") ?? "application/json" } });
  } catch { return denied("역 매핑 API에 연결하지 못했습니다.", 502); }
}
export async function GET(request: NextRequest) {
  if (!(await hasAdminSession(request))) return denied("로그인이 필요합니다.", 401);
  return forward("GET");
}
export async function POST(request: NextRequest) {
  if (!(await hasAdminSession(request))) return denied("로그인이 필요합니다.", 401);
  if (!isAllowedOrigin(request)) return denied("허용되지 않은 요청입니다.", 403);
  if (!request.headers.get("content-type")?.startsWith("application/json")) return denied("JSON 요청만 허용합니다.", 415);
  const raw = await boundedText(request, 2048);
  if (raw === null) return denied("요청 본문이 너무 큽니다.", 413);
  let value: unknown;
  try { value = JSON.parse(raw || "null"); } catch { return denied("JSON 본문을 확인해 주세요.", 422); }
  if (!value || typeof value !== "object" || Array.isArray(value)) return denied("미리보기 revision을 확인해 주세요.", 422);
  const body = value as Record<string, unknown>;
  if (Object.keys(body).length !== 2 || ["expected_revision", "candidate_revision"].some(key => typeof body[key] !== "string" || !/^[0-9a-f]{64}$/.test(body[key] as string))) return denied("미리보기 revision을 확인해 주세요.", 422);
  return forward("POST", JSON.stringify({ expected_revision: body.expected_revision, candidate_revision: body.candidate_revision }));
}
