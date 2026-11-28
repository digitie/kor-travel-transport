import {describe,it,expect} from "vitest";
import {parseSharedStation,sharedStationPath,readSharedStation} from "./fuel-station-share";
const query=new URLSearchParams("station=42&latitude=37.5&longitude=127&product=D047");
const item={id:42,kind:"fuel_station",source:"opinet_browser",name:"공유 주유소",latitude:37.5,longitude:127,updated_at:"2026-11-28T00:00:00Z",prices:[{product_code:"B027",price:1700,observed_at:"2026-11-28T00:00:00Z"}]};
describe("공유 주유소 읽기 경계",()=>{
 it("정상 ID와 목적지 좌표만 받고 기존 공개 reader 경로로 좁게 조회한다",()=>{const q=parseSharedStation(query)!;expect(q).toMatchObject({station:"42",latitude:37.5,product:"D047"});const [path,search]=sharedStationPath(q).split("?");expect(path).toBe("fuel/places");const p=new URLSearchParams(search);expect(p.get("source")).toBe("opinet_browser");expect(p.get("cluster")).toBe("false");expect(Number(p.get("max_latitude"))-Number(p.get("min_latitude"))).toBeCloseTo(.002);expect(p.get("limit")).toBe("100");expect(readSharedStation({items:[item]},q).station?.id).toBe(42);});
 it.each(["station=0","station=1e3","station=9007199254740993","latitude=0","latitude=NaN","longitude=181"])("잘못된 목적지 %s를 조회 전에 거부한다",value=>{const q=new URLSearchParams(query);const [key,v]=value.split("=");q.set(key,v);expect(parseSharedStation(q)).toBeNull();});
 it("등유나 잘못된 유종은 기본 휘발유로 연다",()=>{const q=new URLSearchParams(query);q.set("product","C004");expect(parseSharedStation(q)?.product).toBe("B027");});
 it("ID·위치 불일치와 중복 지점을 해당 지점으로 표시하지 않는다",()=>{const q=parseSharedStation(query)!;expect(readSharedStation({items:[{...item,id:43}]},q).station).toBeNull();expect(readSharedStation({items:[{...item,latitude:37.6}]},q).station).toBeNull();expect(readSharedStation({items:[item,item]},q).station).toBeNull();});
 it("변형된 가격 응답·중복 유종을 거부한다",()=>{const q=parseSharedStation(query)!;expect(()=>readSharedStation({items:[{...item,prices:[{...item.prices[0],price:"1700"}]}]},q)).toThrow();expect(()=>readSharedStation({items:[{...item,prices:[...item.prices,...item.prices]}]},q)).toThrow();});
});

it("공개 읽기 모델 지연과 상태 미제공을 구분한다",()=>{const q=parseSharedStation(query)!;expect(readSharedStation({items:[item],fuel_prices_stale:true},q).stale).toBe(true);expect(readSharedStation({items:[item],fuel_prices_stale:false},q).stale).toBe(false);expect(readSharedStation({items:[item]},q).stale).toBeNull();expect(()=>readSharedStation({items:[item],fuel_prices_stale:"true"},q)).toThrow();});
