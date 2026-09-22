import type { Metadata } from "next";

import { AdminShell } from "@/components/admin-shell";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "Kor Travel Transport Admin", template: "%s · Kor Travel Transport Admin" },
  description: "국내 여행 통합 교통정보 운영 화면",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="ko"><body><AdminShell>{children}</AdminShell></body></html>;
}
