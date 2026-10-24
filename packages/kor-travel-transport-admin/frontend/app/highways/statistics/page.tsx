import { PageHeader } from "@/components/admin-shell";
import { HighwayStatistics } from "@/components/highway-statistics";
export default function Page() { return <><PageHeader title="고속도로 통계" description="노선별 최근 구간 속도와 저속 구간 분포를 비교합니다." /><HighwayStatistics /></>; }
