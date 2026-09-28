"use client";

import { FormEvent, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Field, FieldGroup, FieldLabel, FieldError } from "@/components/ui/field";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";

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
  return <section className="login-shell"><Card className="w-full max-w-md">
    <CardHeader><CardDescription>Kor Travel Transport</CardDescription><CardTitle><h1>관리자 로그인</h1></CardTitle></CardHeader>
    <CardContent><form onSubmit={submit} aria-busy={busy}><FieldGroup>
      <Field data-invalid={!!error}><FieldLabel htmlFor="username">아이디</FieldLabel><Input autoComplete="username" id="username" onChange={(event) => setUsername(event.target.value)} required value={username} aria-invalid={!!error} aria-describedby={error ? "login-error" : undefined} /></Field>
      <Field data-invalid={!!error}><FieldLabel htmlFor="password">비밀번호</FieldLabel><Input autoComplete="current-password" id="password" onChange={(event) => setPassword(event.target.value)} required type="password" value={password} aria-invalid={!!error} aria-describedby={error ? "login-error" : undefined} /></Field>
      <Button disabled={busy} type="submit">{busy ? <Spinner data-icon="inline-start" aria-label="로그인 확인 중" /> : null}{busy ? "확인 중…" : "로그인"}</Button>
      {error ? <FieldError id="login-error">{error}</FieldError> : null}
    </FieldGroup></form></CardContent>
  </Card></section>;
}
