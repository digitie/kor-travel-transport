// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, test, vi } from "vitest";
import { LegendOverlay } from "./echarts-legend";
test("동작 범례는 native button과 선택 상태를 제공하고 정적 범례에는 탭 항목이 없다", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const rootNode = document.createElement("div"), root = createRoot(rootNode), onToggle = vi.fn();
  const props = { seriesKeys: ["fuel"], config: { fuel: { label: "유가" } }, variant: "circle" as const, align: "left" as const, verticalAlign: "bottom" as const, selectedKey: "fuel", hoveredKey: null, onToggle, style: {} };
  try {
    await act(async () => root.render(<LegendOverlay {...props} isClickable={false} />));
    expect(rootNode.querySelector("button,[tabindex]")).toBeNull();
    await act(async () => root.render(<LegendOverlay {...props} isClickable />));
    const button = rootNode.querySelector("button")!;
    expect(button.type).toBe("button"); expect(button.getAttribute("aria-pressed")).toBe("true");
    await act(async () => root.render(<LegendOverlay {...props} selectedKey={null} isClickable />));
    expect(rootNode.querySelector("button")?.getAttribute("aria-pressed")).toBe("true");
    await act(async () => button.click()); expect(onToggle).toHaveBeenCalledWith("fuel");
  } finally { await act(async () => root.unmount()); }
});
