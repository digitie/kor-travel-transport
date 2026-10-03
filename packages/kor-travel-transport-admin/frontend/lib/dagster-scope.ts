/**
 * Every Dagster GraphQL request this admin sends, and the one place that
 * scopes them to this project's own code location.
 *
 * The Dagster webserver behind /api/dagster/graphql is the shared control
 * plane (kor-travel-docker-manager ADR-54): it serves every project's code
 * location. An unscoped `repositoriesOrError` lists every tenant's schedules
 * and an unscoped `runsOrError` mixes their runs into this page, and a raw
 * GraphQL document forwarded from the browser could run a mutation against
 * another project. So the browser posts only an operation name; the proxy
 * route turns it into the query below with the scope filled in on the server.
 *
 * This module is imported by the browser code (lib/dagster.ts) and the proxy
 * route alike, so it must not reach for server-only APIs.
 */

/**
 * The code location name: the code-server's `--location-name` in
 * docker-compose.shared.yml and the shared workspace's `location_name`.
 * backend/tests/test_shared_dagster_plane_contract.py fails if this copy
 * drifts from the compose file.
 */
export const DAGSTER_LOCATION_NAME = "kor-travel-transport";
/** Name Dagster gives the single implicit repository of a `Definitions` module. */
export const DAGSTER_REPOSITORY_NAME = "__repository__";
/** Run tag Dagster sets on every launched run: the code location's name. */
export const DAGSTER_LOCATION_TAG_KEY = "dagster/code_location";
/** Run list size of the overview (unchanged from the unscoped query). */
export const DAGSTER_RUN_LIMIT = 30;

/** Variables the proxy sets itself; a request that tries to supply them is refused. */
const SCOPE_VARIABLES = {
  repositoryLocationName: DAGSTER_LOCATION_NAME,
  repositoryName: DAGSTER_REPOSITORY_NAME,
  locationTag: DAGSTER_LOCATION_NAME,
} as const;

const RUN_TAG_FILTER = `tags: [{ key: "${DAGSTER_LOCATION_TAG_KEY}", value: $locationTag }]`;

const OVERVIEW_QUERY = `query TransportDagsterOverview($repositoryLocationName: String!, $repositoryName: String!, $locationTag: String!) {
  repositoryOrError(repositorySelector: { repositoryLocationName: $repositoryLocationName, repositoryName: $repositoryName }) {
    __typename
    ... on Repository { schedules { name cronSchedule pipelineName scheduleState { status } } }
    ... on RepositoryNotFoundError { message }
    ... on PythonError { message }
  }
  runsOrError(limit: ${DAGSTER_RUN_LIMIT}, filter: { ${RUN_TAG_FILTER} }) {
    __typename
    ... on Runs { results { runId status jobName startTime endTime } }
  }
  activeRuns: runsOrError(filter: { statuses: [STARTED], ${RUN_TAG_FILTER} }) {
    __typename
    ... on Runs { results { runId status jobName startTime endTime } }
  }
}`;

type DagsterOperation = {
  query: string;
};

export const DAGSTER_OPERATIONS = {
  TransportDagsterOverview: { query: OVERVIEW_QUERY },
} satisfies Record<string, DagsterOperation>;

export type DagsterOperationName = keyof typeof DAGSTER_OPERATIONS;

/** What the browser posts to /api/dagster/graphql: a name, never a query document. */
export type DagsterOperationRequest = { operationName: DagsterOperationName };

export type ScopedDagsterRequest = { ok: true; body: string } | { ok: false; message: string };

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Turn a browser request into the GraphQL body the webserver receives, or say
 * why it is refused. The query text and the scope variables always come from
 * this module; the caller contributes only an operation name.
 */
export function scopedDagsterRequest(raw: unknown): ScopedDagsterRequest {
  if (!isPlainObject(raw)) return { ok: false, message: "Dagster 요청 형식이 올바르지 않습니다." };
  const unexpected = Object.keys(raw).filter((key) => key !== "operationName");
  if (unexpected.length) return { ok: false, message: `허용되지 않은 Dagster 요청 필드입니다: ${unexpected.join(", ")}` };
  const { operationName } = raw;
  if (typeof operationName !== "string" || !Object.hasOwn(DAGSTER_OPERATIONS, operationName)) {
    return { ok: false, message: "허용되지 않은 Dagster 작업입니다." };
  }
  const operation: DagsterOperation = DAGSTER_OPERATIONS[operationName as DagsterOperationName];
  return { ok: true, body: JSON.stringify({ operationName, query: operation.query, variables: { ...SCOPE_VARIABLES } }) };
}

/**
 * Links into the Dagster UI: the shared gateway's public host. Run ids are
 * unique across the instance, so run links stay global; everything else goes
 * through this location's own pages.
 */
export const DAGSTER_UI_BASE = "https://dagster.digitie.mywire.org";

export function dagsterLocationUrl(path = ""): string {
  return `${DAGSTER_UI_BASE}/locations/${encodeURIComponent(DAGSTER_LOCATION_NAME)}${path}`;
}

export function dagsterRunUrl(runId: string): string {
  return `${DAGSTER_UI_BASE}/runs/${encodeURIComponent(runId)}`;
}
