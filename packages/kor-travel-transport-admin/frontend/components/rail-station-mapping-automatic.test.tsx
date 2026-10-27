// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { RailStationMapping } from "./rail-station-mapping";

const revision = "a".repeat(64), candidate = "b".repeat(64);
const code = { operator_code: "OP", line_code: "L1", station_code: "001" };
const initial = { schema_version: 1, revision, catalog_sha256: candidate, catalog_updated_at: null, mappings_updated_at: null,
  station_count: 1, mapped_count: 0, automatic_mapped_count: 0, manual_mapped_count: 0, unmatched_count: 1,
  stations: [{ ...code, operator_name: "기관", line_name: "1호선", station_name: "서울역", rail_station_id: null, rail_station_identity_key: null, match_method: "unmatched" }],
  places: [{ id: 1, identity_key: "rail|seoul", operator_name: "기관", line_name: "1호선", station_number: "001", station_name: "서울역" }], mappings: [] };
const preview = { schema_version: 1, generated_at: "2026-10-27T10:00:00Z", expected_revision: revision, candidate_revision: candidate, catalog_sha256: candidate,
  before: { station_count: 1, mapped_count: 0, automatic_mapped_count: 0, manual_mapped_count: 0, unmatched_count: 1 },
  after: { station_count: 1, mapped_count: 1, automatic_mapped_count: 1, manual_mapped_count: 0, unmatched_count: 0 }, has_changes: true, can_apply: true,
  changes: [{ ...code, operator_name: "기관", line_name: "1호선", station_name: "서울역", change_type: "added", before: { rail_station_id: null, rail_station_identity_key: null, match_method: "unmatched" }, after: { rail_station_id: 1, rail_station_identity_key: "rail|seoul", match_method: "exact_identity" } }], manual_conflicts: [], blockers: [] };
const applied = { schema_version: 1, status: "applied", previous_revision: revision, revision: candidate, changed_link_count: 1, summary: preview.after };
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
function deferred<T>() { let resolve!: (value: T) => void; return { promise: new Promise<T>(done => { resolve = done; }), resolve: (v: T) => resolve(v) }; }
let root: Root; let host: HTMLDivElement; let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => { (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
  fetchMock = vi.fn().mockResolvedValueOnce(json(initial)); vi.stubGlobal("fetch", fetchMock);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.unstubAllGlobals(); });
const render = async () => { await act(async () => root.render(<RailStationMapping />)); };
function button(label: string) { const node = [...document.querySelectorAll<HTMLButtonElement>("button")].find(x => x.textContent?.trim() === label); expect(node, label).toBeDefined(); return node!; }
async function click(label: string) { await act(async () => button(label).click()); }
async function input(selector: string, value: string) { const node = document.querySelector<HTMLInputElement>(selector)!; await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(node, value); node.dispatchEvent(new Event("input", { bubbles: true })); }); }
const posts = () => fetchMock.mock.calls.filter(([, init]) => init?.method === "POST");

test("자동 미리보기는 변경행과 전후 건수를 표시하고 돌아가기는 쓰지 않는다", async () => {
  fetchMock.mockResolvedValueOnce(json(preview)); await render(); await click("자동 연결 미리보기");
  const dialog = document.querySelector('[role="dialog"]'); expect(dialog?.textContent).toContain("미연결 → rail|seoul");
  expect(dialog?.textContent).toContain("자동 연결"); expect(dialog?.textContent).toContain("0 → 1");
  await click("돌아가기"); expect(posts()).toHaveLength(0);
});
test("적용은 두 revision만 보내고 최신 목록을 갱신한다", async () => {
  fetchMock.mockResolvedValueOnce(json(preview)).mockResolvedValueOnce(json(applied)).mockResolvedValueOnce(json({ ...initial, revision: candidate }));
  await render(); await click("자동 연결 미리보기"); await click("적용");
  expect(posts()).toHaveLength(1); expect(JSON.parse(posts()[0][1].body)).toEqual({ expected_revision: revision, candidate_revision: candidate });
  expect(host.textContent).toContain("자동 연결을 적용했습니다"); expect(fetchMock.mock.calls).toHaveLength(4);
});
test("선택 target과 note 초안은 미리보기로 버리지 않는다", async () => {
  await render(); await input("#rail-place-search", "서울"); await act(async () => document.querySelector<HTMLButtonElement>('.rail-map-candidates button')!.click());
  await input(".rail-map-note input", "검토 중인 근거"); expect(button("자동 연결 미리보기").disabled).toBe(true);
  expect((document.querySelector('.rail-map-note input') as HTMLInputElement).value).toBe("검토 중인 근거"); expect(fetchMock.mock.calls).toHaveLength(1);
});
test("수동 저장 중에는 자동 미리보기를 요청하지 않는다", async () => {
  const wait = deferred<Response>(); fetchMock.mockReturnValueOnce(wait.promise);
  await render(); await input("#rail-place-search", "서울"); await act(async () => document.querySelector<HTMLButtonElement>('.rail-map-candidates button')!.click());
  await click("수동으로 연결"); expect(button("자동 연결 미리보기").disabled).toBe(true);
  await act(async () => wait.resolve(json(initial))); expect(posts()).toHaveLength(1);
});
test("409는 자동 적용 재시도 없이 새 미리보기를 요구한다", async () => {
  fetchMock.mockResolvedValueOnce(json(preview)).mockResolvedValueOnce(json({ detail: "후보가 변경되었습니다." }, 409));
  await render(); await click("자동 연결 미리보기"); await click("적용");
  expect(document.querySelector('[role="dialog"]')?.textContent).toContain("새 미리보기"); expect(button("적용").disabled).toBe(true); expect(posts()).toHaveLength(1);
});
test("503은 연결0건으로 위장하지 않고 오류를 표시한다", async () => {
  fetchMock.mockResolvedValueOnce(json({ detail: "카탈로그 미준비" }, 503)); await render(); await click("자동 연결 미리보기");
  const dialog = document.querySelector('[role="dialog"]'); expect(dialog?.textContent).toContain("카탈로그 미준비"); expect(dialog?.querySelector('[aria-label="연결 변경 건수"]')).toBeNull(); expect(button("적용").disabled).toBe(true);
});
test("충돌과 차단사유를 표시하고 can_apply=false는 적용하지 않는다", async () => {
  fetchMock.mockResolvedValueOnce(json({ ...preview, can_apply: false, manual_conflicts: [{ ...code, rail_station_identity_key: "rail|seoul", reason: "manual_target_reserved", reserved_by: { ...code, station_code: "002" } }], blockers: [{ code: "catalog", message: "공식 기준정보 확인 필요" }] }));
  await render(); await click("자동 연결 미리보기"); expect(button("적용").disabled).toBe(true); expect(document.querySelector('[role="dialog"]')?.textContent).toContain("수동 대상 예약"); expect(document.querySelector('[role="dialog"]')?.textContent).toContain("공식 기준정보 확인 필요");
});
test("변경 없음은 적용하지 않으며 unchanged 성공도 새 상태를 조회한다", async () => {
  fetchMock.mockResolvedValueOnce(json({ ...preview, has_changes: false, changes: [] })); await render(); await click("자동 연결 미리보기"); expect(button("적용").disabled).toBe(true); expect(posts()).toHaveLength(0);
});
test("unchanged와 방법만 바뀐0FK 성공도 정상 완료 후 목록을 다시 읽는다", async () => {
  fetchMock.mockResolvedValueOnce(json(preview)).mockResolvedValueOnce(json({ ...applied, status: "unchanged", changed_link_count: 0 })).mockResolvedValueOnce(json(initial));
  await render(); await click("자동 연결 미리보기"); await click("적용"); expect(host.textContent).toContain("변경 없이 확인됐습니다"); expect(posts()).toHaveLength(1); expect(fetchMock.mock.calls).toHaveLength(4);
});
test("수동 충돌로 effective 변경0건이어도 후보 갱신을 적용할 수 있다", async () => {
  fetchMock.mockResolvedValueOnce(json({ ...preview, after: preview.before, changes: [], manual_conflicts: [{ ...code, rail_station_identity_key: "rail|seoul", reason: "manual_target_reserved", reserved_by: { ...code, station_code: "002" } }] }))
    .mockResolvedValueOnce(json({ ...applied, changed_link_count: 0 })).mockResolvedValueOnce(json(initial));
  await render(); await click("자동 연결 미리보기"); const dialog = document.querySelector('[role=dialog]')!;
  expect(dialog.textContent).toContain("연결 대상 변경 없이 자동 후보를 갱신합니다"); expect(dialog.textContent).not.toContain("변경할 연결이 없습니다"); expect(dialog.textContent).toContain("수동 대상 예약"); expect(button("적용").disabled).toBe(false);
  await click("적용"); expect(host.textContent).toContain("실제 역 연결 0건 변경"); expect(posts()).toHaveLength(1);
});
test("방법만 바뀐 행은 같은 대상의 전후 연결기준을 보여주고0FK성공을 허용한다", async () => {
  fetchMock.mockResolvedValueOnce(json({ ...preview, changes: [{ ...preview.changes[0], change_type: "method_changed", before: { ...preview.changes[0].after }, after: { ...preview.changes[0].after, match_method: "station_number_and_name" } }] }))
    .mockResolvedValueOnce(json({ ...applied, changed_link_count: 0 })).mockResolvedValueOnce(json(initial));
  await render(); await click("자동 연결 미리보기"); expect(document.querySelector('[role=dialog]')?.textContent).toContain("기준정보 일치 → 역 번호·이름 일치"); await click("적용"); expect(host.textContent).toContain("실제 역 연결 0건 변경");
});
test("note만 수정한 기존 수동 초안도 보호한다", async () => {
  fetchMock.mockReset().mockResolvedValueOnce(json({ ...initial, stations: [{ ...initial.stations[0], match_method: "manual", rail_station_id: 1, rail_station_identity_key: "rail|seoul" }], mappings: [{ ...code, rail_station_identity_key: "rail|seoul", note: "저장된 근거" }] }));
  await render(); await act(async () => document.querySelector<HTMLInputElement>('input[type=checkbox]')!.click());
  await input(".rail-map-note input", "새 근거"); expect(button("자동 연결 미리보기").disabled).toBe(true); expect(posts()).toHaveLength(0);
});
test("적용 중 돌아가기와 중복 적용을 막고 실패 후에는 새 미리보기만 허용한다", async () => {
  const wait = deferred<Response>(); fetchMock.mockResolvedValueOnce(json(preview)).mockReturnValueOnce(wait.promise);
  await render(); await click("자동 연결 미리보기"); await click("적용"); expect(button("적용 중…").disabled).toBe(true); expect(button("돌아가기").disabled).toBe(true);
  await act(async () => document.querySelector('[role=dialog]')!.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })));
  expect(document.querySelector('[role=dialog]')).not.toBeNull(); expect(posts()).toHaveLength(1);
  await act(async () => wait.resolve(json({ detail: "카탈로그 갱신 중" }, 503))); expect(button("적용").disabled).toBe(true); expect(button("새 미리보기").disabled).toBe(false);
});
test("적용 후 검색어와 수동/전체 보기 설정을 유지한다", async () => {
  fetchMock.mockResolvedValueOnce(json(preview)).mockResolvedValueOnce(json(applied)).mockResolvedValueOnce(json({ ...initial, revision: candidate }));
  await render(); await input("#rail-station-filter", "서울"); await act(async () => document.querySelector<HTMLInputElement>('input[type=checkbox]')!.click());
  await click("자동 연결 미리보기"); await click("적용"); expect((document.querySelector("#rail-station-filter") as HTMLInputElement).value).toBe("서울"); expect(document.querySelector<HTMLInputElement>('input[type=checkbox]')!.checked).toBe(false);
});
test("unmount는 진행중 미리보기를 취소하고 늦은 성공을 반영하지 않는다", async () => {
  const wait = deferred<Response>(); fetchMock.mockReturnValueOnce(wait.promise); await render(); await click("자동 연결 미리보기");
  const signal = fetchMock.mock.calls[1][1].signal as AbortSignal; await act(async () => root.unmount()); expect(signal.aborted).toBe(true); await act(async () => wait.resolve(json(preview)));
  root = createRoot(host); expect(document.querySelector('[role=dialog]')).toBeNull(); expect(posts()).toHaveLength(0);
});
test("닫은 미리보기의 늦은 응답은 다시 연 미리보기를 덮지 않는다", async () => {
  const wait = deferred<Response>(); fetchMock.mockReturnValueOnce(wait.promise).mockResolvedValueOnce(json({ ...preview, has_changes: false, changes: [] }));
  await render(); await click("자동 연결 미리보기"); await click("돌아가기"); await click("자동 연결 미리보기");
  await act(async () => wait.resolve(json(preview))); expect(button("적용").disabled).toBe(true); expect(document.querySelector('[role="dialog"]')?.textContent).toContain("변경할 연결이 없습니다");
});
test("적용 성공 후 이전 GET이 늦게 도착해 revision을 되돌리지 않는다", async () => {
  const wait = deferred<Response>(); fetchMock.mockReturnValueOnce(wait.promise).mockResolvedValueOnce(json(preview)).mockResolvedValueOnce(json(applied)).mockResolvedValueOnce(json({ ...initial, revision: candidate, unmatched_count: 77 }));
  await render(); await click("새로고침");
  // 갱신 중에는 자동 요청을 막고 기존 목록을 유지한다.
  expect(button("자동 연결 미리보기").disabled).toBe(true);
  await act(async () => wait.resolve(json(initial))); await click("자동 연결 미리보기"); await click("적용");
  expect(host.textContent).toContain("77"); expect(posts()).toHaveLength(1);
});

test("단일 미연결 역의 수동409 뒤 명시적 초안 취소로 최신revision을 읽고 다시 저장한다", async () => {
  const fresh = { ...initial, revision: "c".repeat(64) };
  fetchMock.mockResolvedValueOnce(json({ detail: "새로고침 후 다시 저장하세요." }, 409)).mockResolvedValueOnce(json(fresh)).mockResolvedValueOnce(json({ ...fresh, revision: "d".repeat(64) }));
  await render(); await input("#rail-place-search", "서울"); await act(async () => document.querySelector<HTMLButtonElement>('.rail-map-candidates button')!.click()); await input(".rail-map-note input", "검토한 연결 근거"); await click("수동으로 연결");
  expect(button("새로고침").disabled).toBe(true); expect((document.querySelector('.rail-map-note input') as HTMLInputElement).value).toBe("검토한 연결 근거"); expect(posts()).toHaveLength(1);
  await click("초안 취소 후 새로고침"); expect(posts()).toHaveLength(1); expect(document.querySelector('.rail-map-note input')).toBeNull(); expect((document.querySelector('#rail-place-search') as HTMLInputElement).value).toBe(""); expect(document.activeElement).toBe(document.querySelector('[data-slot=rail-station-mapping]'));
  await input("#rail-place-search", "서울"); await act(async () => document.querySelector<HTMLButtonElement>('.rail-map-candidates button')!.click()); await click("수동으로 연결"); expect(JSON.parse(posts()[1][1].body).expected_revision).toBe(fresh.revision);
});
test("자동POST 성공 뒤 후속GET 대기에는 편집과 선택을 잠그고 최신FK를 받은 뒤에만 푼다", async () => {
  const wait = deferred<Response>(); fetchMock.mockResolvedValueOnce(json(preview)).mockResolvedValueOnce(json(applied)).mockReturnValueOnce(wait.promise);
  await render(); await act(async () => document.querySelector<HTMLInputElement>('input[type=checkbox]')!.click()); await click("자동 연결 미리보기"); await click("적용");
  expect((document.querySelector('#rail-place-search') as HTMLInputElement).disabled).toBe(true); expect((document.querySelector('#rail-station-filter') as HTMLInputElement).disabled).toBe(true); expect((document.querySelector('.rail-map-station-list button') as HTMLButtonElement).disabled).toBe(true); expect(button("수동으로 연결").disabled).toBe(true);
  await act(async () => wait.resolve(json({ ...initial, revision: candidate, stations: [{ ...initial.stations[0], rail_station_id: 1, rail_station_identity_key: "rail|seoul", match_method: "exact_identity" }] })));
  expect((document.querySelector('#rail-place-search') as HTMLInputElement).disabled).toBe(false); expect((document.querySelector('.rail-map-note input') as HTMLInputElement).value).toBe(""); expect(host.textContent).toContain("서울역 · 1호선");
});
test("후속 목록GET 실패는 옛revision 편집을 계속 막고 사용자 새로고침 성공으로 복구한다", async () => {
  fetchMock.mockResolvedValueOnce(json(preview)).mockResolvedValueOnce(json(applied)).mockResolvedValueOnce(json({ detail: "목록 조회 실패" }, 503)).mockResolvedValueOnce(json({ ...initial, revision: candidate }));
  await render(); await click("자동 연결 미리보기"); await click("적용"); expect((document.querySelector('#rail-place-search') as HTMLInputElement).disabled).toBe(true); expect(button("자동 연결 미리보기").disabled).toBe(true); expect(host.textContent).toContain("최신 역 목록"); expect(button("새로고침").disabled).toBe(false);
  await click("새로고침"); expect((document.querySelector('#rail-place-search') as HTMLInputElement).disabled).toBe(false); expect(button("자동 연결 미리보기").disabled).toBe(false); expect(posts()).toHaveLength(1);
});
