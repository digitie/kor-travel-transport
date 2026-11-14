export function sanitizeLocalPath(value: unknown, fallback = "/"): string {
  if (typeof value !== "string") return fallback;
  const candidate = value.trim();
  if (!candidate || candidate.length > 500 || !candidate.startsWith("/") || candidate.startsWith("//") || candidate.includes("\\")) {
    return fallback;
  }
  try {
    const parsed = new URL(candidate, "http://transport.local");
    // "/.//evil.com"처럼 정규화 뒤 "//"로 시작하면 브라우저가 외부 호스트로 해석한다.
    if (parsed.origin !== "http://transport.local" || parsed.pathname.startsWith("//")) return fallback;
    return `${parsed.pathname}${parsed.search}${parsed.hash}`;
  } catch {
    return fallback;
  }
}
