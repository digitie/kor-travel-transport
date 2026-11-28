export type FuelStationLinkTarget={station_key:string;name:string;address?:string|null;latitude?:number|null;longitude?:number|null};
type Station=FuelStationLinkTarget;
export type MapLink = {label:string;url:string;fallback?:string};
const located=(s:Station)=>typeof s.latitude==="number"&&Number.isFinite(s.latitude)&&Math.abs(s.latitude)<=90&&typeof s.longitude==="number"&&Number.isFinite(s.longitude)&&Math.abs(s.longitude)<=180;
const search=(s:Station)=>[s.name,s.address].filter(Boolean).join(" ");
/** 출발 위치·검색 반경·가격·인증 정보는 공유 주소에 넣지 않는다. */
export function stationShareUrl(station:Station,product:string){
 if(!located(station)||!/^([1-9][0-9]*)$/.test(station.station_key)||!Number.isSafeInteger(Number(station.station_key))||!["B027","D047","B034","K015"].includes(product))return null;
 const query=new URLSearchParams({latitude:String(station.latitude),longitude:String(station.longitude),product,station:station.station_key});
 return `https://fuel.digitie.mywire.org/?${query}`;
}
export function stationMapLinks(station:Station):MapLink[]{
 const name=encodeURIComponent(station.name),query=encodeURIComponent(search(station));
 const naver=`https://map.naver.com/p/search/${query}`;
 const google=`https://www.google.com/maps/search/?api=1&query=${query}`;
 if(!located(station))return [{label:"네이버지도 검색",url:naver},{label:"Google 지도 검색",url:google}];
 const lat=station.latitude!,lon=station.longitude!;
 return [
  {label:"네이버지도",url:`nmap://route/car?${new URLSearchParams({dlat:String(lat),dlng:String(lon),dname:station.name,appname:"https://fuel.digitie.mywire.org"})}`,fallback:naver},
  {label:"카카오맵",url:`https://map.kakao.com/link/to/${name},${lat},${lon}`},
  {label:"Google 지도",url:`https://www.google.com/maps/dir/?${new URLSearchParams({api:"1",destination:`${lat},${lon}`,travelmode:"driving"})}`},
  {label:"Apple 지도",url:`https://maps.apple.com/directions?${new URLSearchParams({destination:`${lat},${lon}`,mode:"driving"})}`},
 ];
}
export function stationAppShare(station:Station){
 const url=located(station)?`https://map.kakao.com/link/map/${encodeURIComponent(station.name)},${station.latitude},${station.longitude}`:stationMapLinks(station)[0]?.url;
 return {title:station.name,text:search(station),url};
}
