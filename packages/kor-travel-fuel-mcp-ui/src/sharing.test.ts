import {describe,it,expect} from "vitest";
import {stationMapLinks,stationShareUrl,stationAppShare} from "../../kor-travel-transport-admin/frontend/lib/fuel-station-links";
const station={station_key:"1",name:"A & <주유소>",address:"서울시 / 가로 1",latitude:37.5,longitude:127,price:1500};
describe("주유소 공유와 지도 앱 연결",()=>{
 it("주유소 좌표/유종만 공유하고 출발 위치·가격·토큰을 넣지 않는다",()=>{const url=new URL(stationShareUrl(station,"D047")!);expect(url.origin).toBe("https://fuel.digitie.mywire.org");expect([...url.searchParams.keys()].sort()).toEqual(["latitude","longitude","product","station"]);expect(url.searchParams.get("latitude")).toBe("37.5");expect(url.searchParams.get("station")).toBe("1");});
 it("지도별 좌표 순서와 인코딩을 보존한다",()=>{const links=stationMapLinks(station);expect(links).toHaveLength(4);const n=new URL(links[0].url);expect(n.protocol).toBe("nmap:");expect(n.searchParams.get("dlat")).toBe("37.5");expect(n.searchParams.get("dlng")).toBe("127");expect(n.searchParams.get("dname")).toBe(station.name);expect(links[0].fallback).toMatch(/^https:\/\/map.naver.com\/p\/search\//);expect(links[1].url).toContain(",37.5,127");expect(new URL(links[3].url).searchParams.get("destination")).toBe("37.5,127");});
 it("마이현대 등 앱 공유는 목적지 지도 링크를 제공한다",()=>{const share=stationAppShare(station);expect(share.url).toMatch(/^https:\/\/map.kakao.com\/link\/map\//);expect(share.title).toBe(station.name);expect(share).not.toHaveProperty("target");});
 it("좌표가 없으면 허위 위치 링크를 만들지 않고 검색만 제공한다",()=>{const s={...station,latitude:null};expect(stationShareUrl(s,"B027")).toBeNull();expect(stationMapLinks(s)).toHaveLength(2);expect(stationMapLinks(s).every(x=>x.label.endsWith("검색"))).toBe(true);});
});
