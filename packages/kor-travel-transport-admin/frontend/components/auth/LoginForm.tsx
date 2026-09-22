"use client";

import { FormEvent, useState } from "react";

export function LoginForm({ nextPath }: { nextPath: string }) {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const response = await fetch("/api/auth/login", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ username, password, next: nextPath }) });
      const payload = await response.json().catch(() => ({})) as { detail?: string; next?: string };
      if (!response.ok) { setError(payload.detail ?? "로그인에 실패했습니다."); return; }
      window.location.assign(payload.next ?? nextPath);
    } catch { setError("로그인 서버에 연결하지 못했습니다."); } finally { setBusy(false); }
  }
  return <section className="login-shell"><form className="login-panel" onSubmit={submit}><p className="eyebrow">Kor Travel Transport</p><h1>관리자 로그인</h1><label className="field" htmlFor="username">아이디<input autoComplete="username" id="username" onChange={(event) => setUsername(event.target.value)} required value={username} /></label><label className="field" htmlFor="password">비밀번호<input autoComplete="current-password" id="password" onChange={(event) => setPassword(event.target.value)} required type="password" value={password} /></label><button className="button" disabled={busy} type="submit">{busy ? "확인 중…" : "로그인"}</button><p className="login-error" role="alert">{error}</p></form></section>;
}
