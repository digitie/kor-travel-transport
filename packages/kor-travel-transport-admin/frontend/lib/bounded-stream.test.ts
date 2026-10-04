import { expect, test } from "vitest";
import { readBounded } from "./bounded-stream";

test("Content-Length 없는 본문도 상한을 넘으면 읽기를 중단한다", async () => {
  let canceled = false;
  const stream = new ReadableStream<Uint8Array>({ start(controller) { controller.enqueue(new Uint8Array(4097)); }, cancel() { canceled = true; } });
  await expect(readBounded(stream, 4096)).rejects.toThrow("크기 초과");
  expect(canceled).toBe(true);
});

test("헤더 수신 후 멈춘 stream을 시간 제한으로 회수한다", async () => {
  let canceled = false;
  const stream = new ReadableStream<Uint8Array>({ cancel() { canceled = true; } });
  await expect(readBounded(stream, 4096, 20)).rejects.toThrow("시간 초과");
  expect(canceled).toBe(true);
});
