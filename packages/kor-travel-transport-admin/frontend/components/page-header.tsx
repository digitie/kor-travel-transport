"use client";
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app

import { AdminPageTitle } from "@kor-travel/ui/admin-shell";
import type { ReactNode } from "react";

export type PageHeaderProps = {
  /** 페이지 이름. 셸 상단 바에 "교통 - {title}"로 표시한다. */
  title: string;
  /** 상단 바 제목 옆의 작은 설명. 좁은 폭에서는 말줄임하고 전체 문장은 title 속성으로 제공한다. */
  description?: ReactNode;
  /** 상단 바 오른쪽 동작. 모바일 폭에서는 아이콘 버튼 1~2개로 줄인다. */
  actions?: ReactNode;
};

/**
 * 페이지 제목은 공용 관리자 셸의 한 줄 상단 바가 그린다(페이지 h1은 거기 하나뿐이다).
 * AdminShell 안에서는 상단 바 내용을 덮어쓰고, 밖(단위 시험 등)에서는 같은 상단 바를 직접 그린다.
 */
export function PageHeader({ title, description, actions }: PageHeaderProps) {
  return <AdminPageTitle title={title} description={description} actions={actions} />;
}
