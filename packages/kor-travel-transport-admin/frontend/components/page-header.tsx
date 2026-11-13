"use client";
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app

import { usePathname } from "next/navigation";
import { Fragment, type ReactNode } from "react";

import { getActiveAdminItem } from "@/components/admin-nav";
import { HelpTip } from "@/components/help-tip";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { withOccurrenceKeys } from "@/lib/occurrence-key";

export type AdminBreadcrumb = { label: string; href?: string };

export type PageHeaderProps = {
  title: string;
  /** 제목 옆 도움말(HelpTip) 본문. 예전 InfoButton 자리를 그대로 쓴다. */
  description?: ReactNode;
  /** 명시 섹션 라벨. 생략하면 메뉴 정본에서 현재 경로의 섹션을 유도한다. breadcrumbs가 있으면 그쪽이 이긴다. */
  section?: string;
  breadcrumbs?: AdminBreadcrumb[];
  /** h1 아래 한 줄 메타(상태·갱신 시각·건수). text-secondary 한 줄이며 구분자는 `·`. */
  meta?: ReactNode;
  /** 헤더 액션 슬롯 — primary ≤ 1 + secondary ≤ 2. */
  actions?: ReactNode;
};

/**
 * 페이지 헤더 — AdminShell의 header band와 같은 마크업·클래스다.
 * 레이아웃의 main 안에서 그려지므로 가로 여백은 main이 준다. 페이지 최상단에 한 번 둔다.
 */
export function PageHeader({ title, description, section, breadcrumbs, meta, actions }: PageHeaderProps) {
  const pathname = usePathname();
  const sectionLabel = section ?? getActiveAdminItem(pathname)?.section;
  const hasBreadcrumbs = Boolean(breadcrumbs && breadcrumbs.length > 0);

  return (
    <header className="mb-6 border-b border-border pb-4" data-slot="admin-shell-header">
      <div className="flex min-w-0 flex-col gap-1">
        {hasBreadcrumbs && breadcrumbs ? (
          <Breadcrumb>
            <BreadcrumbList className="text-xs">
              {withOccurrenceKeys(breadcrumbs, (crumb) => JSON.stringify([crumb.href ?? null, crumb.label])).map(
                ({ key, value: crumb }, index) => (
                  <Fragment key={key}>
                    {index > 0 ? <BreadcrumbSeparator /> : null}
                    <BreadcrumbItem>
                      {crumb.href ? (
                        <BreadcrumbLink href={crumb.href}>{crumb.label}</BreadcrumbLink>
                      ) : index === breadcrumbs.length - 1 ? (
                        <BreadcrumbPage>{crumb.label}</BreadcrumbPage>
                      ) : (
                        <span>{crumb.label}</span>
                      )}
                    </BreadcrumbItem>
                  </Fragment>
                ),
              )}
            </BreadcrumbList>
          </Breadcrumb>
        ) : sectionLabel ? (
          <p className="text-2xs font-medium text-text-secondary">{sectionLabel}</p>
        ) : null}
        <div className="flex min-w-0 flex-col gap-3 md:flex-row md:items-center md:justify-between md:gap-6">
          <div className="flex min-w-0 items-center gap-2">
            <h1 className="text-xl leading-tight font-bold tracking-tight text-text-primary">{title}</h1>
            {description ? <HelpTip label={title}>{description}</HelpTip> : null}
          </div>
          {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
        </div>
        {meta ? (
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-text-secondary">{meta}</div>
        ) : null}
      </div>
    </header>
  );
}
