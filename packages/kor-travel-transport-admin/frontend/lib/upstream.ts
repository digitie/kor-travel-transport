import { isAllowedTransportPath } from "./transport";

// 공개 API gateway의 proxy_read_timeout(30초)과 일치시킨다. 저장된 7일 이상
// 집계가 정상적으로 10초를 넘을 수 있으므로 관리 UI만 먼저 502로 바꾸면 안 된다.
const TIMEOUT_MS = 30_000;
export function transportTimeoutMs(target: URL) {
  // 전체 공개 역 안내는 최초 1회 32페이지를 검산해 저장한다. 다른 요청의 상한은 유지한다.
  return target.pathname === "/v1/transport/rail/general/guide" ? 60_000 : TIMEOUT_MS;
}

export function transportUpstreamUrl(path: string[], search: URLSearchParams) {
  if (!isAllowedTransportPath(path)) return null;
  const base = (process.env.TRANSPORT_API_INTERNAL_URL ?? "http://127.0.0.1:12302").replace(/\/$/, "");
  const target = new URL(`${base}/v1/${path.join("/")}`);
  search.forEach((value, key) => target.searchParams.append(key, value));
  return target;
}

/** 상한 시간은 응답 헤더까지만 적용한다(본문은 그대로 스트리밍). 호출자가 준 `init.signal`(브라우저 요청의
 * `request.signal`)은 본문까지 전체 수명 동안 함께 걸어, 브라우저가 조회를 취소하면 upstream 연결도 끊는다. */
export async function fetchNoStore(target: URL, init: RequestInit = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), transportTimeoutMs(target));
  const signal = init.signal ? AbortSignal.any([init.signal, controller.signal]) : controller.signal;
  try { return await fetch(target, { ...init, cache: "no-store", signal }); }
  finally { clearTimeout(timeout); }
}

export async function boundedText(request: Request, maxBytes = 1_048_576) {
  const declared = Number(request.headers.get("content-length") ?? 0);
  if (Number.isFinite(declared) && declared > maxBytes) return null;
  const text = await request.text();
  return new TextEncoder().encode(text).byteLength <= maxBytes ? text : null;
}
