import { test, expect } from "@playwright/test";
for (const width of [320, 375, 414, 768, 1440])
    test(`실제 MCP Apps 브리지와 반응형 ${width}px`, async ({ page }) => {
        await page.setViewportSize({ width, height: 1100 });
        const errors: string[] = [];
        page.on("pageerror", e => errors.push(e.message));
        await page.route("https://tile.openstreetmap.org/**", route => route.fulfill({ contentType: "image/png", body: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=", "base64") }));
        await page.goto("/");
        const app = page.frameLocator("#widget");
        await expect(app.getByRole("button", { name: "다시 조회", exact: true })).toBeEnabled();
        await expect(app.locator(".station")).toHaveCount(20);
        await expect(app.locator("#result-caption")).toContainText("전체 42곳 중 20곳");
        await app.getByRole("button", { name: "경유", exact: true }).click();
        await expect(app.getByRole("heading", { name: "경유 주유소" })).toBeVisible();
        await app.locator("#radius").selectOption("10000");
        await app.getByRole("button", { name: "이 조건으로 조회" }).click();
        await expect(app.locator("#result-caption")).toContainText("10000m");
        await app.getByRole("button", { name: "전국", exact: true }).click();
        await expect(app.locator("#comparison")).toContainText("평균");
        await app.getByRole("button", { name: "지도", exact: true }).click();
        await expect(app.locator("#map .leaflet-tile-loaded").first()).toBeVisible();
        await expect(app.locator("#map .fuel-marker").first()).toBeVisible();
        expect(await app.locator("#map .fuel-marker").count()).toBeLessThan(20);
        await app.locator(".station").first().click();
        await expect(app.locator("#detail")).toContainText("금남주유소");
        await app.getByRole("button", { name: "큰 지도에서 위치 보기" }).click();
        await expect.poll(() => page.evaluate(() => ((window as unknown as {
            opened: string[];
        }).opened).length)).toBe(1);
        await app.locator("#detail").getByRole("button", { name: "닫기", exact: true }).click();
        await expect(app.locator(".station").first()).toBeFocused();
        const overflow = await app.locator("body").evaluate(node => node.scrollWidth > window.innerWidth + 1);
        expect(overflow).toBe(false);
        expect(errors).toEqual([]);
        await page.screenshot({ path: `test-results/fuel-mcp-${width}.png`, fullPage: true });
    });
test("불신 입력·원문 오류·재시도·필터", async ({ page }) => {
    await page.goto("/");
    const app = page.frameLocator("#widget");
    await expect(app.locator(".station")).toHaveCount(20);
    await app.locator("#filter").fill("없는이름");
    await expect(app.locator("#stations")).toContainText("일치하는 주유소가 없습니다");
    await app.locator("#filter").clear();
    await page.evaluate(() => { const w = window as unknown as {
        sample: () => any;
        sendResult: (r: any) => void;
    }; const r = w.sample(); r.products[0].ranked_stations[0].name = '<img src=x onerror="window.parent.hacked=1">'; w.sendResult(r); });
    await expect(app.locator(".station").first()).toContainText("<img src=x");
    expect(await app.locator(".station img").count()).toBe(0);
    await page.evaluate(() => { (window as unknown as {
        failNext: boolean;
    }).failNext = true; });
    await app.getByRole("button", { name: "다시 조회", exact: true }).click();
    await expect(app.locator("#notice")).toContainText("조회에 실패");
    await expect(app.locator("#notice")).not.toContainText("private");
    await expect(app.locator(".station")).toHaveCount(20);
    await app.getByRole("button", { name: "다시 조회", exact: true }).click();
    await expect(app.locator("#notice")).toContainText("성공 수집분");
});
test("수집 지연·미제공·거리 정렬", async ({ page }) => {
    await page.goto("/");
    const app = page.frameLocator("#widget");
    await expect(app.locator(".station")).toHaveCount(20);
    await app.locator("#sort").selectOption("distance");
    await app.getByRole("button", { name: "이 조건으로 조회" }).click();
    await expect(app.locator("#result-caption")).toContainText("거리순");
    await page.evaluate(() => { const w = window as unknown as {
        sample: () => any;
        sendResult: (r: any) => void;
    }; const r = w.sample(); r.collection.stale = true; r.collection.update_pending = true; w.sendResult(r); });
    await expect(app.locator("#notice")).toContainText("수집 지연");
    await expect(app.locator("#notice")).toContainText("반영 대기");
    await page.evaluate(() => { const w = window as unknown as {
        sample: () => any;
        sendResult: (r: any) => void;
    }; const r = w.sample(); for (const p of r.products) {
        p.station_count = 0;
        p.average_price = null;
        p.minimum_price = null;
        p.cheapest_station_count = 0;
        p.ranked_stations = [];
        p.cheapest_stations = [];
    } w.sendResult(r); });
    await expect(app.locator("#stations")).toContainText("이 반경에 판매 가격이 확인된 주유소가 없습니다");
    await expect(app.locator("#summary")).toContainText("미제공");
    await expect(app.locator("#summary")).not.toContainText("0원");
});

test("위치 없이 UI를 열고 동의 전에는 조회하지 않는다",async({page})=>{
  await page.route("https://tile.openstreetmap.org/**",route=>route.fulfill({contentType:"image/png",body:Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=","base64")}));
  await page.goto("/");const app=page.frameLocator("#widget");await expect(app.locator(".station")).toHaveCount(20);
  await app.getByRole("button",{name:"지도",exact:true}).click();await expect(app.locator("#map .fuel-marker").first()).toBeVisible();
  await page.evaluate(()=>{const w=window as unknown as {sendResult:(r:unknown)=>void};w.sendResult({scope:"radius",collection:{status:"unavailable",reason:"location_required",generated_at:null,last_success_at:null,stale:false,update_pending:false,last_attempt_failed:false},products:[],latitude:null,longitude:null,radius_m:null});});
  await expect(app.locator("#map .leaflet-marker-icon")).toHaveCount(0);await expect(app.locator("#map-pane")).toBeHidden();await expect(app.locator("#timestamp")).toHaveText("수집 시각 미제공");await expect(app.getByRole("button",{name:"지도",exact:true})).toBeDisabled();
  await expect(app.locator("#notice")).toContainText("위치 권한");await expect(app.getByRole("button",{name:"현재 위치로 검색",exact:true})).toBeEnabled();await expect(app.getByRole("button",{name:"전국",exact:true})).toBeDisabled();expect(await page.evaluate(()=>((window as unknown as {calls:unknown[]}).calls).length)).toBe(0);
  await app.locator("#location summary").click();await app.locator("#latitude").fill("37.5");await app.locator("#longitude").fill("127");await app.getByRole("button",{name:"이 조건으로 조회"}).click();await expect(app.locator(".station")).toHaveCount(20);
});


test("키보드 위치 펼침·위치 요청·좌표 Enter·유종 포커스",async({page})=>{
 await page.addInitScript(()=>{Object.defineProperty(navigator,"geolocation",{value:{getCurrentPosition:(_success:unknown,failed:(e:unknown)=>void)=>{(window as any).gpsAttempts=((window as any).gpsAttempts??0)+1;failed({code:1});}},configurable:true});});
 await page.goto("/");const app=page.frameLocator("#widget");await expect(app.locator(".station")).toHaveCount(20);
 const summary=app.locator("#location summary");await summary.focus();await summary.press("Enter");await expect(app.locator("#location")).toHaveAttribute("open","");
 const locate=app.getByRole("button",{name:"현재 위치로 검색",exact:true});await locate.focus();await locate.press("Enter");await expect(app.locator("#notice")).toContainText("위치를 확인하지 못했습니다");expect(await app.locator("body").evaluate(()=>((window as any).gpsAttempts))).toBe(1);
 await app.locator("#latitude").fill("37.6");await app.locator("#longitude").fill("127");await app.locator("#longitude").press("Enter");await expect.poll(()=>page.evaluate(()=>((window as any).calls.at(-1)?.arguments.query.latitude))).toBe(37.6);
 const diesel=app.getByRole("button",{name:"경유",exact:true});await diesel.focus();await diesel.press("Enter");await expect(diesel).toBeFocused();await expect(diesel).toHaveAttribute("aria-pressed","true");await diesel.press("Space");await expect(diesel).toBeFocused();
});

test("위치 획득은 선택 조건을 보존하고 실패 시 적용 위치를 바꾸지 않는다",async({page})=>{
 await page.addInitScript(()=>{Object.defineProperty(navigator,"geolocation",{value:{getCurrentPosition:(success:(p:unknown)=>void)=>success({coords:{latitude:37.6,longitude:127.1}})},configurable:true});});
 await page.goto("/");const app=page.frameLocator("#widget");await expect(app.locator(".station")).toHaveCount(20);
 await app.locator("#radius").selectOption("10000");await app.locator("#sort").selectOption("distance");await page.evaluate(()=>{(window as any).failNext=true;});
 await app.getByRole("button",{name:"현재 위치로 검색",exact:true}).click();await expect(app.locator("#notice")).toContainText("이전 결과");
 expect(await page.evaluate(()=>((window as any).calls.at(-1).arguments.query))).toMatchObject({latitude:37.6,longitude:127.1,radius_m:10000,sort_by:"distance"});
 await expect(app.locator("#radius")).toHaveValue("10000");await expect(app.locator("#sort")).toHaveValue("distance");await expect(app.locator("#result-caption")).toContainText("반경 5000m");await app.locator("#filter").fill("금남");
 await app.getByRole("button",{name:"현재 위치 시군구",exact:true}).click();await expect.poll(()=>page.evaluate(()=>((window as any).calls.at(-1)?.arguments.query.scope))).toBe("sigungu");
 expect(await page.evaluate(()=>((window as any).calls.at(-1).arguments.query))).toMatchObject({latitude:37.5,longitude:127});
});

test("단일 유종 응답은 해당 유종을 처음부터 선택한다",async({page})=>{
 await page.goto("/");const app=page.frameLocator("#widget");await expect(app.locator(".station")).toHaveCount(20);
 for(const [code,label] of [["K015","LPG"],["D047","경유"]]){await page.evaluate(code=>{const w=window as any;const r=w.sample();r.products=r.products.filter((p:any)=>p.product_code===code);w.sendResult(r);},code);await expect(app.getByRole("heading",{name:`${label} 주유소`,exact:true})).toBeVisible();await expect(app.getByRole("button",{name:label,exact:true})).toHaveAttribute("aria-pressed","true");await expect(app.locator(".station")).toHaveCount(20);}
});


test("등유 없는 목록과 상세 공유·목적지 앱·복사 거부 복구",async({page})=>{
 await page.addInitScript(()=>{Object.defineProperty(navigator,"clipboard",{configurable:true,value:{writeText:async(value:string)=>{(window as any).copied=value;}}});Object.defineProperty(navigator,"share",{configurable:true,value:async(value:unknown)=>{const mode=(window as any).shareMode;if(mode==="cancel")throw new DOMException("cancel","AbortError");if(mode==="error")throw new Error("share_denied");(window as any).shared=value;}});});
 await page.goto("/");const app=page.frameLocator("#widget");await expect(app.locator(".station")).toHaveCount(20);await expect(app.locator("#products button")).toHaveCount(4);await expect(app.getByRole("button",{name:"등유",exact:true})).toHaveCount(0);
 await app.locator(".station").first().click();await app.getByRole("button",{name:"링크 복사",exact:true}).click();await expect(app.locator("#notice")).toContainText("복사했습니다");
 const link=await app.locator("body").evaluate(()=>((window as any).copied));const url=new URL(link);expect(url.origin).toBe("https://fuel.digitie.mywire.org");expect(url.searchParams.get("station")).toBe("1");expect(url.searchParams.get("latitude")).toBe("37.501");expect(url.searchParams.has("radius_m")).toBe(false);
 await app.getByRole("button",{name:"네이버지도",exact:true}).click();await expect.poll(()=>page.evaluate(()=>((window as any).opened.length))).toBe(1);const opened=await page.evaluate(()=>((window as any).opened.at(-1)));const nav=new URL(opened);expect(nav.pathname).toBe("/car");expect(nav.searchParams.get("dlat")).toBe("37.501");
 for(const failure of ["reject","error"]){const before=await page.evaluate(()=>((window as any).opened.length));await page.evaluate(failure=>{(window as any).openFailures=[failure];},failure);await app.getByRole("button",{name:"네이버지도",exact:true}).click();await expect.poll(()=>page.evaluate(()=>((window as any).opened.length))).toBe(before+2);expect(await page.evaluate(()=>((window as any).opened.at(-1)))).toMatch(/^https:\/\/map.naver.com\/p\/search\//);}
 await page.evaluate(()=>{(window as any).openFailures=["reject","error"];});await app.getByRole("button",{name:"네이버지도",exact:true}).click();await expect(app.locator("#notice")).toContainText("외부 화면을 열지 못했습니다");

 await app.getByRole("button",{name:"마이현대로 위치 공유",exact:true}).click();expect(await app.locator("body").evaluate(()=>((window as any).shared.url))).toContain("https://map.kakao.com/link/map/");await expect(app.locator("#notice")).toContainText("공유창에 주유소 정보를 전달");await app.getByRole("button",{name:"다른 앱으로 공유",exact:true}).click();expect(await app.locator("body").evaluate(()=>((window as any).shared.url))).toBe(link);
 for(const mode of ["cancel","error","cancel"]){await app.locator("body").evaluate((_node,mode)=>{(window as any).shareMode=mode;},mode);await app.getByRole("button",{name:"마이현대로 위치 공유",exact:true}).click();await expect(app.locator("#notice")).toContainText(mode==="cancel"?"공유를 취소했습니다":"공유창을 열 수 없습니다");}

 await app.locator("body").evaluate(()=>{Object.defineProperty(navigator,"clipboard",{configurable:true,value:{writeText:async()=>{throw new DOMException("denied","NotAllowedError");}}});});await app.getByRole("button",{name:"링크 복사",exact:true}).click();await expect(app.locator("#notice")).toContainText("선택해서 복사");await expect(app.getByRole("textbox",{name:"주유소 공유 링크",exact:true})).toBeFocused();
});
