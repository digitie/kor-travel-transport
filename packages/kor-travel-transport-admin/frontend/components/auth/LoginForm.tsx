"use client";

import { LoginForm as CommonLoginForm, getLoginErrorMessage, sanitizeLocalPath, type LoginSubmission } from "@kor-travel/ui";
import { useState } from "react";

const CREDENTIAL_ERROR = "아이디와 비밀번호를 확인하고 다시 시도해 주세요.";

export function LoginForm({ nextPath }: { nextPath: string }) {
  const [error, setError] = useState("");
  async function submit({ credentials, nextPath: next }: LoginSubmission) {
    const response = await fetch("/api/auth/login", { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ ...credentials, next }), signal: AbortSignal.timeout(15_000) });
    const payload = await response.json().catch(() => ({})) as { next?: string };
    // 잠금(429)·origin(403)·설정(503)을 비밀번호 오류처럼 보이지 않게 Common 상태 코드 사전(서버 원문 비노출)을 쓴다.
    // 자격증명 오류(401)만 기존 문구를 유지한다.
    if (!response.ok) { setError(response.status === 401 ? CREDENTIAL_ERROR : getLoginErrorMessage(response.status)); return; }
    window.location.assign(sanitizeLocalPath(payload.next ?? next));
  }
  return <section className="login-shell"><div className="panel login-panel"><h1>관리자 로그인</h1>
    <CommonLoginForm brand="Kor Travel Transport" defaultUsername="admin" nextPath={nextPath}
      description="교통정보 관리 계정으로 로그인해 주세요." error={error} onClearError={() => setError("")} onSubmit={submit} />
  </div></section>;
}
