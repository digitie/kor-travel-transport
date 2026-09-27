"use client";
import { useEffect, useState } from "react";
import { transportGet } from "./journey";
import { railMarkerLabel, type RailSummaries } from "./rail-markers";

export function useRailMarkers(ids: string, enabled: boolean) {
  const [state, setState] = useState<{ ids: string; data?: RailSummaries; failed?: boolean }>({ ids: "" });
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    if (!enabled || !ids) return;
    let controller: AbortController | undefined;
    const refresh = () => {
      if (document.visibilityState !== "visible") { controller?.abort(); return; }
      controller?.abort();
      const current = new AbortController(); controller = current;
      transportGet<RailSummaries>(`transport/rail/departures?${new URLSearchParams({ place_ids: ids })}`, current.signal)
        .then((data) => { if (!current.signal.aborted) { setState({ ids, data }); setNow(Date.now()); } })
        .catch(() => { if (!current.signal.aborted) setState({ ids, failed: true }); });
    };
    const debounce = setTimeout(refresh, 250);
    const refreshTimer = setInterval(refresh, 60_000);
    const clockTimer = setInterval(() => { if (document.visibilityState === "visible") setNow(Date.now()); }, 5_000);
    const visible = () => { setNow(Date.now()); refresh(); };
    document.addEventListener("visibilitychange", visible);
    return () => { controller?.abort(); clearTimeout(debounce); clearInterval(refreshTimer); clearInterval(clockTimer); document.removeEventListener("visibilitychange", visible); };
  }, [ids, enabled]);
  const current = enabled && state.ids === ids ? state : undefined;
  const requested = new Set(ids.split(",").map(Number));
  const rows = new Map(current?.data?.items.map((row) => [row.place_id, row]));
  return (id: number) => !enabled ? "확대하여 예정 시각 확인" : !requested.has(id) ? "선택하여 예정 시각 확인" : current?.failed ? "예정 시각 조회 실패" : railMarkerLabel(current?.data, rows.get(id), now);
}
