/** 요청·응답 본문을 상한 내에서만 읽는다. 헤더 수신 후 멈춘 stream도 회수한다. */
export async function readBounded(body: ReadableStream<Uint8Array> | null, maxBytes: number, timeoutMs = 10_000): Promise<string> {
  if (!body) return "";
  const reader = body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const expired = new Promise<never>((_, reject) => { timer = setTimeout(() => reject(new Error("본문 조회 시간 초과")), timeoutMs); });
  try {
    for (;;) {
      const { done, value } = await Promise.race([reader.read(), expired]);
      if (done) break;
      total += value.byteLength;
      if (total > maxBytes) throw new Error("본문 크기 초과");
      chunks.push(value);
    }
    const joined = new Uint8Array(total);
    let offset = 0;
    for (const chunk of chunks) { joined.set(chunk, offset); offset += chunk.length; }
    return new TextDecoder().decode(joined);
  } catch (error) {
    void reader.cancel().catch(() => undefined);
    throw error;
  } finally { clearTimeout(timer); }
}
