import { z } from "zod";
const product=z.enum(["B027","D047","B034","K015"]);
const requestSchema=z.object({station:z.string().regex(/^[1-9][0-9]{0,15}$/).refine(v=>Number.isSafeInteger(Number(v))),latitude:z.coerce.number().finite().min(32).max(39.5),longitude:z.coerce.number().finite().min(124).max(132),product});
export type SharedStationRequest=z.infer<typeof requestSchema>;
export function parseSharedStation(search:Pick<URLSearchParams,"get">):SharedStationRequest|null{
 const parsed=requestSchema.safeParse({station:search.get("station"),latitude:search.get("latitude"),longitude:search.get("longitude"),product:product.safeParse(search.get("product")).success?search.get("product"):"B027"});return parsed.success?parsed.data:null;
}
export function sharedStationPath(q:SharedStationRequest){
 const params=new URLSearchParams({kind:"fuel_station",source:"opinet_browser",cluster:"false",zoom:"19",limit:"100",days:"30",min_latitude:String(q.latitude-.001),max_latitude:String(q.latitude+.001),min_longitude:String(q.longitude-.001),max_longitude:String(q.longitude+.001)});
 return `fuel/places?${params}`;
}
const price=z.object({product_code:z.string().max(20),price:z.number().finite().nullable(),observed_at:z.string().max(100),collected_at:z.string().max(100).nullable().optional()});
const station=z.object({id:z.number().int().positive().refine(Number.isSafeInteger),kind:z.literal("fuel_station"),source:z.literal("opinet_browser"),name:z.string().max(2000),address:z.string().max(2000).nullable().optional(),brand_name:z.string().max(200).nullable().optional(),latitude:z.number().finite().min(-90).max(90),longitude:z.number().finite().min(-180).max(180),updated_at:z.string().max(100),prices:z.array(price).max(20)});
export type SharedFuelStation=z.infer<typeof station>;
/** URL의 ID와 위치가 일치하는 실제 저장 행만 표시한다. URL의 이름·가격은 받지 않는다. */
export function readSharedStation(payload:unknown,q:SharedStationRequest):{station:SharedFuelStation|null;stale:boolean|null}{
 const data=z.object({items:z.array(station).max(1000),fuel_prices_stale:z.boolean().optional()}).parse(payload);
 const stale=data.fuel_prices_stale??null;
 const matches=data.items.filter(item=>String(item.id)===q.station);
 if(matches.length!==1)return {station:null,stale};
 const item=matches[0];if(Math.abs(item.latitude-q.latitude)>.00101||Math.abs(item.longitude-q.longitude)>.00101)return {station:null,stale};
 const codes=item.prices.map(p=>p.product_code);if(new Set(codes).size!==codes.length)throw new Error("duplicate_product");
 return {station:item,stale};
}
export const SHARED_FUEL_PRODUCTS=[["B027","휘발유"],["D047","경유"],["B034","고급휘발유"],["K015","LPG"]] as const;
