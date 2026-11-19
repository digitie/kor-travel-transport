import { PAGE_HEADINGS } from "@/components/admin-nav";
import { PageHeader } from "@/components/admin-shell";
import { AirportParking, type ParkingView } from "@/components/airport-parking";

export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const params = await searchParams;
  const airportCode = typeof params.airport === "string" && /^[A-Za-z]{3}$/.test(params.airport) ? params.airport.toUpperCase() : "";
  const lot = typeof params.lot === "string" ? Number(params.lot) : NaN;
  const initialSelection = airportCode ? { airportCode, parkingLotId: Number.isSafeInteger(lot) && lot > 0 ? lot : null } : null;
  const initialView = typeof params.view === "string" && ["current", "analytics", "history", "fees"].includes(params.view) ? params.view as ParkingView : "current";
  return <><PageHeader {...PAGE_HEADINGS["/parking"]} /><AirportParking initialSelection={initialSelection} initialView={initialView} /></>;
}
