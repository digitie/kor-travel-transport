import { NextRequest, NextResponse } from "next/server";

import { hasAdminSession } from "@/lib/auth";
import { isAllowedOrigin } from "@/lib/origin";
import { boundedText, fetchNoStore } from "@/lib/upstream";

const API_PATH = "/v1/transport/admin/rail-station-mappings";

function deniedConfiguration() {
  return NextResponse.json({ detail: "역 매핑 관리 기능이 설정되지 않았습니다." }, { status: 503 });
}

async function forward(method: "GET" | "POST", body?: string) {
  const token = process.env.TRANSPORT_ADMIN_WRITE_TOKEN ?? "";
  if (token.length < 32) return deniedConfiguration();
  try {
    const target = new URL(API_PATH, process.env.TRANSPORT_API_INTERNAL_URL ?? "http://127.0.0.1:14001");
    const response = await fetchNoStore(target, {
      method,
      headers: { "x-transport-admin-token": token, ...(body ? { "content-type": "application/json" } : {}) },
      ...(body ? { body } : {}),
    });
    return new NextResponse(response.body, {
      status: response.status,
      headers: { "cache-control": "no-store, private", "content-type": response.headers.get("content-type") ?? "application/json" },
    });
  } catch {
    return NextResponse.json({ detail: "역 매핑 API에 연결하지 못했습니다." }, { status: 502, headers: { "cache-control": "no-store, private" } });
  }
}

export async function GET(request: NextRequest) {
  if (!(await hasAdminSession(request))) return NextResponse.json({ detail: "로그인이 필요합니다." }, { status: 401 });
  return forward("GET");
}

export async function POST(request: NextRequest) {
  if (!(await hasAdminSession(request))) return NextResponse.json({ detail: "로그인이 필요합니다." }, { status: 401 });
  if (!isAllowedOrigin(request)) return NextResponse.json({ detail: "허용되지 않은 요청입니다." }, { status: 403 });
  if (!request.headers.get("content-type")?.startsWith("application/json")) {
    return NextResponse.json({ detail: "JSON 요청만 허용합니다." }, { status: 415 });
  }
  const raw = await boundedText(request, 512 * 1024);
  if (raw === null) return NextResponse.json({ detail: "요청 본문이 너무 큽니다." }, { status: 413 });
  let payload: unknown;
  try { payload = JSON.parse(raw || "null"); }
  catch { return NextResponse.json({ detail: "JSON 본문을 확인해 주세요." }, { status: 422 }); }
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return NextResponse.json({ detail: "매핑 JSON 객체가 필요합니다." }, { status: 422 });
  }
  const body = payload as Record<string, unknown>;
  if (typeof body.expected_revision !== "string" || !/^[0-9a-f]{64}$/.test(body.expected_revision) ||
      !Array.isArray(body.mappings) || body.mappings.length > 1108 || body.mappings.some((item) => {
        if (!item || typeof item !== "object" || Array.isArray(item)) return true;
        const mapping = item as Record<string, unknown>;
        return ["operator_code", "line_code", "station_code", "rail_station_identity_key"].some((key) =>
          typeof mapping[key] !== "string" || (mapping[key] as string).length === 0 || (mapping[key] as string).length > 400,
        ) || (mapping.note !== undefined && (typeof mapping.note !== "string" || mapping.note.length > 500));
      })) {
    return NextResponse.json({ detail: "역 코드와 매핑 형식을 확인해 주세요." }, { status: 422 });
  }
  return forward("POST", JSON.stringify({ expected_revision: body.expected_revision, mappings: body.mappings }));
}
