import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ReferenceDataset, type FerryReferencePayload } from "./ferry-reference";

const state: FerryReferencePayload["items"][number] = { dataset: "ferry_routes", title: "도선항로",
  last_attempt_at: "2026-10-24T00:00:00Z", last_error: "NetworkError",
  data: { source: "vadahub:piltg_rute_l", source_url: "https://vadahub.go.kr", source_version: "2019-12-10",
    source_sha256: "a".repeat(64), collected_at: "2026-10-23T00:00:00Z", items: [{ record_id: "001", kind: "route",
      name: null, departure: null, arrival: null, segment: null, calls: null, address: null, telephone: null, source_year: null }] } };

describe("배편 기준자료", () => {
  it("실패 뒤 마지막 정상 자료와 출처·시점을 표시하고 출도착지를 추정하지 않는다", () => {
    const html = renderToStaticMarkup(<ReferenceDataset state={state} query="" />);
    expect(html).toContain("마지막 정상 저장본");
    expect(html).toContain("2019-12-10");
    expect(html).toContain("vadahub:piltg_rute_l");
    expect(html).toContain("출발지 미제공");
    expect(html).toContain("도착지 미제공");
    expect(html).toContain("원천 항로 001");
  });
  it("아직 수집하지 못한 원천을 항로 없음으로 표시하지 않는다", () => {
    const html = renderToStaticMarkup(<ReferenceDataset state={{ ...state, data: null }} query="" />);
    expect(html).toContain("수집 대기");
    expect(html).toContain("항로나 시설이 없다는 뜻이 아닙니다");
  });
  it("이름이 없는 항로도 원천 ID로 검색한다", () => {
    expect(renderToStaticMarkup(<ReferenceDataset state={state} query="001" />)).toContain("원천 항로 001");
    expect(renderToStaticMarkup(<ReferenceDataset state={state} query="없는 항로" />)).toContain("검색 결과 없음");
  });
  it.each(["15995985", "2014"])("전화번호와 조사연도로 시설을 검색한다: %s", (query) => {
    const facility = { ...state, data: { ...state.data!, items: [{ ...state.data!.items[0],
      kind: "facility" as const, name: "인천연안여객선터미널", telephone: "15995985", source_year: "2014" }] } };
    expect(renderToStaticMarkup(<ReferenceDataset state={facility} query={query} />)).toContain("인천연안여객선터미널");
  });
});
