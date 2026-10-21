import Link from "next/link";
import { PageHeader } from "@/components/admin-shell";
import { TransportMap } from "@/components/transport-map";

export default function FuelPage() { return <><PageHeader title="유가 지도" actions={<Link href="/fuel/statistics">유가 통계</Link>} description="주유소별 최신 가격과 유종 정보를 지도에서 확인합니다." /><TransportMap mode="fuel" /></>; }
