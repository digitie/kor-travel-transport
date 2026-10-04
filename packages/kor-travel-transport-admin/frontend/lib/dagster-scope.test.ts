import { expect, test } from "vitest";
import { DAGSTER_LOCATION_NAME, dagsterLocationUrl, dagsterRunUrl, scopedDagsterRequest } from "./dagster-scope";

test("실패 상세도 소유 location 태그로 제한하고 scope 변수를 거절한다", () => {
  const runId = "00000000-0000-0000-0000-000000000001";
  const result = scopedDagsterRequest({ operationName: "TransportDagsterRunFailure", variables: { runId } });
  expect(result.ok).toBe(true);
  if (result.ok) {
    const body = JSON.parse(result.body);
    expect(body.variables.locationTag).toBe(DAGSTER_LOCATION_NAME);
    expect(body.query).toContain('key: "dagster/code_location"');
    expect(body.query).toContain("afterCursor: $cursor");
  }
  expect(scopedDagsterRequest({ operationName: "TransportDagsterRunFailure", variables: { runId, locationTag: "weather" } }).ok).toBe(false);
  expect(scopedDagsterRequest({ operationName: "TransportDagsterRunFailure", variables: { runId: "invalid" } }).ok).toBe(false);
});

test("이름 붙은 작업은 이 location으로 좁힌 query가 된다", () => {
  const scoped = scopedDagsterRequest({ operationName: "TransportDagsterOverview" });
  expect(scoped.ok).toBe(true);
  if (!scoped.ok) return;
  const body = JSON.parse(scoped.body);
  expect(body.operationName).toBe("TransportDagsterOverview");
  expect(body.variables).toEqual({ repositoryLocationName: DAGSTER_LOCATION_NAME, repositoryName: "__repository__", locationTag: DAGSTER_LOCATION_NAME });
  // 공용 webserver의 모든 테넌트를 훑는 형태가 남아 있지 않다.
  expect(body.query).not.toContain("repositoriesOrError");
  expect(body.query).toContain("repositorySelector: { repositoryLocationName: $repositoryLocationName");
  // 두 run 목록 모두 이 location의 tag로 좁힌다.
  expect(body.query.match(/tags: \[\{ key: "dagster\/code_location", value: \$locationTag \}\]/g)).toHaveLength(2);
  expect(body.query).not.toMatch(/\bmutation\b/);
});

test.each([
  [{ query: "{ runsOrError { __typename } }" }, "허용되지 않은 Dagster 요청 필드"],
  [{ operationName: "TransportDagsterOverview", query: "mutation { terminateRun }" }, "허용되지 않은 Dagster 요청 필드"],
  [{ operationName: "TransportDagsterOverview", variables: { locationTag: "kortravelmap.dagster.definitions" } }, "허용되지 않은 Dagster 요청 필드"],
  [{ operationName: "LaunchRun" }, "허용되지 않은 Dagster 작업"],
  [{ operationName: "constructor" }, "허용되지 않은 Dagster 작업"],
  [null, "형식"],
  [[], "형식"],
])("브라우저가 query·변수·모르는 작업을 보내면 거부한다 (%j)", (raw, message) => {
  const scoped = scopedDagsterRequest(raw);
  expect(scoped.ok).toBe(false);
  if (scoped.ok) return;
  expect(scoped.message).toContain(message);
});

test("Dagster UI 링크는 공용 gateway의 공개 host와 이 location을 쓴다", () => {
  expect(dagsterLocationUrl("/schedules")).toBe("https://dagster.digitie.mywire.org/locations/kor-travel-transport/schedules");
  expect(dagsterRunUrl("abc")).toBe("https://dagster.digitie.mywire.org/runs/abc");
});
