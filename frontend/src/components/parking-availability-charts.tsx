"use client";

import dynamic from "next/dynamic";
import { groupParkingLots, parkingCounts, type ParkingChartLot } from "../lib/parking-chart-model";

const ParkingPie = dynamic(() => import("./parking-pie").then((module) => module.ParkingPie), { ssr: false, loading: () => <p role="status">주차면 그래프를 불러오는 중입니다.</p> });

export function ParkingAvailabilityCharts({ items }: { items: ParkingChartLot[] }) {
  if (!items.length) return null;
  return <div className="parking-radar"><div className="parking-pie-grid" aria-label="주차장별 잔여 주차면 그래프">
    {groupParkingLots(items).map((lots) => <article className="parking-pie-card" key={lots.map((lot) => lot.parking_lot_id).join("-")}>
      <h3>{lots.length > 1 ? lots[0].parking_lot_name.replace(/P\s*\d+\b/gi, "") : lots[0].parking_lot_name}</h3>
      <ParkingPie lots={lots} />
      <ul className="parking-pie-values">{lots.map((lot, index) => {
        const counts = parkingCounts(lot);
        const age = Date.now() - Date.parse(lot.observed_at);
        return <li key={lot.parking_lot_id}><strong>{lots.length > 1 ? `${index + 1}. ${lot.parking_lot_name}` : "잔여 / 전체"}</strong>
          <span>{counts ? `${counts.available.toLocaleString()} / ${counts.total.toLocaleString()}면 · 사용 ${counts.occupied.toLocaleString()}면` : "주차면 수치 확인 필요"}</span>
          <small>{!Number.isFinite(age) || age < 0 ? "관측 시각 확인 필요" : age > 15 * 60_000 ? "갱신 지연 · " : ""}{Number.isFinite(age) ? new Date(lot.observed_at).toLocaleString("ko-KR", { timeZone: "Asia/Seoul" }) : ""}</small>
        </li>;
      })}</ul>
      {lots.length > 1 ? <p className="muted">바깥쪽부터 목록 순서입니다. 각 원은 해당 주차장의 전체 면수입니다.</p> : null}
    </article>)}
  </div></div>;
}
