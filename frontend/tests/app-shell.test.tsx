import { render, screen } from "@testing-library/react";

import { AppShell } from "@/components/app-shell";
import { DashboardProvider } from "@/lib/dashboard-context";
import type { Airport, CollectorStatusResponse, HolidaySummaryResponse, ParkingCurrentResponse } from "@/lib/types";

let currentPathname = "/";
vi.mock("next/navigation", () => ({
  usePathname: () => currentPathname,
}));

const airports: Airport[] = [
  {
    code: "GMP",
    name_ko: "Gimpo",
    name_en: "Gimpo",
    source: "kac",
    parking_lots: [],
  },
];

function buildCollectorStatus(): CollectorStatusResponse {
  return {
    scheduler_enabled: true,
    collect_interval_seconds: 300,
    manual_collect_enabled: false,
    manual_collect_min_interval_seconds: 300,
    client_mode: "live",
    enabled_sources: ["kac_parking"],
    data_go_kr_service_key_configured: true,
    supported_airport_codes: ["GMP"],
    latest_snapshot_observed_at: null,
    latest_snapshot_collected_at: null,
    earliest_snapshot_observed_at: null,
    manual_collect_available_at: null,
    manual_collect_blocked: false,
    upstream_rate_limited: false,
    upstream_rate_limited_until: null,
    last_run: null,
    recent_runs: [],
    effective_collect_interval_seconds: 180,
    scheduler_safety_buffer_seconds: 120,
  };
}

const holidaySummaryPayload: HolidaySummaryResponse = {
  generated_at: "2026-05-09T00:00:00.000Z",
  start_date: "2026-04-27",
  end_date: "2026-05-17",
  source: "sample_holiday_info",
  status: "sample",
  error_message: null,
  sentence: "",
  items: [],
};

const currentPayload: ParkingCurrentResponse = { generated_at: "2026-04-26T00:00:00.000Z", items: [] };

vi.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {},
  buildApiClient: () => ({
    getDashboardBootstrap: vi.fn(async () => ({
      airports,
      current: currentPayload,
      collector: buildCollectorStatus(),
      holidays: holidaySummaryPayload,
    })),
    getCollectorStatus: vi.fn(async () => buildCollectorStatus()),
  }),
}));

function renderShell(pathname: string) {
  currentPathname = pathname;
  return render(
    <DashboardProvider apiBaseUrl="http://localhost:8000">
      <AppShell>
        <div data-testid="page-content">content</div>
      </AppShell>
    </DashboardProvider>
  );
}

describe("AppShell", () => {
  test("marks the current route active in both the desktop and mobile nav", async () => {
    renderShell("/analytics");

    const analyticsLinks = await screen.findAllByRole("link", { name: "분석" });
    expect(analyticsLinks.length).toBeGreaterThan(0);
    for (const link of analyticsLinks) {
      expect(link).toHaveAttribute("aria-current", "page");
    }
    for (const link of screen.getAllByRole("link", { name: "현황" })) {
      expect(link).not.toHaveAttribute("aria-current");
    }
  });

  test("renders exactly the four read-only destinations and no backup entry (ADR-012)", async () => {
    renderShell("/");

    // Desktop top nav + mobile bottom tabbar each render the same 4 links.
    expect(await screen.findAllByRole("link", { name: "현황" })).toHaveLength(2);
    expect(screen.getAllByRole("link", { name: "분석" })).toHaveLength(2);
    expect(screen.getAllByRole("link", { name: "과거조회" })).toHaveLength(2);
    expect(screen.getAllByRole("link", { name: "요금계산" })).toHaveLength(2);
    expect(screen.getAllByRole("link")).toHaveLength(8);
    expect(screen.queryByRole("link", { name: "백업" })).toBeNull();
    expect(screen.queryByRole("button", { name: "더보기" })).toBeNull();
    expect(document.querySelector('a[href="/backup"]')).toBeNull();
  });

  test("renders the page content passed as children", async () => {
    renderShell("/");
    expect(await screen.findByTestId("page-content")).toBeInTheDocument();
  });
});
