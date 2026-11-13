import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LegendOverlay } from "@/components/evilcharts/ui/echarts-legend";

test("클릭 범례는 Enter/Space로 작동하는 버튼이고 정적 범례는 탭 정지점을 만들지 않는다", async () => {
  const onToggle = vi.fn();
  const props = { seriesKeys: ["available"], config: { available: { label: "잔여" } }, variant: "circle" as const, align: "left" as const, verticalAlign: "bottom" as const, selectedKey: null, hoveredKey: null, onToggle, style: {} };
  const view = render(<LegendOverlay {...props} isClickable={false} />);
  expect(screen.queryByRole("button")).toBeNull();
  view.rerender(<LegendOverlay {...props} isClickable />);
  const button = screen.getByRole("button", { name: "잔여" });
  expect(button).toHaveAttribute("aria-pressed", "true");
  const user = userEvent.setup();
  button.focus();
  await user.keyboard("{Enter}");
  await user.keyboard(" ");
  expect(onToggle).toHaveBeenCalledTimes(2);
  expect(onToggle).toHaveBeenCalledWith("available");
  view.rerender(<LegendOverlay {...props} selectedKey="occupied" isClickable />);
  expect(screen.getByRole("button", { name: "잔여" })).toHaveAttribute("aria-pressed", "false");
});
