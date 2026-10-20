// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { RailStationMapping } from "./rail-station-mapping";

const initial = {
  schema_version: 1 as const, revision: "a".repeat(64), catalog_sha256: "b".repeat(64), catalog_updated_at: null, mappings_updated_at: null,
  station_count: 2, mapped_count: 1, automatic_mapped_count: 1, manual_mapped_count: 0, unmatched_count: 1,
  stations: [
    { operator_code: "OP", operator_name: "서울교통공사", line_code: "L1", line_name: "1호선", station_code: "001", station_name: "서울역", rail_station_id: 1, rail_station_identity_key: "rail|seoul", match_method: "exact_identity" as const },
    { operator_code: "OP", operator_name: "서울교통공사", line_code: "L2", line_name: "2호선", station_code: "002", station_name: "미연결역", rail_station_id: null, rail_station_identity_key: null, match_method: "unmatched" as const },
  ],
  places: [
    { id: 1, identity_key: "rail|seoul", operator_name: "서울교통공사", line_name: "1호선", station_number: "001", station_name: "서울역" },
  ],
  mappings: [],
};
let root: Root | null;
let container: HTMLDivElement;
let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
  fetchMock = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify(initial), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(async () => { if (root) await act(async () => root!.unmount()); container.remove(); vi.unstubAllGlobals(); });
async function render() { await act(async () => { root!.render(<RailStationMapping />); }); }
async function click(node: HTMLElement | null) { expect(node).not.toBeNull(); await act(async () => node!.click()); }
function button(label: string) { return [...container.querySelectorAll<HTMLButtonElement>("button")].find((node) => node.textContent?.trim() === label); }

test("카탈로그 요약에서 미연결 역을 찾아 수동 매핑을 저장한다", async () => {
  const updated = { ...initial, revision: "c".repeat(64), mapped_count: 2, manual_mapped_count: 1, unmatched_count: 0,
    stations: initial.stations.map((station) => station.station_code === "002"
      ? { ...station, rail_station_id: 1, rail_station_identity_key: "rail|seoul", match_method: "manual" as const } : station),
    mappings: [{ operator_code: "OP", line_code: "L2", station_code: "002", rail_station_identity_key: "rail|seoul", note: "" }],
  };
  fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(updated), { status: 200 }));
  await render();
  expect(container.textContent).toContain("전체 역"); expect(container.textContent).toContain("미연결역");
  expect(container.textContent).not.toContain("서울역");
  const search = container.querySelector<HTMLInputElement>("#rail-place-search"); expect(search).not.toBeNull();
  await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(search, "서울"); search!.dispatchEvent(new Event("input", { bubbles: true })); });
  await click(container.querySelector('[role="option"][aria-selected="false"]'));
  await click(button("수동으로 연결") ?? null);
  const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
  expect(post).toBeDefined();
  expect(JSON.parse(post![1].body as string)).toMatchObject({ expected_revision: initial.revision,
    mappings: [{ operator_code: "OP", line_code: "L2", station_code: "002", rail_station_identity_key: "rail|seoul" }] });
  expect(container.textContent).toContain("수동 매핑을 저장했습니다.");
  expect(container.textContent).toContain("수동 연결");
});
