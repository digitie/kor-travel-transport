// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { MultiSearch } from "./journey-controls";

beforeEach(() => { Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true }); });
afterEach(() => vi.unstubAllGlobals());

test("비교 최대 5곳에 도달해도 여섯째 상세는 선택 변경 없이 열 수 있다", async () => {
  const options = Array.from({ length: 6 }, (_, index) => ({ id: String(index), name: `항구${index + 1}` }));
  const select = vi.fn(), inspect = vi.fn();
  const container = document.createElement("div"); document.body.append(container); const root = createRoot(container);
  try {
    await act(async () => root.render(<MultiSearch label="항구 검색" query="" onQuery={() => {}} options={options} selected={options.slice(0, 5)} onSelect={select} onInspect={inspect} />));
    const choices = container.querySelectorAll('[role="checkbox"]');
    expect(choices).toHaveLength(6);
    expect(choices[5].getAttribute("aria-disabled")).toBe("true");
    const button = container.querySelector<HTMLButtonElement>('[aria-label="항구6 상세 보기"]')!;
    expect(button.disabled).toBe(false);
    await act(async () => button.click());
    expect(inspect).toHaveBeenCalledWith("5"); expect(select).not.toHaveBeenCalled();
    expect(container.textContent).toContain("5/5곳 선택");
  } finally { await act(async () => root.unmount()); container.remove(); }
});
