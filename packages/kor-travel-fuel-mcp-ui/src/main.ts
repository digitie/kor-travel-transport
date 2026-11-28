import { App } from "@modelcontextprotocol/ext-apps";
import { FuelController } from "./controller";
import { PRODUCTS, collectedAt, distance, mapUrl, money, queryFromResult, querySchema, readResult, rowsFor, type FuelResponse, type Query, type Station } from "./model";
import { FuelMap } from "./map";
import { stationMapLinks, stationShareUrl, stationAppShare } from "../../kor-travel-transport-admin/frontend/lib/fuel-station-links";
import "../../kor-travel-transport-admin/frontend/app/transport-palette.css";
import "./style.css";
const root = document.querySelector<HTMLElement>("#app")!;
// 정적인 화면 구조만 HTML로 선언한다. 도구/사용자 문자열은 아래에서 textContent로 넣는다.
root.innerHTML = `<header class="heading"><div><p class="eyebrow">FUEL · 내 주변 유가</p><h1>내 주변 주유소</h1></div><button id="refresh" type="button" disabled>다시 조회</button></header>
<div id="notice" role="status" aria-live="polite">대화의 검색 결과를 기다리고 있습니다.</div>
<form id="controls"><details id="location"><summary>검색 위치·반경</summary><div class="location-fields"><label>위도<input id="latitude" type="number" step="any" min="-90" max="90" required></label><label>경도<input id="longitude" type="number" step="any" min="-180" max="180" required></label></div></details>
<div class="control-row"><label>반경<select id="radius"><option value="1000">1km</option><option value="3000">3km</option><option value="5000" selected>5km</option><option value="10000">10km</option><option value="20000">20km</option><option value="50000">50km</option></select></label><label>정렬<select id="sort"><option value="price">가격 낮은 순</option><option value="distance">직선거리 가까운 순</option></select></label></div><div class="search-actions"><button id="locate" type="button" disabled>현재 위치로 검색</button><button id="search" type="button" disabled>이 조건으로 조회</button></div></form>
<fieldset class="products"><legend class="sr-only">유종 선택</legend><div id="products"></div></fieldset>
<section id="summary" aria-label="유가 요약"></section>
<div class="view-heading"><h2 id="list-title" tabindex="-1">주유소</h2><div class="views" role="group" aria-label="표시 방식"><button id="list-view" type="button" aria-pressed="true">목록</button><button id="map-view" type="button" aria-pressed="false">지도</button></div></div>
<p id="result-caption" class="muted"></p><label class="filter-label">이름·주소 찾기<input id="filter" type="search" placeholder="표시된 주유소에서 검색" autocomplete="off"></label>
<section id="map-pane" aria-label="주유소 지도" hidden><div id="map"></div><p id="map-message" class="muted" role="status"></p><button id="tile-retry" type="button" hidden>배경지도 다시 불러오기</button></section>
<div class="results-layout"><section id="stations" aria-label="주유소 목록"></section><aside id="detail" aria-label="선택한 주유소 상세" hidden tabindex="-1"></aside></div>
<section class="comparison"><div class="compare-heading"><h2>지역 가격과 비교</h2><div><button id="district" type="button" disabled>현재 위치 시군구</button><button id="national" type="button" disabled>전국</button></div></div><div id="comparison" role="status" aria-live="polite">범위 선택 시 저장된 지역 통계를 조회합니다.</div></section>
<footer><p id="timestamp">수집 시각 미제공</p><p>가격은 원/L · 거리는 직선거리입니다. 방문 전 실제 판매가를 확인하세요.</p><p>지도 배경은 VWorld에서 불러옵니다.</p><button id="full-fuel" type="button">fuel 웹에서 더 보기</button></footer>`;
const el = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
const app = new App({ name: "transport-nearby-fuel", version: "1.0.0" }, {}, { autoResize: true });
let connected = false, busy = false, result: FuelResponse | null = null, query: Query | null = null, product = "B027", selected: Station | null = null, map: FuelMap | null = null, comparison: FuelResponse | null = null;
let comparisonEpoch = 0, locationEpoch = 0, preferMap = true;
const controller = new FuelController((name, args) => app.callServerTool({ name, arguments: args }, { timeout: 25000 }));
const message = (text: string, error = false) => { el("notice").textContent = text; el("notice").dataset.error = String(error); };
const text = (tag: string, value: string, className?: string) => { const node = document.createElement(tag); node.textContent = value; if (className)
    node.className = className; return node; };
async function openExternal(url:string,fallback?:string){
 for(const target of [url,...(fallback?[fallback]:[])]){
  try{const response=await app.openLink({url:target});if(!response.isError)return;}catch{/* 호스트 거부도 웹 대체 경로를 한 번 시도한다. */}
 }
 message("외부 화면을 열지 못했습니다. 공유 링크를 복사하거나 다른 지도 앱을 선택해 주세요.",true);
}
async function shareData(data:ShareData){
 message("공유창에서 앱을 선택해 주세요.");
 if(!navigator.share){message("이 환경은 앱 공유창을 지원하지 않습니다. 공유 링크를 복사해 휴대폰에서 열어 주세요.",true);return;}
 try{await navigator.share(data);message("공유창에 주유소 정보를 전달했습니다.");}catch(error){if(error instanceof DOMException&&error.name==="AbortError"){message("공유를 취소했습니다.");return;}message("이 환경에서 공유창을 열 수 없습니다. 공유 링크를 복사해 휴대폰에서 열어 주세요.",true);}
}
function setTheme(theme: string) { document.documentElement.dataset.theme = theme; document.documentElement.classList.toggle("dark", theme === "dark"); }
function setBusy(value: boolean) {
    busy = value;
    for (const id of ["search", "refresh", "district", "national", "locate", "full-fuel"])
        el<HTMLButtonElement>(id).disabled = value || !connected;
    el("stations").setAttribute("aria-busy", String(value));
    el("refresh").textContent = value ? "조회 중…" : "다시 조회";
    for(const id of ["district","national","refresh"]) el<HTMLButtonElement>(id).disabled = value || !connected || !query;
    el<HTMLButtonElement>("map-view").disabled=!query;
}
function fillQuery(next: Query) {
    query = next;
    el<HTMLInputElement>("latitude").value = String(next.latitude);
    el<HTMLInputElement>("longitude").value = String(next.longitude);
    const radius = el<HTMLSelectElement>("radius");
    if (!Array.from(radius.options).some(o => o.value === String(next.radius_m)))
        radius.add(new Option(`${next.radius_m}m`, String(next.radius_m)));
    radius.value = String(next.radius_m);
    el<HTMLSelectElement>("sort").value = next.sort_by;
}
function requestQuery() { return querySchema.safeParse({ latitude: Number(el<HTMLInputElement>("latitude").value), longitude: Number(el<HTMLInputElement>("longitude").value), radius_m: Number(el<HTMLSelectElement>("radius").value), sort_by: el<HTMLSelectElement>("sort").value }); }
function showCollection(data: FuelResponse) {
    const c = data.collection;
    const flags = [(c.stale || c.public_source_stale) ? "수집 지연" : null, c.update_pending ? "새 통계 반영 대기" : null, c.last_attempt_failed ? "최근 수집 실패·이전 성공분" : null].filter(Boolean);
    message(c.status === "unavailable" ? "아직 공개된 가격 자료가 없습니다." : flags.length ? flags.join(" · ") : "저장된 성공 수집분의 가격입니다.");
    el("timestamp").textContent = `수집 ${collectedAt(c.generated_at)}`;
}
function accept(data: FuelResponse) {
    if(data.collection.reason==="location_required" && data.products.length===0 && data.latitude==null && data.longitude==null){
        controller.invalidate();comparisonEpoch++;locationEpoch++;result=null;query=null;comparison=null;selected=null;
        el<HTMLInputElement>("latitude").value="";el<HTMLInputElement>("longitude").value="";
        preferMap=true;map?.destroy();map=null;el("map").replaceChildren();el("map-pane").hidden=true;
        el("map-message").textContent="";el("tile-retry").hidden=true;
        el("list-view").setAttribute("aria-pressed","true");el("map-view").setAttribute("aria-pressed","false");
        el("timestamp").textContent="수집 시각 미제공";
        setBusy(false);message("현재 위치로 검색을 누르고 위치 권한을 허용하거나, 검색 위치에 좌표를 입력해 주세요.");render();return;
    } if (data.scope !== "radius" || !queryFromResult(data)) {
    setBusy(false);
    message("주변 검색 응답의 위치를 확인하지 못했습니다. 다시 조회해 주세요.", true);
    return;
} controller.invalidate(); comparisonEpoch++; result = data; comparison = null; selected = null;
const available=data.products.filter(p=>PRODUCTS.some(([code])=>code===p.product_code));
if(!available.some(p=>p.product_code===product)) product=available[0]?.product_code??"B027";
const next = queryFromResult(data); if (next)
    fillQuery(next); setBusy(false); showCollection(data); render(); }
function search() {
    locationEpoch++;
    if (!connected || busy)
        return;
    const fields = [el<HTMLInputElement>("latitude"), el<HTMLInputElement>("longitude")];
    if (fields.some(field => !field.value.trim())) {
        message("위도·경도를 입력하거나 현재 위치를 허용해 주세요.", true);
        el<HTMLDetailsElement>("location").open = true;
        return;
    }
    const parsed = requestQuery();
    if (!parsed.success) {
        message("유효한 좌표와 50km 이내 반경을 입력해 주세요.", true);
        return;
    }
    setBusy(true);
    message("주유소 가격을 조회하고 있습니다.");
    comparisonEpoch++;
    void controller.search(parsed.data, accept, error => { setBusy(false); message(error + (result ? " 이전 결과를 표시합니다." : ""), true); });
}
function displayedRows() {
    const p = result ? rowsFor(result, product) : null;
    const filter = el<HTMLInputElement>("filter").value.trim().toLocaleLowerCase();
    return (p?.ranked_stations ?? p?.cheapest_stations ?? []).filter(s => !filter || `${s.name} ${s.address ?? ""}`.toLocaleLowerCase().includes(filter));
}
function select(station: Station) { selected = station; render(); if (!el("map-pane").hidden)
    map?.focus(station); el("detail").focus({ preventScroll: true }); }
function renderProducts() {
    const host=el("products");
    if(!host.childElementCount) for(const [code,label] of PRODUCTS){
        const button=text("button",label) as HTMLButtonElement;button.type="button";button.dataset.productCode=code;
        button.onclick=()=>{product=code;selected=null;render();};host.append(button);
    }
    for(const button of host.querySelectorAll<HTMLButtonElement>("button")) button.setAttribute("aria-pressed",String(button.dataset.productCode===product));
}
function renderSummary() {
    const p = result ? rowsFor(result, product) : null;
    el("summary").replaceChildren();
    if (!p)
        return;
    const stats = [["반경 내 최저", p.minimum_price], ["반경 내 평균", p.average_price]] as const;
    for (const [label, value] of stats) {
        const box = text("div", "", "stat");
        box.append(text("span", label, "muted"), text("strong", money(value)), text("span", value == null ? "" : "원/L", "muted"));
        el("summary").append(box);
    }
}
function renderStations() {
    const p = result ? rowsFor(result, product) : null;
    const rows = displayedRows();
    el("stations").replaceChildren();
    const label = PRODUCTS.find(([c]) => c === product)?.[1] ?? "유가";
    el("list-title").textContent = `${label} 주유소`;
    const count = p?.station_count;
    el("result-caption").textContent = count == null ? "자료 미제공" : `반경 ${result?.radius_m ?? 0}m · 전체 ${count.toLocaleString("ko-KR")}곳 중 ${rows.length}곳 표시 · ${result?.sort_by === "distance" ? "거리순" : "가격순"}${p?.ranking_truncated ? " 상위20곳" : ""}`;
    if (!rows.length) {
        el("stations").append(text("p", result ? (count === 0 ? "이 반경에 판매 가격이 확인된 주유소가 없습니다." : el<HTMLInputElement>("filter").value ? "표시된 목록에 일치하는 주유소가 없습니다." : "이 유종의 자료가 제공되지 않았습니다.") : "대화에서 위치를 알려 주시거나 검색 위치를 입력해 주세요.", "empty"));
        return;
    }
    for (const [i, station] of rows.entries()) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "station";
        button.dataset.stationKey = station.station_key;
        button.setAttribute("aria-pressed", String(selected?.station_key === station.station_key));
        const info = text("span", "", "station-info");
        info.append(text("strong", `${i + 1}. ${station.name}`), text("span", station.address ?? "주소 미제공", "muted"), text("span", `${station.brand_name ?? "상표 미제공"} · ${distance(station.distance_m)}`, "muted"));
        const amount = text("span", "", "amount");
        amount.append(text("strong", money(station.price)), text("span", "원/L", "muted"));
        if (station.price === p?.minimum_price)
            amount.append(text("span", "최저", "lowest"));
        button.append(info, amount);
        button.onclick = () => select(station);
        el("stations").append(button);
    }
}
function renderDetail() {
    const panel = el("detail");
    panel.hidden = !selected;
    panel.replaceChildren();
    if (!selected)
        return;
    const close = text("button", "닫기") as HTMLButtonElement;
    close.type = "button";
    close.className = "close";
    close.onclick = () => { const key = selected?.station_key; selected = null; render(); (Array.from(document.querySelectorAll<HTMLButtonElement>(".station")).find(button => button.dataset.stationKey === key) ?? el("list-title")).focus(); };
    panel.append(close, text("h2", selected.name), text("p", selected.address ?? "주소 미제공", "muted"), text("p", distance(selected.distance_m), "muted"));
    const list = document.createElement("dl");
    for (const [code, label] of PRODUCTS) {
        const station = result?.products.find(p => p.product_code === code)?.ranked_stations?.find(s => s.station_key === selected?.station_key);
        const row = text("div", "", "detail-price");
        row.append(text("dt", label), text("dd", station ? `${money(station.price)}원/L` : "표시 결과 내 가격 미제공"));
        list.append(row);
    }
    panel.append(list);
    const url = mapUrl(selected);
    if (url) {
        const button = text("button", "큰 지도에서 위치 보기") as HTMLButtonElement;
        button.type = "button";
        button.onclick = () => { void openExternal(url); };
        panel.append(button);
    }
    const sharing=document.createElement("section");sharing.className="station-sharing";sharing.setAttribute("aria-label","주유소 공유 및 지도 앱");
    sharing.append(text("h3","공유·지도 앱"));
    const link=stationShareUrl(selected,product);
    if(link){const label=text("label","공유 링크");const input=document.createElement("input");input.readOnly=true;input.value=link;input.setAttribute("aria-label","주유소 공유 링크");label.append(input);sharing.append(label);
      const copy=text("button","링크 복사") as HTMLButtonElement;copy.type="button";copy.onclick=()=>{void navigator.clipboard?.writeText(link).then(()=>message("주유소 공유 링크를 복사했습니다.")).catch(()=>{input.focus();input.select();message("공유 링크를 길게 누르거나 선택해서 복사해 주세요.");});if(!navigator.clipboard){input.focus();input.select();message("공유 링크를 선택해서 복사해 주세요.");}};sharing.append(copy);}
    const maps=document.createElement("div");maps.className="map-apps";
    for(const target of stationMapLinks(selected)){const button=text("button",target.label) as HTMLButtonElement;button.type="button";button.onclick=()=>{void openExternal(target.url,target.fallback);};maps.append(button);}sharing.append(maps);
    const station=selected;const share=text("button","마이현대로 위치 공유") as HTMLButtonElement;share.type="button";share.onclick=()=>{void shareData(stationAppShare(station));};sharing.append(share);
    if(link){const general=text("button","다른 앱으로 공유") as HTMLButtonElement;general.type="button";general.onclick=()=>{void shareData({title:station.name,text:station.address??station.name,url:link});};sharing.append(general);}
    sharing.append(text("p","휴대폰 공유창에서 마이현대를 선택해 지도에서 위치를 확인하세요. 앱 설치·공유 지원 여부에 따라 표시되는 앱이 달라집니다.","muted"));panel.append(sharing);
}
function renderComparison() {
    const host = el("comparison");
    host.replaceChildren();
    if (!comparison) {
        host.textContent = "범위 선택 시 저장된 지역 통계를 조회합니다.";
        return;
    }
    const p = rowsFor(comparison, product);
    const c = comparison.collection;
    host.append(text("p", comparison.scope === "nationwide" ? "전국" : comparison.region?.label ?? "시군구 미확인"));
    if (c.status !== "ready" || comparison.region?.status === "unavailable") {
        host.append(text("p", "해당 범위의 통계가 제공되지 않았습니다."));
        return;
    }
    host.append(text("p", `평균 ${money(p?.average_price)}원/L · 최저 ${money(p?.minimum_price)}원/L`), text("p", `수집 ${collectedAt(c.generated_at)}`, "muted"));
    if (c.stale || c.update_pending || c.last_attempt_failed)
        host.append(text("p", "수집 지연 또는 새 통계 반영 대기 상태입니다.", "warning"));
    if (result?.collection.generated_at !== c.generated_at)
        host.append(text("p", "주변 검색과 집계 시각이 다르므로 같은 시점의 가격으로 비교할 수 없습니다.", "warning"));
    for (const station of p?.cheapest_stations ?? []) {
        const button = text("button", `최저가 ${station.name} · ${money(station.price)}원/L`) as HTMLButtonElement;
        button.type = "button";
        button.onclick = () => { const url = mapUrl(station); if (url)
            void openExternal(url); };
        host.append(button);
    }
    if (p?.truncated)
        host.append(text("p", `최저가 동률 ${p.cheapest_station_count}곳 중 대표 1곳 표시`, "muted"));
}
function renderMap() {
    if (el("map-pane").hidden || !query)
        return;
    try {
        map ??= new FuelMap(el("map"), () => { el("map-message").textContent = "배경지도를 불러오지 못했습니다. 가격·주소 목록은 계속 볼 수 있습니다."; el("tile-retry").hidden = false; }, query);
        map.update(query, displayedRows(), selected?.station_key ?? null, select);
    }
    catch {
        el("map-message").textContent = "이 환경에서는 지도를 표시하지 못했습니다. 목록에서 가격·주소를 확인해 주세요.";
    }
}
function syncView(){const visible=Boolean(query)&&preferMap;el("map-pane").hidden=!visible;el("list-view").setAttribute("aria-pressed",String(!visible));el("map-view").setAttribute("aria-pressed",String(visible));}
function render() { syncView();renderProducts(); renderSummary(); renderStations(); renderDetail(); renderComparison(); renderMap(); }
async function compare(scope: "nationwide" | "sigungu") {
    if (!connected || busy || !query)
        return;
    const epoch = ++comparisonEpoch;
    el("comparison").textContent = "지역 통계를 조회하고 있습니다.";
    try {
        const next = readResult(await app.callServerTool({ name: "get_regional_fuel_prices", arguments: { query: { scope, latitude: query.latitude, longitude: query.longitude, product_codes: PRODUCTS.map(([c]) => c) } } }, { timeout: 25000 }));
        if (epoch !== comparisonEpoch)
            return;
        comparison = next;
        renderComparison();
    }
    catch {
        if (epoch === comparisonEpoch)
            el("comparison").textContent = "지역 통계를 불러오지 못했습니다. 범위를 눌러 다시 시도해 주세요.";
    }
}
// MCP 호스트가 allow-forms를 주지 않아도 브리지 조회는 동작해야 한다.
el("controls").addEventListener("submit", event => event.preventDefault());
el("controls").addEventListener("keydown", event => { if (event.key === "Enter" && !event.isComposing && event.target instanceof HTMLInputElement && ["latitude","longitude"].includes(event.target.id)) {
    event.preventDefault();
    search();
} });
el("search").onclick = search;
el("refresh").onclick = search;
el("filter").addEventListener("input", () => { renderStations(); renderMap(); });
el("district").onclick = () => { void compare("sigungu"); };
el("national").onclick = () => { void compare("nationwide"); };
for (const view of ["list", "map"] as const)
    el(`${view}-view`).onclick = () => { preferMap=view==="map";syncView();renderMap(); };
el("tile-retry").onclick = () => { el("tile-retry").hidden = true; el("map-message").textContent = "배경지도를 다시 불러옵니다."; map?.retry(); };
el("full-fuel").onclick = () => { void openExternal(`https://fuel.digitie.mywire.org/?product=${product}`); };
el("locate").onclick = () => {
    if (!navigator.geolocation) {
        message("이 환경은 위치 요청을 지원하지 않습니다. 검색 위치에 좌표를 입력하거나 대화로 알려 주세요.", true);
        return;
    }
    const epoch = ++locationEpoch;
    el<HTMLButtonElement>("locate").disabled = true;
    message("기기의 위치 권한을 확인하고 있습니다.");
    navigator.geolocation.getCurrentPosition(position => { if (epoch !== locationEpoch)
        return; el<HTMLInputElement>("latitude").value=String(position.coords.latitude);el<HTMLInputElement>("longitude").value=String(position.coords.longitude);setBusy(false);search(); }, () => { if (epoch !== locationEpoch)
        return; setBusy(false); message("위치를 확인하지 못했습니다. 위치 권한을 허용하거나 좌표를 입력해 주세요.", true); }, { timeout: 10000, maximumAge: 0 });
};
app.addEventListener("toolinput", input => { const candidate = querySchema.safeParse(input.arguments?.query); if (candidate.success) {
    controller.invalidate();
    comparisonEpoch++;
    locationEpoch++;
    result = null;
    selected = null;
    comparison = null;
    fillQuery(candidate.data);
    setBusy(true);
    render();
} });
app.addEventListener("toolresult", next => { try {
    accept(readResult(next));
}
catch {
    setBusy(false);
    message("유가 응답을 확인하지 못했습니다. 다시 조회해 주세요.", true);
} });
app.addEventListener("toolcancelled", () => { controller.invalidate(); comparisonEpoch++; locationEpoch++; setBusy(false); message("조회가 취소됐습니다. 다시 조회할 수 있습니다."); });
app.addEventListener("hostcontextchanged", ctx => { if (ctx.theme)
    setTheme(ctx.theme); });
window.addEventListener("pagehide", () => { controller.invalidate(); comparisonEpoch++; locationEpoch++; map?.destroy(); });
render();
void app.connect().then(() => { connected = true; setTheme(app.getHostContext()?.theme ?? "light"); setBusy(false); }).catch(() => { message("ChatGPT의 MCP Apps 연결을 확인해 주세요. 검색 결과는 대화에서도 확인할 수 있습니다.", true); });
