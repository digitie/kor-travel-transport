export function sanitizeLocalPath(value: unknown, fallback = "/"): string {
  if (typeof value !== "string") return fallback;
  const candidate = value.trim();
  if (!candidate || candidate.length > 500 || !candidate.startsWith("/") || candidate.startsWith("//") || candidate.includes("\\")) {
    return fallback;
  }
  try {
    const parsed = new URL(candidate, "http://transport.local");
    return parsed.origin === "http://transport.local" ? `${parsed.pathname}${parsed.search}${parsed.hash}` : fallback;
  } catch {
    return fallback;
  }
}
