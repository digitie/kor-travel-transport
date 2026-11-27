"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { statisticsGet } from "@/lib/public-fuel-statistics-client";
import {
  ALL_ROUTES, currentScope, describeStatisticsError, historyPath, kstDay, listScope, missingRegionName, parseStatisticsView, resolveRegion,
  statisticsPath, statisticsRetryDelay, statisticsSchema, statisticsViewQuery, trendSchema,
  type PublicFuelStatistics, type PublicFuelStatisticsView, type PublicFuelTrend, type StatisticsLoadError,
} from "@/lib/public-fuel-statistics";

/** 브라우저 쪽 요청 상한. BFF 30초 상한(그 뒤 502)보다 조금 길다. */
const REQUEST_TIMEOUT_MS = 40_000;
/** 같은 경로를 이 안에 다시 고르면 다시 받지 않는다. 오피넷 공개는 하루 3회, 도로공사는 매시라 1분 재사용은 안전하다. */
const REUSE_MS = 60_000;
/** 탭을 오래 두었다가 다시 보면(이보다 오래 전 응답) 현재 값과 추이를 다시 읽는다. */
const REFRESH_AFTER_MS = 10 * 60_000;

type Schema = { parse: (value: unknown) => unknown };
type Resource<T> = { key: string; data?: T; error?: StatisticsLoadError; retrying?: boolean; at?: number; last?: T };
/** `previous`: 마지막으로 받은 응답(다른 경로일 수 있다). 새 응답을 기다리는 동안 선택지를 비우지 않는 데만 쓴다. */
export type ResourceView<T> = { pending: boolean; retrying: boolean; data?: T; error?: StatisticsLoadError; at?: number; previous?: T };

function waitUnlessAborted(ms: number, signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    if (signal.aborted) { reject(signal.reason); return; }
    const stop = () => { clearTimeout(timer); reject(signal.reason); };
    const timer = setTimeout(() => { signal.removeEventListener("abort", stop); resolve(); }, ms);
    signal.addEventListener("abort", stop, { once: true });
  });
}

/**
 * 공개 유가 BFF 읽기 하나. 같은 경로·reload의 응답만 보인다. 혼잡(429·503, Retry-After 5초 이하·없음)은 한 번
 * 자동으로 다시 묻는다. `reload`가 바뀐 첫 읽기(다시 조회·오래된 탭)는 메모리 재사용을 건너뛴다.
 */
function useStatisticsResource<T>(path: string | null, reload: number, schema: Schema, onSettled?: () => void): ResourceView<T> {
  const key = path ? `${reload}:${path}` : "";
  const [state, setState] = useState<Resource<T>>({ key: "" });
  const forcedReload = useRef(0);
  const settled = useRef(onSettled);
  useEffect(() => { settled.current = onSettled; });
  useEffect(() => {
    if (!path) return;
    const controller = new AbortController();
    const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(REQUEST_TIMEOUT_MS)]);
    const force = forcedReload.current !== reload;
    forcedReload.current = reload;
    const load = (fresh: boolean) => statisticsGet(path, signal, { maxAgeMs: REUSE_MS, force: fresh }).then(value => schema.parse(value) as T);
    load(force).catch(async (reason: unknown) => {
      const delay = signal.aborted ? null : statisticsRetryDelay(reason);
      if (delay === null) throw reason;
      if (!controller.signal.aborted) setState(previous => ({ key, retrying: true, last: previous.last }));
      await waitUnlessAborted(delay, signal);
      return load(true);
    }).then(data => { if (!controller.signal.aborted) setState({ key, data, at: Date.now(), last: data }); },
      (reason: unknown) => { if (!controller.signal.aborted) setState(previous => ({ key, error: describeStatisticsError(reason), last: previous.last })); })
      .finally(() => { if (!controller.signal.aborted) settled.current?.(); });
    return () => controller.abort();
  }, [key, path, reload, schema]);
  const current = state.key === key && key ? state : undefined;
  return { pending: Boolean(path) && !current?.data && !current?.error, retrying: Boolean(current?.retrying), data: current?.data, error: current?.error, at: current?.at, previous: state.last };
}

/**
 * 화면 상태를 URL에 남긴다(공유·새로고침 시 같은 화면). 뒤로 가기 기록은 늘리지 않는다. 지역은 실제로 보이는(응답에 맞춘)
 * 지역을 쓴다 — 유종을 바꿔 다른 지역으로 바뀌었으면 링크도 그 지역이다. Next가 `history.replaceState`를 라우터 상태와 맞춘다.
 */
function useViewInUrl(view: PublicFuelStatisticsView) {
  const query = statisticsViewQuery(view);
  useEffect(() => {
    try {
      const next = `${window.location.pathname}${query ? `?${query}` : ""}`;
      if (`${window.location.pathname}${window.location.search}` !== next) window.history.replaceState(null, "", next);
    } catch { /* 주소를 바꿀 수 없는 환경에서도 화면은 그대로 쓴다. */ }
  }, [query]);
}

/** 탭을 오래 두었다 다시 보면 다시 읽는다(열어 둔 화면이 어제 통계에 머무르지 않게). */
function useRefreshWhenVisible(loadedAt: number | undefined, refresh: () => void) {
  const latest = useRef({ loadedAt, refresh });
  useEffect(() => { latest.current = { loadedAt, refresh }; });
  useEffect(() => {
    const onVisible = () => {
      const { loadedAt: at, refresh: run } = latest.current;
      if (document.visibilityState === "visible" && at !== undefined && Date.now() - at > REFRESH_AFTER_MS) run();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, []);
}

export function usePublicFuelStatistics() {
  const search = useSearchParams();
  const [view, setView] = useState(() => parseStatisticsView(new URLSearchParams(search?.toString() ?? "")));
  // 현재 값(목록·전체 노선)과 추이는 따로 다시 조회한다. 추이만 실패했을 때 146KB 목록을 다시 받지 않는다.
  const [listReload, setListReload] = useState(0);
  const [trendReload, setTrendReload] = useState(0);
  // 고속도로 "전체 노선"은 전체 범주(highways)를 먼저 읽고, 끝난 뒤 노선 목록(highway)을 읽는다 — 한 사용자가 gateway 자리를 둘 잡지 않는다.
  const [settledAll, setSettledAll] = useState("");
  const allPath = statisticsPath("highways", view.product);
  const allKey = `${listReload}:${allPath}`;
  const wantsAll = view.area === "highway" && (!view.region || view.region === ALL_ROUTES);
  const list = useStatisticsResource<PublicFuelStatistics>(wantsAll && settledAll !== allKey ? null : statisticsPath(listScope(view.area), view.product), listReload, statisticsSchema);
  const region = list.data ? resolveRegion(view, list.data.items) : null;
  const scope = currentScope({ area: view.area, region: region ?? view.region });
  const all = useStatisticsResource<PublicFuelStatistics>(scope === "highways" ? allPath : null, listReload, statisticsSchema, () => setSettledAll(allKey));
  const current = scope === "highways" ? all : list;
  const selected = scope === "highways" || view.area === "nationwide" ? current.data?.items[0]
    : current.data?.items.find(item => item.scope_key === region);
  const to = kstDay(current.data?.generated_at);
  const trend = useStatisticsResource<PublicFuelTrend>(selected && to ? historyPath(scope, selected.scope_key, view.product, view.period, to) : null, trendReload, trendSchema);
  useViewInUrl({ ...view, region: region ?? view.region });
  const refreshAll = () => { setListReload(value => value + 1); setTrendReload(value => value + 1); };
  useRefreshWhenVisible(current.at, refreshAll);
  const update = (patch: Partial<PublicFuelStatisticsView>) => setView(previous => ({ ...previous, ...patch }));
  return {
    view, update, list, current, selected, region, trend, to, missingRegion: missingRegionName(view, region),
    retryCurrent: () => setListReload(value => value + 1), retryTrend: () => setTrendReload(value => value + 1),
  };
}
