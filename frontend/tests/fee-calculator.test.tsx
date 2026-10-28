import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { FeeCalculator } from "@/components/fee-calculator";
import type { Airport, FeeCalculationResponse } from "@/lib/types";

const airports: Airport[] = [
  {
    code: "GMP",
    name_ko: "김포국제공항",
    name_en: "Gimpo",
    source: "kac",
    parking_lots: [{ id: 1, source_lot_id: "gmp-1", legacy_source_lot_id: null, name: "국내선 제1주차장", terminal: "국내선", category: "short", is_active: true }]
  },
  {
    code: "ICN",
    name_ko: "인천국제공항",
    name_en: "Incheon",
    source: "incheon",
    parking_lots: [{ id: 2, source_lot_id: "icn-1", legacy_source_lot_id: null, name: "T1 단기주차장", terminal: "T1", category: "short", is_active: true }]
  }
];

describe("FeeCalculator", () => {
  test("uses the shared selection without duplicate controls and resets an old quote when the scope changes", async () => {
    const activeAirports = [{ ...airports[0], parking_lots: [...airports[0].parking_lots, { ...airports[0].parking_lots[0], id: 3, name: "국내선 제2주차장" }] }];
    const onCalculate = vi.fn(async () => ({ supported: true, airport_code: "GMP", vehicle_size: "small", total_fee: 1000, currency: "KRW", message: null, breakdown: [] }) as FeeCalculationResponse);
    const { rerender } = render(<FeeCalculator airports={activeAirports} initialAirportCode="GMP" initialParkingLotId={3} scopeControls={false} onCalculate={onCalculate} />);
    expect(screen.queryByLabelText("공항")).toBeNull(); expect(screen.queryByLabelText("주차장")).toBeNull();
    fireEvent.submit(screen.getByRole("button", { name: "요금 계산" }).closest("form")!);
    await waitFor(() => expect(onCalculate).toHaveBeenLastCalledWith(expect.objectContaining({ parking_lot_id: 3 })));
    await screen.findByText("₩1,000");
    rerender(<FeeCalculator airports={activeAirports} initialAirportCode="GMP" initialParkingLotId={null} scopeControls={false} onCalculate={onCalculate} />);
    expect(screen.queryByText("₩1,000")).toBeNull();
    fireEvent.submit(screen.getByRole("button", { name: "요금 계산" }).closest("form")!);
    await waitFor(() => expect(onCalculate).toHaveBeenLastCalledWith(expect.objectContaining({ parking_lot_id: 1 })));
  });

  test("discards a late quote when the user edits its input", async () => {
    let resolve!: (value: FeeCalculationResponse) => void;
    render(<FeeCalculator airports={airports} initialAirportCode="GMP" onCalculate={() => new Promise((done) => { resolve = done; })} />);
    fireEvent.submit(screen.getByRole("button", { name: "요금 계산" }).closest("form")!);
    fireEvent.change(screen.getByLabelText("차량 크기"), { target: { value: "large" } });
    await act(async () => resolve({ supported: true, airport_code: "GMP", vehicle_size: "small", total_fee: 9999, currency: "KRW", message: null, breakdown: [] }));
    expect(screen.queryByText("₩9,999")).toBeNull(); expect(screen.getByRole("button", { name: "요금 계산" })).not.toBeDisabled();
  });

  test("keeps the chosen second active parking lot after other fields change", async () => {
    const onCalculate = vi.fn(async () => ({ supported: true, airport_code: "GMP", vehicle_size: "small", total_fee: 1000, currency: "KRW", message: null, breakdown: [] }) as FeeCalculationResponse);
    render(<FeeCalculator airports={[{ ...airports[0], parking_lots: [...airports[0].parking_lots, { ...airports[0].parking_lots[0], id: 3, name: "국내선 제2주차장" }] }]} initialAirportCode="GMP" onCalculate={onCalculate} />);
    fireEvent.change(screen.getByLabelText("주차장"), { target: { value: "3" } });
    fireEvent.change(screen.getByLabelText("차량 크기"), { target: { value: "large" } });
    expect(screen.getByLabelText("주차장")).toHaveValue("3");
    fireEvent.submit(screen.getByRole("button", { name: "요금 계산" }).closest("form")!);
    await waitFor(() => expect(onCalculate).toHaveBeenCalledWith(expect.objectContaining({ parking_lot_id: 3 })));
  });

  test("defaults to 09:00 KST and submits the entered KST instant independently of browser timezone", async () => {
    const onCalculate = vi.fn(async () => ({ supported: true, airport_code: "GMP", vehicle_size: "small", total_fee: 1000, currency: "KRW", message: null, breakdown: [] }) as FeeCalculationResponse);
    render(<FeeCalculator airports={airports} initialAirportCode="GMP" onCalculate={onCalculate} />);
    expect((screen.getByLabelText("입차 시각") as HTMLInputElement).value).toMatch(/T09:00$/);
    fireEvent.change(screen.getByLabelText("입차 시각"), { target: { value: "2026-10-25T09:00" } });
    fireEvent.change(screen.getByLabelText("출차 시각"), { target: { value: "2026-10-25T15:00" } });
    fireEvent.submit(screen.getByRole("button", { name: "요금 계산" }).closest("form")!);
    await waitFor(() => expect(onCalculate).toHaveBeenCalledWith(expect.objectContaining({ entry_at: "2026-10-25T00:00:00.000Z", exit_at: "2026-10-25T06:00:00.000Z" })));
  });

  test("shows validation message when exit is earlier than entry", async () => {
    const user = userEvent.setup();

    render(
      <FeeCalculator
        airports={airports}
        initialAirportCode="GMP"
        onCalculate={async () =>
          ({
            supported: true,
            airport_code: "GMP",
            vehicle_size: "small",
            total_fee: 4000,
            currency: "KRW",
            message: null,
            breakdown: []
          }) as FeeCalculationResponse
        }
      />
    );

    await user.clear(screen.getByLabelText("입차 시각"));
    await user.type(screen.getByLabelText("입차 시각"), "2026-04-25T18:00");
    await user.clear(screen.getByLabelText("출차 시각"));
    await user.type(screen.getByLabelText("출차 시각"), "2026-04-25T12:00");
    await user.click(screen.getByRole("button", { name: "요금 계산" }));

    expect(screen.getByText("출차 시각은 입차 시각보다 늦어야 합니다.")).toBeInTheDocument();
  });

  test("shows unsupported message for incheon", async () => {
    const user = userEvent.setup();

    render(
      <FeeCalculator
        airports={airports}
        initialAirportCode="ICN"
        onCalculate={async () =>
          ({
            supported: false,
            airport_code: "ICN",
            vehicle_size: "small",
            total_fee: null,
            currency: "KRW",
            message: "인천공항은 현재 요금 계산을 지원하지 않습니다.",
            breakdown: []
          }) as FeeCalculationResponse
        }
      />
    );

    await user.click(screen.getByRole("button", { name: "요금 계산" }));
    expect(screen.getByText("인천공항은 현재 요금 계산을 지원하지 않습니다.")).toBeInTheDocument();
  });

  test("shows the official next action for a missing tariff and keeps rule details behind the info button", async () => {
    const user = userEvent.setup();
    const onCalculate = vi.fn(async () => ({ supported: false, airport_code: "GMP", vehicle_size: "small", total_fee: null,
      currency: "KRW", reason_code: "collection_disabled", message: "요금 수집이 꺼져 있습니다.",
      official_url: "https://www.airport.co.kr/gimpo/cms/frCon/index.do?CONTENTS_NO=2&MENU_ID=1360", breakdown: [] }) as FeeCalculationResponse);
    render(<FeeCalculator airports={airports} initialAirportCode="GMP" onCalculate={onCalculate} />);
    await user.click(screen.getByRole("button", { name: "요금 계산" }));
    expect(await screen.findByText("계산 불가")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "공항 공식 요금 안내 ↗" })).toHaveAttribute("target", "_blank");
    expect(screen.getByText("요금 수집이 꺼져 있습니다.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "주차요금 계산 안내" }));
    expect(await screen.findByText(/입출차 시각은 한국 시간/)).toBeInTheDocument();
  });
});
