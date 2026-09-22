import { isAllowedTransportPath } from "./transport";

// 공개 API gateway의 proxy_read_timeout(30초)과 일치시킨다. 저장된 7일 이상
// 집계가 정상적으로 10초를 넘을 수 있으므로 관리 UI만 먼저 502로 바꾸면 안 된다.
const TIMEOUT_MS = 30_000;

export function transportUpstreamUrl(path: string[], search: URLSearchParams) {
  if (!isAllowedTransportPath(path)) return null;
  const base = (process.env.TRANSPORT_API_INTERNAL_URL ?? "http://127.0.0.1:14001").replace(/\/$/, "");
  const target = new URL(`${base}/v1/${path.join("/")}`);
  search.forEach((value, key) => target.searchParams.append(key, value));
  return target;
}

export async function fetchNoStore(target: URL, init: RequestInit = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try { return await fetch(target, { ...init, cache: "no-store", signal: controller.signal }); }
  finally { clearTimeout(timeout); }
}

export async function boundedText(request: Request, maxBytes = 1_048_576) {
  const declared = Number(request.headers.get("content-length") ?? 0);
  if (Number.isFinite(declared) && declared > maxBytes) return null;
  const text = await request.text();
  return new TextEncoder().encode(text).byteLength <= maxBytes ? text : null;
}
