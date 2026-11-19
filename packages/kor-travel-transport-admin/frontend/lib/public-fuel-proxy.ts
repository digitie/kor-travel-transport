/** 공개 연산은 고정 경로만 만든다. 요청의 origin·cookie·인증 정보는 사용하지 않는다. */
export function publicFuelUpstreamUrl(path: string[], search: URLSearchParams): URL | null {
  const operation = path.join("/");
  if (!/^(places|stations|statistics|health|stations\/[1-9][0-9]*\/price-history)$/.test(operation)) return null;
  const endpoint = operation === "health" ? "/health" : `/v1/transport/fuel/${operation}`;
  const target = new URL(endpoint, process.env.BACKEND_INTERNAL_URL ?? "http://127.0.0.1:12307");
  if (!["http:", "https:"].includes(target.protocol) || target.username || target.password) return null;
  target.search = search.toString();
  return target;
}
