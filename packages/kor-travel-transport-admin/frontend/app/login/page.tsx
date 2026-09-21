import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { LoginForm } from "@/components/auth/LoginForm";
import { sanitizeLocalPath } from "@/lib/navigation";
import { SESSION_COOKIE, verifySessionValue } from "@/lib/session";

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ next?: string }> }) {
  const nextPath = sanitizeLocalPath((await searchParams).next); const session = (await cookies()).get(SESSION_COOKIE)?.value;
  if (await verifySessionValue(session)) redirect(nextPath);
  return <LoginForm nextPath={nextPath} />;
}
