"use client";
import Link from "next/link";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { buttonVariants } from "@/components/ui/button-variants";
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from "@/components/ui/card";
import { Field, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { publicFuelGet } from "@/lib/public-fuel";
import { dateTime } from "@/lib/journey";
import { stationMapLinks, stationShareUrl, stationAppShare, type FuelStationLinkTarget } from "@/lib/fuel-station-links";
import { parseSharedStation, sharedStationPath, readSharedStation, SHARED_FUEL_PRODUCTS, type SharedFuelStation } from "@/lib/fuel-station-share";

export function PublicFuelStation(){
 const search=useSearchParams();const key=search.toString();const request=useMemo(()=>parseSharedStation(new URLSearchParams(key)),[key]);
 const [reload,setReload]=useState(0);const identity=`${key}:${reload}`;
 const [state,setState]=useState<{key:string;station?:SharedFuelStation|null;stale?:boolean|null;error?:boolean}>();
 useEffect(()=>{
  if(!request)return;
  const controller=new AbortController();
  publicFuelGet<unknown>(sharedStationPath(request),AbortSignal.any([controller.signal,AbortSignal.timeout(15000)]))
   .then(payload=>{if(!controller.signal.aborted)setState({key:identity,...readSharedStation(payload,request)});})
   .catch(()=>{if(!controller.signal.aborted)setState({key:identity,error:true});});
  return()=>controller.abort();
 },[identity,request]);
 const current=state?.key===identity?state:undefined;const station=current?.station;
 const target=station?{...station,station_key:String(station.id)}:null;
 const shareUrl=target&&request?stationShareUrl(target,request.product):null;
 const mapHref=request?`/?${new URLSearchParams({latitude:String(request.latitude),longitude:String(request.longitude),product:request.product})}`:"/";
 return <main className="public-fuel-surface mx-auto flex min-h-dvh w-full max-w-3xl flex-col gap-4 p-4" aria-label="공유한 주유소 상세">
  <header className="flex items-center justify-between gap-3"><h1 className="text-xl font-semibold">주유소 상세</h1><Link className={buttonVariants({variant:"outline",size:"sm"})} href={mapHref}>유가 지도</Link></header>
  {!request?<Alert variant="destructive"><AlertDescription>주유소 공유 링크가 올바르지 않습니다.</AlertDescription></Alert>:!current?<section aria-label="주유소 조회 중"><p role="status">저장된 주유소 정보를 확인하고 있습니다.</p><Skeleton className="mt-3 h-40 w-full" /></section>:current.error||!station?<Alert variant="destructive"><AlertDescription><p>해당 주유소 정보를 불러오지 못했습니다. 지점 정보가 변경되었거나 잠시 조회할 수 없습니다.</p><Button variant="outline" size="sm" onClick={()=>setReload(v=>v+1)}>다시 조회</Button></AlertDescription></Alert>:<>
   <StationPriceCard station={station} stale={current.stale} />
   {target&&<StationMapCard target={target} />}
   {target&&<StationSharing key={identity} target={target} shareUrl={shareUrl} />}
  </>}
 </main>;
}


function StationPriceCard({station,stale}:{station:SharedFuelStation;stale:boolean|null|undefined}){
 return <Card><CardHeader><CardTitle className="break-words">{station.name}</CardTitle><CardDescription className="break-words">{station.brand_name??"상표 미제공"} · {station.address??"주소 미제공"}</CardDescription></CardHeader>
    <CardContent className="flex flex-col gap-3">{stale?<Alert><AlertDescription>가격 정보 갱신이 지연되고 있습니다. 표시된 수집 시각을 확인해 주세요.</AlertDescription></Alert>:stale===null?<p className="text-sm text-text-secondary">가격 갱신 상태가 제공되지 않았습니다.</p>:null}<dl className="grid grid-cols-2 gap-4">{SHARED_FUEL_PRODUCTS.map(([code,label])=>{const row=station.prices.find(p=>p.product_code===code);const amount=row?.price;return <div key={code}><dt className="text-sm text-text-secondary">{label}</dt><dd className="text-xl font-semibold">{amount!=null&&amount>0&&amount<100000000?`${amount.toLocaleString("ko-KR",{maximumFractionDigits:2})}원/L`:"미제공"}</dd><dd className="text-xs text-text-secondary">수집 {dateTime(row?.collected_at??row?.observed_at)}</dd></div>;})}</dl></CardContent>
    <CardFooter><p className="text-xs text-text-secondary">저장된 가격이며 실제 판매가는 주유소에서 확인해 주세요.</p></CardFooter></Card>;
}

function StationMapCard({target}:{target:FuelStationLinkTarget}){
 return <Card><CardHeader><CardTitle>목적지로 길찾기</CardTitle><CardDescription>주유소가 도착지로 지정됩니다.</CardDescription></CardHeader><CardContent className="flex flex-wrap gap-2">{target&&stationMapLinks(target).map(link=><span key={link.label} className="flex items-center gap-2"><a className={buttonVariants({variant:"outline",size:"sm"})} href={link.url} target={link.url.startsWith("https:")?"_blank":undefined} rel="noopener noreferrer">{link.label}</a>{link.fallback?<a className="text-xs text-text-secondary underline" href={link.fallback} target="_blank" rel="noopener noreferrer">웹 지도</a>:null}</span>)}</CardContent></Card>;
}

function StationSharing({target,shareUrl}:{target:FuelStationLinkTarget;shareUrl:string|null}){
 const [notice,inform]=useState("");const linkInput=useRef<HTMLInputElement>(null);const shareId=useId();
 const selectLink=()=>{linkInput.current?.focus();linkInput.current?.select();inform("공유 링크를 길게 누르거나 선택해서 복사해 주세요.");};
 async function copy(){if(!shareUrl)return;if(!navigator.clipboard){selectLink();return;}try{await navigator.clipboard.writeText(shareUrl);inform("주유소 상세 공유 링크를 복사했습니다.");}catch{selectLink();}}
 async function share(myHyundai:boolean){inform("공유창에서 앱을 선택해 주세요.");if(!navigator.share){inform("앱 공유창을 지원하지 않는 브라우저입니다. 목적지 주소나 공유 링크를 복사해 주세요.");return;}try{await navigator.share(myHyundai?stationAppShare(target):{title:target.name,text:target.address??target.name,url:shareUrl??undefined});inform("공유창에 위치 정보를 전달했습니다.");}catch(error){if(error instanceof DOMException&&error.name==="AbortError"){inform("공유를 취소했습니다.");return;}inform("공유창을 열지 못했습니다. 목적지 주소나 공유 링크를 복사해 주세요.");}}
 return <Card><CardHeader><CardTitle>공유</CardTitle></CardHeader><CardContent className="flex flex-col gap-3"><Field><FieldLabel htmlFor={shareId}>주유소 상세 링크</FieldLabel><Input id={shareId} ref={linkInput} readOnly value={shareUrl??""} /></Field><div className="flex flex-wrap gap-2"><Button size="sm" variant="outline" onClick={()=>void copy()}>링크 복사</Button><Button size="sm" onClick={()=>void share(true)}>마이현대로 위치 공유</Button><Button size="sm" variant="outline" onClick={()=>void share(false)}>다른 앱으로 공유</Button></div><p className="text-sm text-text-secondary">휴대폰 공유창에서 마이현대를 선택해 지도에서 위치를 확인하세요. 공유 목록에 없으면 주유소 주소를 복사해 앱 지도에서 검색할 수 있습니다.</p><p role="status" aria-live="polite" className="text-sm">{notice}</p></CardContent></Card>;
}
