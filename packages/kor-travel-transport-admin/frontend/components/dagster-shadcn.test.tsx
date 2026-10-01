import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, expect, test, vi } from "vitest";
import { DagsterOperations, DagsterTables } from "./dagster-operations";
import type { DagsterOverview } from "@/lib/dagster";

afterEach(() => vi.useRealTimers());

const snapshot: DagsterOverview = {
  checkedAt: "2026-09-28T03:20:00Z",
  runs: [{
    runId: "run/with space",
    status: "STARTED",
    jobName: "airport_collection_job",
    startTime: Date.parse("2026-09-28T03:00:00Z") / 1000,
    endTime: null,
  }],
  schedules: [{
    name: "airport_schedule",
    cronSchedule: "*/5 * * * *",
    pipelineName: "airport_collection_job",
    scheduleState: { status: "RUNNING" },
  }],
};

test("실행 표와 스케줄 표의 제목·키보드 진입·링크 의미를 유지한다", () => {
  const html = renderToStaticMarkup(<DagsterTables snapshot={snapshot} />);

  expect(html).toContain("<h2>최근 실행</h2>");
  expect(html).toContain("<h2>스케줄</h2>");
  expect(html).toMatch(/role="region" aria-label="최근 Dagster 실행 표" tabindex="0"/);
  expect(html).toMatch(/role="region" aria-label="Dagster 스케줄 표" tabindex="0"/);
  expect(html.match(/scope="col"/g)).toHaveLength(8);
  expect(html).toMatch(/<button[^>]*aria-expanded="false"/);
  expect(html).toContain("5분마다");
  const link = html.match(/<a\b[^>]*>/)?.[0];
  expect(link).toContain('href="https://dagster.digitie.mywire.org/runs/run%2Fwith%20space"');
  expect(link).toContain('target="_blank"');
  expect(link).toContain('rel="noreferrer"');
  expect(link).not.toContain('role="button"');
});

test("경과 시간과 정체 판정은 현재 시각 대신 스냅샷 확인 시각에 고정된다", () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-09-29T03:20:00Z"));
  const html = renderToStaticMarkup(<DagsterTables snapshot={snapshot} />);

  expect(html).toContain("20분 경과 · 정체 의심");
  expect(html).toContain('data-variant="warning"');
  expect(html).toContain('data-variant="success"');
  const withoutCheckTime = renderToStaticMarkup(<DagsterTables snapshot={{ ...snapshot, checkedAt: undefined }} />);
  expect(withoutCheckTime).not.toContain("분 경과");
  expect(withoutCheckTime).not.toContain("정체 의심");
});

test("빈 조회 결과와 실패한 실행을 각각 표시한다", () => {
  const empty = renderToStaticMarkup(<DagsterTables snapshot={{ runs: [], schedules: [] }} />);
  expect(empty).toContain("최근 Dagster 실행이 없습니다.");
  expect(empty).toContain("등록된 스케줄이 없습니다.");
  expect(empty).not.toContain("<table");

  const failed = renderToStaticMarkup(<DagsterTables snapshot={{
    ...snapshot,
    runs: [{ ...snapshot.runs[0], status: "FAILURE", endTime: snapshot.runs[0].startTime! + 60 }],
  }} />);
  expect(failed).toContain("실패 원인은 실행 상세에서 확인하세요.");
  expect(failed).toContain('data-variant="destructive"');
  expect(failed).toContain("1분 경과");
  expect(failed).not.toContain("정체 의심");
});

test("최초 로딩은 새로고침을 막고 상태 안내와 자리표시자를 제공한다", () => {
  const html = renderToStaticMarkup(<DagsterOperations />);
  expect(html).toContain('aria-busy="true"');
  expect(html).toMatch(/<button[^>]*disabled=""/);
  expect(html).toContain("확인 중…");
  expect(html).toContain('data-slot="spinner"');
  expect(html).toContain('data-slot="skeleton"');
  expect(html).toContain("실행 기록·스케줄을 불러오는 중…");
  expect(html).not.toContain("최근 Dagster 실행이 없습니다.");
  expect(html.match(/<a\b[^>]*>/)?.[0]).not.toContain('role="button"');
});
