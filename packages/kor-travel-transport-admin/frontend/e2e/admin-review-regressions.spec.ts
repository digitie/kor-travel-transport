import { expect, test, type Page } from "@playwright/test";

const station = {provider_id:"역/1 &?=",station_name:"시험역",station_code:null,address:"시험시 역길 1",phone:"+82 (2) 123-4567",longitude:127.1,latitude:37.3};
const at = "2026-11-12T00:00:00Z";
async function isolatedSession(page: Page) {
 // 모의 쿠키·API 응답은 격리된 로컬 서버에서만 사용한다. 운영 인증 수용과 구분한다.
 const origin = new URL(process.env.E2E_BASE_URL ?? "http://127.0.0.1:12305");
 if (!["127.0.0.1", "localhost", "[::1]"].includes(origin.hostname)) throw new Error("격리 회귀 검사는 loopback 서버에서만 실행할 수 있습니다.");
 await page.context().addCookies([{name:"kor_travel_transport_admin_session",value:"isolated-review-regression",url:origin.origin,httpOnly:true,sameSite:"Strict"}]);
}
async function localTiles(page: Page) {
 const png=await page.evaluate(()=>{const canvas=document.createElement("canvas");canvas.width=256;canvas.height=256;return canvas.toDataURL("image/png").split(",")[1];});
 await page.route("https://api.vworld.kr/**",route=>route.fulfill({contentType:"image/png",headers:{"access-control-allow-origin":"*"},body:Buffer.from(png,"base64")}));
}

for(const width of [375,1440]) test("일반철도 상세의 공식 안내·전화·주소 지도 이동 보존 " + width + "px",async({page})=>{
 await page.setViewportSize({width,height:900});await isolatedSession(page);
 await page.route("**/api/transport/**",route=>{
  const url=new URL(route.request().url());
  if(url.pathname.endsWith("/guide"))return route.fulfill({json:{fetched_at:at,stale:false,kind:"ktx",category_code:"",total:1,categories:[],items:[station]}});
  if(url.pathname.endsWith("/catalog"))return route.fulfill({json:{fetched_at:at,stale:false,cities:[{code:"11",name:"시험시"}],train_classes:[]}});
  return route.fulfill({json:{items:[],stale:false}});
 });
 await page.route("https://api.vworld.kr/**",route=>route.abort());
 await page.goto("/rail");await page.getByRole("tab",{name:"목록",exact:true}).click();
 await page.locator(".map-place-list").getByRole("button",{name:/시험역/}).click();
 const detail=page.getByRole("complementary",{name:"선택 장소 상세"});
 const official=detail.getByRole("link",{name:"공식 역 안내",exact:false});
 await expect(official).toHaveAttribute("href","https://www.korail.com/ticket/train/stationGuide/station/view?stationSeq="+encodeURIComponent(station.provider_id));
 await expect(official).toHaveAttribute("target","_blank");await expect(official).toHaveAttribute("rel",/noreferrer/);
 await expect(detail.getByRole("link",{name:station.phone,exact:true})).toHaveAttribute("href","tel:+8221234567");
 await detail.getByRole("button",{name:/시험시 역길 1 · 지도에서 보기/}).click();
 await expect(page.getByRole("tab",{name:"지도",exact:true})).toHaveAttribute("aria-selected","true");
 await expect(detail).toBeFocused();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});

for(const width of [375,1440]) test("실제 VWorld Marker 집계 갱신은 같은 DOM·키보드 초점을 보존 " + width + "px",async({page})=>{
 test.skip(process.env.E2E_MAP_SDK!=="true","격리 키와 PNG 타일로 실제 SDK를 실행하는 gate");
 await page.setViewportSize({width,height:900});await isolatedSession(page);await localTiles(page);
 let count=2;
 await page.route("**/api/transport/**",route=>route.fulfill({json:{items:[],total:count,truncated:false,clustered:true,clusters:[{longitude:127.8,latitude:36.2,count,kind_counts:{fuel_station:count}}]}}));
 await page.goto("/fuel");
 const canvas=page.locator(".maplibregl-map"),marker=page.locator(".map-cluster");
 await expect(canvas).toBeVisible();
 await expect(page.locator(".kt-map-coordinates")).toContainText("center");
 await expect(marker).toHaveAttribute("aria-label","2개 장소 요약 묶음 확대");
 await marker.evaluate(element=>{(window as Window & {transportClusterBefore?:Element}).transportClusterBefore=element;});await marker.focus();await expect(marker).toBeFocused();
 count=3;
 // 공개된 확대 조작으로 마커 초점을 옮기지 않고 새 집계 응답을 받는다.
 await page.locator(".maplibregl-ctrl-zoom-in").evaluate(element=>(element as HTMLButtonElement).click());
 await expect(marker).toHaveAttribute("aria-label","3개 장소 요약 묶음 확대");
 expect(await marker.evaluate(element=>element===(window as Window & {transportClusterBefore?:Element}).transportClusterBefore)).toBe(true);
 await expect(marker).toBeFocused();
});
