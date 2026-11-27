"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { knownRegionLabel, statisticsGet } from "@/lib/public-fuel-statistics-client";
import {
  ALL_ROUTES, FROM_MAP_PARAM, currentScope, describeStatisticsError, displayRegionLabel, fitProductToArea, historyPath, kstDay, listScope, mapProductFromSearch,
  parseStatisticsView, regionSubstitution, resolveRegion, statisticsPath, statisticsRetryDelay, statisticsSchema, statisticsViewQuery, trendSchema,
  type PublicFuelStatistics, type PublicFuelStatisticsView, type PublicFuelTrend, type StatisticsLoadError,
} from "@/lib/public-fuel-statistics";

/** 브라우저 쪽 요청 상한. BFF 30초 상한(그 뒤 502)보다 조금 길다. */
const REQUEST_TIMEOUT_MS = 40_000;
/** 같은 경로를 이 안에 다시 고르면 다시 받지 않는다. 오피넷 공개는 하루 3회, 도로공사는 매시라 1분 재사용은 안전하다. */
const REUSE_MS = 60_000;
/** 이보다 오래 전 응답이면(탭을 오래 두었다 다시 보거나 계속 열어 둠) 현재 값을 다시 읽는다. */
const REFRESH_AFTER_MS = 10 * 60_000;
const REFRESH_CHECK_MS = 60_000;

type Schema = { parse: (value: unknown) => unknown };
type Resource<T> = { key: string; path?: string; data?: T; error?: StatisticsLoadError; retrying?: boolean; at?: number; last?: T; lastPath?: string };
/**
 * `previous`: 마지막으로 받은 응답(다른 경로일 수 있다). 새 응답을 기다리는 동안 선택지를 비우지 않는 데만 쓴다.
 * `refreshing`: 같은 경로를 다시 읽는 중(오래된 탭). 그동안 직전 값을 그대로 보이고, 다시 읽기가 실패해도 직전 값을 지우지 않는다.
 */
export type ResourceView<T> = { pending: boolean; retrying: boolean; refreshing?: boolean; data?: T; error?: StatisticsLoadError; at?: number; previous?: T };

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
 * 자동으로 다시 묻는다. `reload`가 바뀐 첫 읽기(다시 조회·오래된 탭)는 메모리 재사용을 건너뛴다(끝까지 읽은 뒤에야 처리한 것으로 센다).
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
    const load = (fresh: boolean) => statisticsGet(path, signal, { maxAgeMs: REUSE_MS, force: fresh }).then(value => schema.parse(value) as T);
    const keep = (previous: Resource<T>) => ({ last: previous.last, lastPath: previous.lastPath });
    load(forcedReload.current !== reload).catch(async (reason: unknown) => {
      const delay = signal.aborted ? null : statisticsRetryDelay(reason);
      if (delay === null) throw reason;
      if (!controller.signal.aborted) setState(previous => ({ key, path, retrying: true, ...keep(previous) }));
      await waitUnlessAborted(delay, signal);
      return load(true);
    }).then(data => {
      if (controller.signal.aborted) return;
      forcedReload.current = reload;
      setState({ key, path, data, at: Date.now(), last: data, lastPath: path });
    }, (reason: unknown) => {
      if (!controller.signal.aborted) setState(previous => ({ key, path, error: describeStatisticsError(reason), ...keep(previous) }));
    }).finally(() => { if (!controller.signal.aborted) settled.current?.(); });
    return () => controller.abort();
  }, [key, path, reload, schema]);
  const current = state.key === key && key ? state : undefined;
  // 같은 경로를 다시 읽는 동안(또는 그 다시 읽기가 실패해도) 직전 값을 지우지 않는다 — 열어 둔 표·차트가 닫히지 않는다.
  if (path && state.lastPath === path && state.last !== undefined && !current?.data && !current?.retrying) {
    return { pending: false, retrying: false, refreshing: !current, data: state.last, previous: state.last };
  }
  return { pending: Boolean(path) && !current?.data && !current?.error, retrying: Boolean(current?.retrying), data: current?.data, error: current?.error, at: current?.at, previous: state.last };
}

/**
 * 화면 상태를 URL에 남긴다(공유·새로고침 시 같은 화면). 뒤로 가기 기록은 늘리지 않는다. 지역은 실제로 보이는(응답에 맞춘)
 * 지역을 쓴다 — 유종을 바꿔 다른 지역으로 바뀌었으면 링크도 그 지역이다. Next가 `history.replaceState`를 라우터 상태와 맞춘다.
 * 지도에서 온 표시(`from=map`)는 첫 렌더에 읽고 여기서 지운다.
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

/** 응답이 오래되면 다시 읽는다: 탭을 다시 볼 때, 그리고 보이는 동안 1분마다 확인한다(열어 둔 화면이 어제 통계에 머무르지 않게). */
function useRefreshWhenStale(loadedAt: number | undefined, refresh: () => void) {
  const latest = useRef({ loadedAt, refresh });
  useEffect(() => { latest.current = { loadedAt, refresh }; });
  useEffect(() => {
    const check = () => {
      const { loadedAt: at, refresh: run } = latest.current;
      if (document.visibilityState === "visible" && at !== undefined && Date.now() - at > REFRESH_AFTER_MS) run();
    };
    document.addEventListener("visibilitychange", check);
    const timer = setInterval(check, REFRESH_CHECK_MS);
    return () => { document.removeEventListener("visibilitychange", check); clearInterval(timer); };
  }, []);
}

function initialState(search: URLSearchParams) {
  const fitted = fitProductToArea(parseStatisticsView(search));
  return { view: fitted.view, replacedProduct: fitted.replaced, fromMap: search.get(FROM_MAP_PARAM) === "map",
    // 링크가 유종을 정했는가(`product`가 아는 코드). 기본값 휘발유를 사용자가 고른 것처럼 지도에 넘기지 않으려고 따로 둔다.
    productChosen: mapProductFromSearch(search) !== null };
}

/** 카드에 보일 범주. 전국·고속도로 전체는 유일한 범주, 그 밖은 응답에 맞춘 지역. 표시 이름은 풀어 쓴다. */
function selectedItem(data: PublicFuelStatistics | undefined, region: string | null) {
  const found = region === null ? data?.items[0] : data?.items.find(item => item.scope_key === region);
  return found ? { ...found, label: displayRegionLabel(found.label) } : undefined;
}
function trendPath(view: PublicFuelStatisticsView, scope: string, scopeKey: string | undefined, to: string | null, listPending: boolean) {
  return scopeKey && to && !listPending ? historyPath(scope, scopeKey, view.product, view.period, to) : null;
}

export function usePublicFuelStatistics() {
  const search = useSearchParams();
  const [initial] = useState(() => initialState(new URLSearchParams(search?.toString() ?? "")));
  const [view, setView] = useState(initial.view);
  // 고속도로로 바꾸며 없는 유종(고급유·등유)을 휘발유로 바꿨으면 그 유종. 유종·범위를 다시 고르면 지운다.
  const [replacedProduct, setReplacedProduct] = useState(initial.replacedProduct);
  // 유종을 링크가 정했거나 이 화면에서 골랐는가. 아니면(기본 휘발유) 새로 여는 지도는 저장한 유종 선택을 그대로 쓴다.
  const [productChosen, setProductChosen] = useState(initial.productChosen);
  // 현재 값(목록·전체 노선)과 추이는 따로 다시 조회한다. 추이만 실패했을 때 146KB 목록을 다시 받지 않는다.
  const [listReload, setListReload] = useState(0);
  const [trendReload, setTrendReload] = useState(0);
  // 고속도로 "전체 노선"은 전체 범주(highways)를 먼저 읽고, 끝난 뒤 노선 목록(highway)을 읽는다.
  const [settledAll, setSettledAll] = useState("");
  const allPath = statisticsPath("highways", view.product);
  const allKey = `${listReload}:${allPath}`;
  const wantsAll = view.area === "highway" && (!view.region || view.region === ALL_ROUTES);
  const list = useStatisticsResource<PublicFuelStatistics>(wantsAll && settledAll !== allKey ? null : statisticsPath(listScope(view.area), view.product), listReload, statisticsSchema);
  const region = list.data ? resolveRegion(view, list.data.items) : null;
  const scope = currentScope({ area: view.area, region: region ?? view.region });
  const all = useStatisticsResource<PublicFuelStatistics>(scope === "highways" ? allPath : null, listReload, statisticsSchema, () => setSettledAll(allKey));
  const current = scope === "highways" ? all : list;
  const selected = selectedItem(current.data, scope === "highways" || view.area === "nationwide" ? null : region);
  const to = kstDay(current.data?.generated_at);
  // 추이는 목록이 끝난 뒤 읽는다(고속도로 전체 노선에서도 한 번에 한 요청). 현재 값을 다시 읽으면(listReload) 추이도 한 번 다시 읽는다.
  const trend = useStatisticsResource<PublicFuelTrend>(trendPath(view, scope, selected?.scope_key, to, list.pending), listReload * 100_000 + trendReload, trendSchema);
  useViewInUrl({ ...view, region: region ?? view.region });
  useRefreshWhenStale(current.at, () => setListReload(value => value + 1));
  const update = (patch: Partial<PublicFuelStatisticsView>) => {
    const fitted = fitProductToArea({ ...view, ...patch });
    if (patch.product !== undefined) setProductChosen(true);
    setReplacedProduct(fitted.replaced);
    setView(fitted.view);
  };
  const substitution = selected && !current.pending ? regionSubstitution(view, region, knownRegionLabel(view.region)) : null;
  return {
    view, update, list, current, selected, region, scope, trend, to, substitution, replacedProduct, fromMap: initial.fromMap, productChosen,
    retryCurrent: () => setListReload(value => value + 1), retryTrend: () => setTrendReload(value => value + 1),
  };
}
