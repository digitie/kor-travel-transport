// @vitest-environment jsdom
import { useState } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { MultiFilterCombobox } from "./multi-filter-combobox";

// jsdom은 레이아웃·관찰자를 구현하지 않으므로 필요한 최소 대역만 둔다.
if (typeof ResizeObserver === "undefined") {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}
if (!HTMLElement.prototype.scrollIntoView) {
  HTMLElement.prototype.scrollIntoView = () => {};
}

afterEach(cleanup);

it("Radix 목록은 입력 포커스와 키보드 선택·Escape 계약을 유지한다", async () => {
  function Filter() {
    const [values, setValues] = useState<string[]>([]);
    return <MultiFilterCombobox ariaLabel="제공처" options={["alpha", "beta"]} values={values} onChange={setValues} placeholder="검색" />;
  }
  render(<Filter />);
  const input = screen.getByRole("combobox") as HTMLInputElement;
  act(() => input.focus());
  await waitFor(() => expect(screen.getByRole("listbox")).toBeTruthy());
  expect(document.activeElement).toBe(input);
  fireEvent.keyDown(input, { key: "ArrowDown" });
  fireEvent.keyDown(input, { key: "Enter" });
  expect(screen.getByRole("button", { name: "alpha 제거" })).toBeTruthy();
  expect(document.activeElement).toBe(input);
  fireEvent.keyDown(input, { key: "Escape" });
  await waitFor(() => expect(screen.queryByRole("listbox")).toBeNull());
  expect(document.activeElement).toBe(input);
});
