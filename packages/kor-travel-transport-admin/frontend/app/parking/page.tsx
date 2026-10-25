import { PageHeader } from "@/components/admin-shell";
import { AirportParking, type ParkingView } from "@/components/airport-parking";

export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const params = await searchParams;
  const airportCode = typeof params.airport === "string" && /^[A-Za-z]{3}$/.test(params.airport) ? params.airport.toUpperCase() : "";
  const lot = typeof params.lot === "string" ? Number(params.lot) : NaN;
  const initialSelection = airportCode ? { airportCode, parkingLotId: Number.isSafeInteger(lot) && lot > 0 ? lot : null } : null;
  const initialView = typeof params.view === "string" && ["current", "analytics", "history", "fees"].includes(params.view) ? params.view as ParkingView : "current";
  return <><PageHeader title="공항 주차장" description="현재 잔여면, 관측 이력, 요일·공휴일·임계치 패턴과 공개 기준 주차요금을 확인합니다. 과거 패턴은 입차 가능성을 보장하는 예측값이 아닙니다." /><AirportParking initialSelection={initialSelection} initialView={initialView} /></>;
}
