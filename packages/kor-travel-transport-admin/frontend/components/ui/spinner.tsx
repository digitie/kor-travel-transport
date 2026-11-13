"use client";

import type { ComponentProps } from "react";
import { Loader2Icon } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * 공용 UI 패키지에는 spinner가 없어 Map Button의 로딩 표시와 같은 아이콘을 쓴다.
 * 회전 속도는 globals.css의 reduced-motion 규칙이 느리게 낮춘다.
 */
function Spinner({ className, ...props }: ComponentProps<typeof Loader2Icon>) {
  return <Loader2Icon data-slot="spinner" className={cn("size-4 animate-spin", className)} {...props} />;
}

export { Spinner };
