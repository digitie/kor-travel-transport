import { PageHeader } from "@/components/admin-shell";
import { TransportMap } from "@/components/transport-map";

export default function MapPage() { return <><PageHeader title="교통 지도" description="철도역·항구·버스 터미널·공항·휴게소·도로 돌발 위치를 확인합니다." /><TransportMap mode="transport" /></>; }
