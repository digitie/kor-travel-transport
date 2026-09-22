"use client";

import { useEffect, useState } from "react";

import { PageHeader } from "@/components/admin-shell";

const query = "{ repositoriesOrError { __typename ... on RepositoryConnection { nodes { name } } } }";

export default function DagsterPage() {
  const [result, setResult] = useState("Dagster workspace를 확인하는 중입니다…");
  useEffect(() => { fetch("/api/dagster/graphql", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ query }) }).then(async (response) => setResult(JSON.stringify(await response.json(), null, 2))).catch(() => setResult("Dagster 연결에 실패했습니다.")); }, []);
  return <><PageHeader title="Dagster" description="관리 UI 세션을 통과한 GraphQL 상태 조회입니다. 실행 제어는 공개 Dagster 도메인의 Basic Auth로 분리됩니다." /><pre className="api-result">{result}</pre></>;
}
