import type { DagsterSnapshot } from "@kor-travel/ui";
import { jobBudgetSeconds, type DagsterOverview } from "./dagster";
import { DAGSTER_LOCATION_NAME, DAGSTER_REPOSITORY_NAME } from "./dagster-scope";

export function commonSnapshot(snapshot: DagsterOverview): DagsterSnapshot {
  const runs = new Map(snapshot.runs.map(run => [run.runId, run]));
  for (const run of snapshot.activeRuns ?? []) if (!runs.has(run.runId)) runs.set(run.runId, run);
  return {
    checkedAt: snapshot.checkedAt ?? "",
    repositories: [{ name: DAGSTER_REPOSITORY_NAME, locationName: DAGSTER_LOCATION_NAME, jobs: [], assets: [],
      schedules: snapshot.schedules.map(row => ({ name: row.name, cron: row.cronSchedule, jobName: row.pipelineName, status: row.scheduleState.status })) }],
    runs: [...runs.values()].map(run => ({ ...run, errorMessage: run.errorMessage ?? null,
      maxRuntimeSeconds: Number(run.tags?.find(tag => tag.key === "dagster/max_runtime")?.value) || jobBudgetSeconds(run.jobName) })),
  };
}
