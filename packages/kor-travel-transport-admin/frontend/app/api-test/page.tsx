"use client";

import { useState } from "react";

import { PageHeader } from "@/components/admin-shell";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

const endpoints = ["transport/collector-status", "transport/statistics?days=7", "transport/highways/traffic?days=1&limit=10", "transport/highways/incidents?days=1&limit=10", "transport/fuel/stations?days=2&limit=10"];

export default function ApiTestPage() {
  const [result, setResult] = useState("조회할 endpoint를 선택하세요.");
  async function inspect(endpoint: string) {
    try {
      const response = await fetch(`/api/transport/${endpoint}`);
      if (!response.ok) {
        const error: unknown = await response.json();
        setResult(`조회 실패 ${response.status}
${JSON.stringify(error, null, 2)}`);
        return;
      }
      const status = `정상 ${response.status}`;
      const payload: unknown = await response.json();
      setResult(`${status}
${JSON.stringify(payload, null, 2)}`);
    } catch { setResult("응답을 확인하지 못했습니다. 접속 상태를 확인해 주세요."); }
  }

  return <>
    <PageHeader title="API 점검" description="이 화면은 저장 데이터 조회 경로만 테스트합니다. 수집·백업 API와 지도 상세의 별도 좌표 보정 경로는 여기에 노출하지 않습니다." />
    <Card size="sm">
      <CardContent className="flex flex-wrap gap-2">
        {endpoints.map((endpoint) => <Button key={endpoint} onClick={() => inspect(endpoint)} type="button" variant="outline" size="sm">GET /v1/{endpoint}</Button>)}
      </CardContent>
    </Card>
    <pre className="mt-6 max-h-[28rem] overflow-auto rounded-panel border border-border bg-surface-subtle p-4 font-mono text-2xs leading-normal break-words whitespace-pre-wrap text-text-primary">{result}</pre>
  </>;
}
