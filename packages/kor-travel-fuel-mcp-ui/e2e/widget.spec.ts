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

test("위치 없이 UI를 열고 동의 전에는 조회하지 않는다",async({page})=>{await page.goto("/");const app=page.frameLocator("#widget");await expect(app.locator(".station")).toHaveCount(20);
  await page.evaluate(()=>{const w=window as unknown as {sendResult:(r:unknown)=>void};w.sendResult({scope:"radius",collection:{status:"unavailable",reason:"location_required",generated_at:null,last_success_at:null,stale:false,update_pending:false,last_attempt_failed:false},products:[],latitude:null,longitude:null,radius_m:null});});
  await expect(app.locator("#notice")).toContainText("위치 권한");await expect(app.getByRole("button",{name:"현재 위치로 검색",exact:true})).toBeEnabled();await expect(app.getByRole("button",{name:"전국",exact:true})).toBeDisabled();expect(await page.evaluate(()=>((window as unknown as {calls:unknown[]}).calls).length)).toBe(0);
  await app.locator("#location summary").click();await app.locator("#latitude").fill("37.5");await app.locator("#longitude").fill("127");await app.getByRole("button",{name:"이 조건으로 조회"}).click();await expect(app.locator(".station")).toHaveCount(20);
});
