"use client";
import dynamic from "next/dynamic";
import { useSearchParams } from "next/navigation";
import { PublicFuelStation } from "@/components/public-fuel-station";
const PublicFuelMap=dynamic(()=>import("@/components/public-fuel-map").then(module=>module.PublicFuelMap));
/** 공유 상세는 지도 전체·타일을 불러오지 않고 한 지점의 저장 정보만 읽는다. */
export function PublicFuelEntry({refreshEnabled}:{refreshEnabled?:boolean}){
 const search=useSearchParams();return search.has("station")?<PublicFuelStation/>:<PublicFuelMap refreshEnabled={refreshEnabled}/>;
}
