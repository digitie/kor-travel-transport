"use client";

import { useState } from "react";

import { PageHeader } from "@/components/admin-shell";

const endpoints = ["transport/collector-status", "transport/statistics?days=7", "transport/highways/traffic?days=1&limit=10", "transport/highways/incidents?days=1&limit=10", "transport/fuel/stations?days=2&limit=10"];

export default function ApiTestPage() {
  const [result, setResult] = useState("조회할 endpoint를 선택하세요.");
  async function inspect(endpoint: string) { const response = await fetch(`/api/transport/${endpoint}`); setResult(`${response.status}\n${JSON.stringify(await response.json(), null, 2)}`); }
  return <><PageHeader title="API 점검" description="관리 UI가 허용한 저장 데이터 조회 경로만 테스트합니다. 수집·백업·DB 변경 API는 노출하지 않습니다." /><section className="panel"><div className="row-list">{endpoints.map((endpoint) => <button className="button" key={endpoint} onClick={() => inspect(endpoint)} type="button">GET /v1/{endpoint}</button>)}</div></section><pre className="api-result">{result}</pre></>;
}
