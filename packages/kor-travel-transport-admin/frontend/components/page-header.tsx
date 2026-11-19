"use client";

import { AdminPageTitle } from "@kor-travel/ui/admin-shell";
import { Fragment, type ReactNode } from "react";

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
  /** 공통 상단 바의 한 줄 설명. 긴 문자열은 말줄임하고 전체 내용을 title로 제공한다. */
  description?: ReactNode;
  /** 명시 영역 이름. 생략하면 서비스 이름인 교통을 사용한다. */
  section?: string;
  breadcrumbs?: AdminBreadcrumb[];
  /** 갱신 시각·건수 등 페이지의 보조 정보는 본문에 보존한다. */
  meta?: ReactNode;
  actions?: ReactNode;
};

/** 공통 셸의 제목 슬롯을 사용해 페이지 h1이 두 번 렌더링되지 않게 한다. */
export function PageHeader({ title, description, section, breadcrumbs, meta, actions }: PageHeaderProps) {
  const hasBreadcrumbs = Boolean(breadcrumbs && breadcrumbs.length > 0);

  return (
    <>
      <AdminPageTitle area={section ?? "교통"} title={title} description={description} actions={actions} />
      {hasBreadcrumbs || meta ? (
        <div className="mb-4 flex min-w-0 flex-wrap items-center justify-between gap-2" data-slot="admin-page-context">
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
          ) : null}
          {meta ? <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-text-secondary">{meta}</div> : null}
        </div>
      ) : null}
    </>
  );
}
