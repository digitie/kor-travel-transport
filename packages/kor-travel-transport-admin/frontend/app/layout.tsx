import type { Metadata } from "next";
import type { ReactNode } from "react";

import { AdminShell } from "@/components/admin-shell";
import { ConfirmDialogProvider } from "@/components/confirm-dialog";
import { Toaster } from "@/components/ui/sonner";

// 본문·UI 서체는 공용 tokens의 Pretendard 스택이다. Geist Mono는 next/font/google이 빌드 때 네트워크를 요구해 뺐다.
import "@kor-travel/tokens/font.css";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "kor-travel-transport admin", template: "%s · kor-travel-transport admin" },
  description: "국내 여행 통합 교통정보 운영 화면. 내부 전용 관리 콘솔.",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="ko" className="font-sans">
      <body>
        <ConfirmDialogProvider>
          <AdminShell>{children}</AdminShell>
        </ConfirmDialogProvider>
        <Toaster position="top-right" />
      </body>
    </html>
  );
}
