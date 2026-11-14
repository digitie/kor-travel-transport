"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { getRunFailure, type DagsterRunFailureDetail } from "@/lib/dagster";

/** 목록 진입 시 로그를 읽지 않고 선택한 실패 한 건만 조회한다. */
export function CollectionRunFailure({ runId, expanded: selected, onExpandedChange }: { runId: string; expanded?: boolean; onExpandedChange?: (value: boolean) => void }) {
  const [localExpanded, setLocalExpanded] = useState(false);
  const expanded = selected ?? localExpanded;
  const [revision, setRevision] = useState(0);
  const [detail, setDetail] = useState<{ runId: string; loading: boolean; result?: DagsterRunFailureDetail; error?: string }>({ runId, loading: false });
  useEffect(() => {
    if (!expanded) return;
    const controller = new AbortController();
    getRunFailure(runId, controller.signal)
      .then(result => { if (!controller.signal.aborted) setDetail({ runId, loading: false, result }); })
      .catch(() => { if (!controller.signal.aborted) setDetail({ runId, loading: false, error: "실패 상세를 읽지 못했습니다. 다시 조회해 주세요." }); });
    return () => controller.abort();
  }, [expanded, revision, runId]);
  return <div className="flex min-w-0 flex-col items-start gap-2">
    <Button aria-expanded={expanded} onClick={() => { if (!expanded) setDetail({ runId, loading: true }); if (onExpandedChange) onExpandedChange(!expanded); else setLocalExpanded(!expanded); }} size="sm" type="button" variant="ghost">{expanded ? "실패 상세 접기" : "실패 원인·진단 보기"}</Button>
    {expanded ? <div aria-label="선택한 수집 실패 상세" className="flex max-w-full flex-col gap-2 text-xs">
      {detail.runId !== runId || detail.loading ? <p role="status">실패 단계와 원인을 확인하는 중…</p> : detail.error ? <>
        <p role="alert">{detail.error}</p><Button onClick={() => { setDetail({ runId, loading: true }); setRevision(value => value + 1); }} size="sm" type="button" variant="outline">상세 다시 조회</Button>
      </> : <>
        <p className="break-words whitespace-pre-wrap">{detail.result?.message ?? "확인할 수 있는 실패 이벤트가 없습니다."}</p>
        {detail.result && !detail.result.complete ? <p>조회 상한에 도달했습니다. 전체 로그는 Dagster 실행 상세에서 확인하세요.</p> : null}
      </>}
    </div> : null}
  </div>;
}
