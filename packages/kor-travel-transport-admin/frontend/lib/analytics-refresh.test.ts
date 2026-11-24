import { describe, expect, test } from "vitest";
import { analyticsRefreshView, type AnalyticsRefreshStatus } from "./analytics-refresh";

const base: AnalyticsRefreshStatus = {
  status: "ok", alerting: false, generated_at: "2026-11-24T05:00:00Z", pending_since: null, pending_seconds: null,
  warn_after_seconds: 900, fallback_after_seconds: 2400,
};
const clock = (iso: string | null) => (iso ? iso.slice(11, 16) : "—");

describe("analyticsRefreshView", () => {
  test("정상·갱신 대기 중은 경보가 아니다", () => {
    expect(analyticsRefreshView(base, clock)).toEqual({ label: "정상", tone: "success", alerting: false, detail: "05:00 생성" });
    expect(analyticsRefreshView({ ...base, pending_since: "2026-11-24T05:01:00Z", pending_seconds: 330 }, clock)?.detail)
      .toBe("05:00 생성 · 새 적재 5분째 갱신 대기");
  });

  test("첫 사전집계를 기다리는 동안(생성 시각 없음)은 경보가 아니고 그렇게 말한다", () => {
    expect(analyticsRefreshView({ ...base, generated_at: null, pending_since: "2026-11-24T05:01:00Z", pending_seconds: 420 }, clock))
      .toEqual({ label: "첫 갱신 대기", tone: "neutral", alerting: false, detail: "첫 관측 뒤 7분째 사전집계를 기다립니다." });
  });

  test("지연·원본 계산·없음은 경보 톤으로 원인과 남은 여유를 알린다", () => {
    const delayed = analyticsRefreshView({ ...base, status: "delayed", alerting: true, pending_seconds: 1260 }, clock);
    expect(delayed).toMatchObject({ label: "갱신 지연", tone: "warning", alerting: true });
    expect(delayed?.detail).toContain("21분째");
    expect(delayed?.detail).toContain("40분");
    expect(analyticsRefreshView({ ...base, status: "stale", alerting: true, pending_seconds: 3000 }, clock))
      .toMatchObject({ label: "원본 계산 중", tone: "destructive", alerting: true });
    expect(analyticsRefreshView({ ...base, status: "missing", alerting: true, generated_at: null }, clock))
      .toMatchObject({ tone: "destructive", alerting: true });
  });

  test("사전집계가 2시간 넘게 갱신되지 않으면(미반영 적재 없음) 생성 시각 나이로 알린다", () => {
    const stale = analyticsRefreshView({ ...base, status: "stale", alerting: true, pending_seconds: null, generated_age_seconds: 7500 }, clock);
    expect(stale).toMatchObject({ label: "원본 계산 중", tone: "destructive" });
    expect(stale?.detail).toBe("사전집계가 125분째(05:00 생성) 갱신되지 않아 대시보드가 원본에서 계산합니다.");
  });

  test("관측 없음은 경보가 아니고, 값이 없으면(이전 backend) 표시하지 않는다", () => {
    expect(analyticsRefreshView({ ...base, status: "empty", generated_at: null }, clock)).toMatchObject({ alerting: false });
    expect(analyticsRefreshView(null, clock)).toBeNull();
    expect(analyticsRefreshView(undefined, clock)).toBeNull();
  });
});
