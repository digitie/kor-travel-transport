"use client";

import { useState } from "react";
import { LoginForm as CommonLoginForm, type LoginSubmission } from "@kor-travel/ui/login-form";
import { getLoginErrorMessage } from "@kor-travel/ui";

import { sanitizeLocalPath } from "@/lib/navigation";

const CREDENTIAL_ERROR = "아이디와 비밀번호를 확인하고 다시 시도해 주세요.";

/** 인증·세션은 Transport BFF(`/api/auth/login`)가 소유하고, 폼은 공통 컴포넌트를 쓴다. */
export function LoginForm({ nextPath }: { nextPath: string }) {
  const [error, setError] = useState<string | null>(null);

  async function submit({ credentials, nextPath: safeNext }: LoginSubmission) {
    const response = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ ...credentials, next: safeNext }),
      signal: AbortSignal.timeout(15_000),
    });
    // 잠금(429)·origin(403)·설정(503)을 비밀번호 오류처럼 보이지 않게 Common 상태 코드 사전(서버 원문 비노출)을 쓴다.
    // 자격증명 오류(401)만 기존 문구를 유지한다.
    if (!response.ok) {
      setError(response.status === 401 ? CREDENTIAL_ERROR : getLoginErrorMessage(response.status));
      return;
    }
    const payload = (await response.json().catch(() => ({}))) as { next?: string };
    window.location.assign(sanitizeLocalPath(payload.next ?? safeNext));
  }

  return (
    <main className="map-common-surface flex min-h-dvh flex-col justify-center bg-surface-page text-text-primary">
      <h1 className="sr-only">관리자 로그인</h1>
      <CommonLoginForm
        brand="kor-travel-transport admin"
        description="내부 전용 관리 콘솔"
        defaultUsername="admin"
        nextPath={nextPath}
        onSubmit={submit}
        error={error}
        onClearError={() => setError(null)}
        testId="transport-common-login"
        footer={<p>kor-travel-transport admin · 내부 전용 콘솔</p>}
      />
    </main>
  );
}
