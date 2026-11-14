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

it("고정 목록 모드는 목록 밖 입력을 값으로 만들지 않고 상한에서 남은 항목을 막는다", async () => {
  const changes: string[][] = [];
  function Filter() {
    const [values, setValues] = useState<string[]>(["alpha"]);
    return <MultiFilterCombobox ariaLabel="출처" options={["alpha", "beta", "gamma"]} values={values}
      onChange={(next) => { changes.push(next); setValues(next); }} placeholder="검색"
      allowCreate={false} maxSelected={2} emptyText="검색 결과가 없습니다." removeLabel={(value) => `${value} 선택 해제`} />;
  }
  render(<Filter />);
  const input = screen.getByRole("combobox") as HTMLInputElement;
  act(() => input.focus());
  fireEvent.change(input, { target: { value: "없는 값" } });
  await waitFor(() => expect(screen.getByRole("status").textContent).toBe("검색 결과가 없습니다."));
  expect(screen.queryByText(/추가:/)).toBeNull();
  fireEvent.keyDown(input, { key: "Enter" });
  expect(changes).toEqual([]);

  fireEvent.change(input, { target: { value: "beta" } });
  fireEvent.click(await screen.findByRole("option", { name: "beta" }));
  expect(changes.at(-1)).toEqual(["alpha", "beta"]);
  act(() => input.focus());
  fireEvent.change(input, { target: { value: "gamma" } });
  const gamma = await screen.findByRole("option", { name: "gamma" });
  expect(gamma.getAttribute("aria-disabled")).toBe("true");
  fireEvent.click(gamma);
  fireEvent.keyDown(input, { key: "ArrowDown" });
  fireEvent.keyDown(input, { key: "Enter" });
  expect(changes).toHaveLength(1);
  fireEvent.click(screen.getByRole("button", { name: "alpha 선택 해제" }));
  expect(changes.at(-1)).toEqual(["beta"]);
});
