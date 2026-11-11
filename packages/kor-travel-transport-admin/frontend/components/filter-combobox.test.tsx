// @vitest-environment jsdom
import { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { FilterCombobox } from "./filter-combobox";

let root: Root, host: HTMLDivElement;
const options = [{ value: "SEOUL", label: "서울 · 서울" }, { value: "BUSAN", label: "부산 · 부산" }];
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => { callback(0); return 1; });
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { configurable: true, value: vi.fn() });
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
function input() { return host.querySelector<HTMLInputElement>('[role="combobox"]')!; }
async function key(value: string) { await act(async () => { input().dispatchEvent(new KeyboardEvent("keydown", { key: value, bubbles: true })); }); }
async function type(value: string) {
  await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input(), value); input().dispatchEvent(new Event("input", { bubbles: true })); });
}
test("단일 선택은 키보드로 한 역을 확정하고 닫으며 Escape로 확정 역을 해제하지 않는다", async () => {
  const changed = vi.fn();
  function Demo() { const [value, setValue] = useState<string[]>([]); return <FilterCombobox id="station" mode="single" options={options} value={value} onChange={v => { changed(v); setValue(v); }} placeholder="역 이름" />; }
  await act(async () => root.render(<Demo />));
  await key("ArrowDown"); await key("ArrowDown"); await key("Enter");
  expect(changed).toHaveBeenLastCalledWith(["BUSAN"]); expect(input().value).toBe("부산 · 부산");
  expect(input().getAttribute("aria-expanded")).toBe("false"); expect(document.querySelector('[role="listbox"]')).toBeNull();
  await key("ArrowDown"); await key("Escape");
  expect(changed).toHaveBeenCalledTimes(1); expect(input().value).toBe("부산 · 부산");
  await act(async () => host.querySelector<HTMLButtonElement>('[aria-label="부산 · 부산 선택 해제"]')!.click());
  expect(changed).toHaveBeenLastCalledWith([]); expect(input().value).toBe("");
});
test("제어 검색어 변경은 후보와 활성 옵션을 갱신하고 disabled 동안 팝업·aria를 닫는다", async () => {
  const changed = vi.fn();
  const render = (text: string, disabled = false) => root.render(<FilterCombobox id="controlled" mode="single" options={options} value={[]} onChange={changed} placeholder="역" inputValue={text} disabled={disabled} />);
  await act(async () => render("부산")); await key("ArrowDown");
  expect(document.querySelectorAll('[role="option"]')).toHaveLength(1);
  await act(async () => render("서울")); await key("Enter");
  expect(changed).toHaveBeenLastCalledWith(["SEOUL"]);
  await key("ArrowDown"); await act(async () => render("서울", true));
  expect(input().disabled).toBe(true); expect(input().getAttribute("aria-expanded")).toBe("false");
  expect(input().hasAttribute("aria-controls")).toBe(false); expect(input().hasAttribute("aria-activedescendant")).toBe(false);
  expect(document.querySelector('[role="listbox"]')).toBeNull();
});
test("다중 선택은 기존 칩·검색·선택 해제 계약을 유지한다", async () => {
  function Demo() { const [value, setValue] = useState<string[]>([]); return <FilterCombobox id="multi" options={options} value={value} onChange={setValue} placeholder="필터" />; }
  await act(async () => root.render(<Demo />)); await type("서울"); await key("Enter");
  expect(host.querySelector('[data-slot="combobox-chip"]')?.textContent).toContain("서울");
  expect(document.querySelector('[role="listbox"]')?.getAttribute("aria-multiselectable")).toBe("true");
  await act(async () => host.querySelector<HTMLButtonElement>('[aria-label="서울 · 서울 선택 해제"]')!.click());
  expect(host.querySelector('[data-slot="combobox-chip"]')).toBeNull();
});
