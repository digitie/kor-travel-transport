"use client";

import type { ComponentProps } from "react";

import { HelpTip } from "@/components/help-tip";

/**
 * 기존 호출부의 이름을 유지하는 별칭이다. 제목 옆 도움말의 정본은 HelpTip이며,
 * 호출부를 HelpTip으로 옮기면 이 파일을 지운다.
 */
export function InfoButton(props: ComponentProps<typeof HelpTip>) {
  return <HelpTip {...props} />;
}
