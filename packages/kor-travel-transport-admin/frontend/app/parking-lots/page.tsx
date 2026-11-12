import { PageHeader } from "@/components/admin-shell";
import { PublicParkingLots } from "@/components/public-parking-lots";

export default function ParkingLotsPage() {
  return <><PageHeader title="일반 주차장" description="전국주차장정보 표준데이터의 저장된 총면수·요금·운영시간을 확인합니다. 실시간 잔여면은 제공하지 않습니다." /><PublicParkingLots /></>;
}
