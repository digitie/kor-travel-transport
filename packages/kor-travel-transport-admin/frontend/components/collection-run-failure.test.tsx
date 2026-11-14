// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { CollectionRunFailure } from "./collection-run-failure";
import { getRunFailure } from "@/lib/dagster";

vi.mock("@/lib/dagster", () => ({ getRunFailure: vi.fn() }));
const failure = vi.mocked(getRunFailure);
afterEach(() => { cleanup(); vi.clearAllMocks(); });

test("목록만 보면 조회하지 않고 선택한 실패의 단계·수치를 표시한다", async () => {
  failure.mockResolvedValue({ message: "원인: 불량 행\n수신 행 수: 8352\n불량 행 수: 1", complete: true });
  render(<CollectionRunFailure runId="run-a" />);
  expect(failure).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "실패 원인·진단 보기" }));
  expect(await screen.findByText(/수신 행 수: 8352/)).toBeTruthy();
  expect(failure).toHaveBeenCalledTimes(1);
  expect(failure.mock.calls[0][0]).toBe("run-a");
  expect(screen.getByRole("button", { name: "실패 상세 접기" }).getAttribute("aria-expanded")).toBe("true");
});

test("상세를 접거나 실행을 바꾸면 이전 조회를 취소하고 늦은 응답을 표시하지 않는다", async () => {
  let resolve!: (value: { message: string; complete: boolean }) => void;
  failure.mockImplementation(() => new Promise(done => { resolve = done; }));
  const { rerender } = render(<CollectionRunFailure runId="run-a" />);
  fireEvent.click(screen.getByRole("button", { name: "실패 원인·진단 보기" }));
  const signal = failure.mock.calls[0][1]!;
  fireEvent.click(screen.getByRole("button", { name: "실패 상세 접기" }));
  expect(signal.aborted).toBe(true);
  resolve({ message: "이전 실행의 응답", complete: true });
  rerender(<CollectionRunFailure runId="run-b" />);
  await waitFor(() => expect(screen.queryByText("이전 실행의 응답")).toBeNull());
});

test("상세 조회 실패는 재시도할 수 있고 조회 상한은 숨기지 않는다", async () => {
  failure.mockRejectedValueOnce(new Error("upstream"));
  failure.mockResolvedValueOnce({ message: "확인된 부분 원인", complete: false });
  render(<CollectionRunFailure runId="run-a" />);
  fireEvent.click(screen.getByRole("button", { name: "실패 원인·진단 보기" }));
  expect(await screen.findByRole("alert")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "상세 다시 조회" }));
  expect(await screen.findByText("확인된 부분 원인")).toBeTruthy();
  expect(screen.getByText(/조회 상한에 도달/)).toBeTruthy();
  expect(failure).toHaveBeenCalledTimes(2);
});

test("열린 상세에서 실행이 바뀌면 새 실행만 표시한다", async () => {
  const resolvers: Array<(value: { message: string; complete: boolean }) => void> = [];
  failure.mockImplementation(() => new Promise(done => { resolvers.push(done); }));
  const { rerender } = render(<CollectionRunFailure runId="run-a" />);
  fireEvent.click(screen.getByRole("button", { name: "실패 원인·진단 보기" }));
  const oldSignal = failure.mock.calls[0][1]!;
  rerender(<CollectionRunFailure runId="run-b" />);
  expect(oldSignal.aborted).toBe(true);
  expect(screen.getByRole("status")).toBeTruthy();
  resolvers[1]({ message: "새 실행 진단", complete: true });
  expect(await screen.findByText("새 실행 진단")).toBeTruthy();
  resolvers[0]({ message: "이전 실행 진단", complete: true });
  await waitFor(() => expect(screen.queryByText("이전 실행 진단")).toBeNull());
});

test("목록의 선택이 다른 실행으로 바뀌면 기존 상세 조회를 취소한다", () => {
  failure.mockImplementation(() => new Promise(() => {}));
  const { rerender } = render(<CollectionRunFailure runId="run-a" expanded onExpandedChange={() => {}} />);
  const signal = failure.mock.calls[0][1]!;
  rerender(<CollectionRunFailure runId="run-a" expanded={false} onExpandedChange={() => {}} />);
  expect(signal.aborted).toBe(true);
  expect(screen.queryByRole("status")).toBeNull();
});
