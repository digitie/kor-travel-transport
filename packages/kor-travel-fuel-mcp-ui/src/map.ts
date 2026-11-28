import {createElement} from "react";
import {createRoot,type Root} from "react-dom/client";
import {VWorldMapView,type MapLibreMap} from "vworld-map-web";
import {Marker,Popup,setWorkerUrl,type GeoJSONSource} from "maplibre-gl";
import type {Station,Query} from "./model";
import {money} from "./model";

declare const __FUEL_MAP_WORKER__:string;
let workerReady=false;
export function mapKey(document:Document):string{
 try{const value=JSON.parse(document.getElementById("fuel-map-config")?.textContent??"{}");return typeof value.apiKey==="string"?value.apiKey.trim():"";}catch{return "";}
}
/** 같은 SDK·tarball을 fuel 웹과 공유한다. 서비스 인증값은 지도 코드에 전달하지 않는다. */
export class FuelMap{
 private root:Root;private map:MapLibreMap|null=null;private markers:Marker[]=[];private popup:Popup|null=null;
 private query:Query;private rows:Station[]=[];private selected:string|null=null;private camera="";private disposed=false;
 private onSelect:(station:Station)=>void=()=>{};
 constructor(container:HTMLElement,onTileError:()=>void,query:Query){
  this.query=query;this.root=createRoot(container);
  if(!workerReady){setWorkerUrl(URL.createObjectURL(new Blob([__FUEL_MAP_WORKER__],{type:"text/javascript"})));workerReady=true;}
  this.root.render(createElement(VWorldMapView,{apiKey:mapKey(document),center:[query.longitude,query.latitude],zoom:12,minZoom:5,maxZoom:19,geolocate:false,scale:false,animateCameraChanges:false,
   fallback:createElement("p",{className:"muted",role:"status"},"VWorld 지도를 열 수 없습니다. 지도 키와 WebGL 지원을 확인하고 목록에서 가격·주소를 확인해 주세요."),
   onError:()=>{if(!this.disposed)onTileError();},onLoad:map=>{if(this.disposed)return;this.map=map;this.paint();},onMoveEnd:()=>this.draw()}));
 }
 private draw(){
  const map=this.map;if(!map||this.disposed)return;this.markers.forEach(marker=>marker.remove());this.markers=[];this.popup?.remove();this.popup=null;
  const center=document.createElement("span");center.className="fuel-origin";center.textContent="검색 중심";
  this.markers.push(new Marker({element:center,anchor:"top"}).setLngLat([this.query.longitude,this.query.latitude]).addTo(map));
  const groups:{x:number;y:number;rows:Station[]}[]=[];
  for(const station of this.rows){
   if(station.latitude==null||station.longitude==null)continue;
   const point=map.project([station.longitude,station.latitude]);
   const group=station.station_key===this.selected?undefined:groups.find(g=>g.rows[0].station_key!==this.selected&&Math.hypot(g.x-point.x,g.y-point.y)<80);
   if(group)group.rows.push(station);else groups.push({x:point.x,y:point.y,rows:[station]});
  }
  for(const {rows}of groups){
   const first=rows[0],single=rows.length===1,button=document.createElement("button"),label=document.createElement("span");
   button.type="button";button.className="fuel-marker-host";button.style.zIndex=this.selected===first.station_key?"1000":"1";
   label.className="fuel-marker"+(this.selected===first.station_key?" is-selected":"");label.textContent=money(Math.min(...rows.map(s=>s.price)));
   if(!single){const count=document.createElement("small");count.textContent=`${rows.length}곳`;label.append(count);}
   button.title=single?`${first.name} ${money(first.price)}원`:`주유소 ${rows.length}곳 · 최저 ${label.firstChild?.textContent}원 · 확대 또는 목록 선택`;
   button.setAttribute("aria-label",button.title);button.append(label);
   button.onclick=event=>{event.stopPropagation();
    if(single){this.onSelect(first);return;}
    if(map.getZoom()<18.9){const lng=rows.map(s=>s.longitude!),lat=rows.map(s=>s.latitude!);map.fitBounds([[Math.min(...lng),Math.min(...lat)],[Math.max(...lng),Math.max(...lat)]],{padding:30,maxZoom:19,duration:0});return;}
    const list=document.createElement("div");list.className="fuel-map-choices";
    for(const station of rows){const choice=document.createElement("button");choice.type="button";choice.textContent=`${station.name} · ${money(station.price)}원/L`;choice.onclick=()=>{this.popup?.remove();this.onSelect(station);};list.append(choice);}
    this.popup=new Popup().setLngLat([first.longitude!,first.latitude!]).setDOMContent(list).addTo(map);
   };
   this.markers.push(new Marker({element:button,anchor:"bottom"}).setLngLat([first.longitude!,first.latitude!]).addTo(map));
  }
 }
 private paint(){
  const map=this.map;if(!map||this.disposed)return;
  const q=this.query,delta=q.radius_m/6371008.8,lat=q.latitude*Math.PI/180,lon=q.longitude*Math.PI/180;
  const coordinates=Array.from({length:65},(_,i)=>{const angle=i/64*2*Math.PI;const y=Math.asin(Math.sin(lat)*Math.cos(delta)+Math.cos(lat)*Math.sin(delta)*Math.cos(angle));const x=lon+Math.atan2(Math.sin(angle)*Math.sin(delta)*Math.cos(lat),Math.cos(delta)-Math.sin(lat)*Math.sin(y));return[x*180/Math.PI,y*180/Math.PI];});
  const data={type:"Feature" as const,properties:{},geometry:{type:"Polygon" as const,coordinates:[coordinates]}};
  const source=map.getSource("fuel-radius") as GeoJSONSource|undefined;
  if(source)source.setData(data);else{map.addSource("fuel-radius",{type:"geojson",data});map.addLayer({id:"fuel-radius-fill",type:"fill",source:"fuel-radius",paint:{"fill-color":"#1260ba","fill-opacity":.05}});map.addLayer({id:"fuel-radius-line",type:"line",source:"fuel-radius",paint:{"line-color":"#1260ba","line-width":1}});}
  const camera=`${q.latitude}:${q.longitude}:${q.radius_m}`;
  if(camera!==this.camera){this.camera=camera;const lng=coordinates.map(p=>p[0]),latitudes=coordinates.map(p=>p[1]);map.fitBounds([[Math.min(...lng),Math.min(...latitudes)],[Math.max(...lng),Math.max(...latitudes)]],{padding:25,maxZoom:16,duration:0});}
  map.resize();this.draw();
 }
 update(query:Query,rows:Station[],selected:string|null,onSelect:(station:Station)=>void){this.query=query;this.rows=rows;this.selected=selected;this.onSelect=onSelect;this.paint();}
 focus(station:Station){if(this.map&&station.latitude!=null&&station.longitude!=null)this.map.jumpTo({center:[station.longitude,station.latitude],zoom:Math.max(15,this.map.getZoom())});}
 retry(){const map=this.map;if(!map)return;for(const[id,style]of Object.entries(map.getStyle().sources)){if(style.type==="raster"&&style.tiles){const source=map.getSource(id);if(source&&"setTiles"in source&&typeof source.setTiles==="function")source.setTiles([...style.tiles]);}}}
 destroy(){this.disposed=true;this.markers.forEach(marker=>marker.remove());this.popup?.remove();this.root.unmount();this.map=null;}
}
