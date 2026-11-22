"use client";

import { useEffect, useId, useState, type Ref, type RefObject } from "react";
import { ChevronDown, MapPinned, SlidersHorizontal } from "lucide-react";
import { z } from "zod";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "./ui/dialog";
import { Popover, PopoverContent, PopoverTrigger } from "./ui/popover";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "./ui/tooltip";
import { Button } from "./ui/button";
import { FuelBrandIcon } from "./fuel-brand-icon";
import { FUEL_CHART_ORDER } from "@/lib/fuel-chart-model";
import { fuelProductLabel } from "@/lib/transport-presentation";
import {
  activeFilterCount, BRAND_FILTERS, brandRelevant, DEFAULT_PUBLIC_FUEL_FILTERS, FLAG_FILTERS, isBrandChecked,
  NEAR_MIN_STEPS, toggleBrand, type PublicFuelFilters,
} from "@/lib/public-fuel-filters";

// 공개 유가(TRANSPORT_UI_MODE=fuel) 전용: 맨 위 지역 아이콘 버튼·"이동하세요…" 대화상자, 유종·필터 한 곳 선택.
// 관리 화면은 이 파일을 쓰지 않는다.
type Loader = <T>(path: string, signal?: AbortSignal) => Promise<T>;

const catalogSchema = z.object({ items: z.array(z.object({
  sido_value: z.string(), sido_name: z.string(),
  sigungu: z.array(z.object({ sigungu_value: z.string(), sigungu_name: z.string(), station_count: z.number(),
    bounds: z.tuple([z.number(), z.number(), z.number(), z.number()]) })),
})) });
export type FuelAreaCatalog = z.infer<typeof catalogSchema>;
export type FuelAreaChoice = { sido_value: string; sigungu_value: string };
/** 지역 이동에서 고른 시군구. label은 "시도 시군구". */
export type FuelSelectedRegion = FuelAreaChoice & { label: string };
type ConfirmRegion = (bounds: [number, number, number, number], region: FuelSelectedRegion) => void;

/** "이동하세요…": 시/도 → 구/군/시를 고르고 확인하면 그 시군구 주유소 범위로 지도를 옮긴다. */
export function FuelRegionPicker({ open, onOpenChange, load, current, onConfirm, returnFocus }: {
  open: boolean; onOpenChange: (open: boolean) => void; load: Loader; current?: FuelAreaChoice;
  onConfirm: ConfirmRegion;
  /** 트리거 없이 여는 대화상자라 닫을 때 연 버튼으로 초점을 직접 돌려준다. */
  returnFocus?: RefObject<HTMLElement | null>;
}) {
  return <Dialog open={open} onOpenChange={onOpenChange}>
    {open ? <DialogContent className="fuel-region-picker" showCloseButton={false}
      onCloseAutoFocus={event => { event.preventDefault(); returnFocus?.current?.focus(); }}>
      <FuelRegionPickerBody load={load} current={current} onCancel={() => onOpenChange(false)}
        onConfirm={(bounds, region) => { onConfirm(bounds, region); onOpenChange(false); }} />
    </DialogContent> : null}
  </Dialog>;
}

function FuelRegionPickerBody({ load, current, onCancel, onConfirm }: {
  load: Loader; current?: FuelAreaChoice; onCancel: () => void; onConfirm: ConfirmRegion;
}) {
  const [state, setState] = useState<{ catalog?: FuelAreaCatalog; error?: boolean }>();
  const [retry, setRetry] = useState(0);
  const [sido, setSido] = useState(current?.sido_value);
  const [sigungu, setSigungu] = useState(current?.sigungu_value);
  useEffect(() => {
    const controller = new AbortController();
    load<unknown>("transport/fuel/area-catalog", controller.signal)
      .then(value => { if (!controller.signal.aborted) setState({ catalog: catalogSchema.parse(value) }); })
      .catch(() => { if (!controller.signal.aborted) setState({ error: true }); });
    return () => controller.abort();
  }, [load, retry]);
  const catalog = state?.catalog;
  const sidoRow = catalog?.items.find(row => row.sido_value === sido) ?? catalog?.items[0];
  const sigunguRow = sidoRow?.sigungu.find(row => row.sigungu_value === sigungu);
  const label = sidoRow && sigunguRow ? `${sidoRow.sido_name} ${sigunguRow.sigungu_name}` : null;
  return <div className="fuel-region-picker-body" aria-busy={!state}>
    <DialogTitle>이동하세요…</DialogTitle>
    <DialogDescription className="sr-only">시/도와 구/군/시를 고르면 그 지역 주유소가 보이도록 지도를 옮깁니다.</DialogDescription>
    {!state ? <p role="status">지역 목록 불러오는 중…</p>
      : state.error || !catalog ? <div role="alert"><p>지역 목록을 불러오지 못했습니다.</p><Button type="button" variant="outline" size="sm" onClick={() => setRetry(value => value + 1)}>다시 시도</Button></div>
      : <div className="fuel-region-columns">
        <fieldset>
          <legend>시/도</legend>
          <div className="fuel-region-options">
            {catalog.items.map(row => <label key={row.sido_value} className="fuel-region-option">
              <input type="radio" name="fuel-region-sido" value={row.sido_value} checked={row.sido_value === sidoRow?.sido_value}
                onChange={() => { setSido(row.sido_value); setSigungu(undefined); }} />
              <span>{row.sido_name}</span>
            </label>)}
          </div>
        </fieldset>
        <fieldset>
          <legend>구/군/시</legend>
          <div className="fuel-region-options">
            {sidoRow?.sigungu.map(row => <label key={row.sigungu_value} className="fuel-region-option">
              <input type="radio" name="fuel-region-sigungu" value={row.sigungu_value} checked={row.sigungu_value === sigungu}
                onChange={() => setSigungu(row.sigungu_value)} />
              <span>{row.sigungu_name}</span>
            </label>)}
          </div>
        </fieldset>
      </div>}
    <div className="fuel-region-actions">
      <Button type="button" variant="ghost" onClick={onCancel}>취소</Button>
      <Button type="button" disabled={!sigunguRow} onClick={() => sidoRow && sigunguRow && label && onConfirm(sigunguRow.bounds,
        { sido_value: sidoRow.sido_value, sigungu_value: sigunguRow.sigungu_value, label })}
        aria-label={label ? `${label} 지역으로 이동` : undefined}>{label ?? "구/군/시 선택"}</Button>
    </div>
  </div>;
}


/** 맨 위 줄의 지역 이동 아이콘 버튼. 글자 대신 접근성 이름과 툴팁으로 "지역 이동"을 알린다. */
export function PublicFuelRegionButton({ onOpen, buttonRef }: { onOpen: (opener: HTMLElement) => void; buttonRef?: Ref<HTMLButtonElement> }) {
  return <TooltipProvider delayDuration={300}>
    <Tooltip>
      <TooltipTrigger asChild>
        <Button ref={buttonRef} type="button" variant="outline" size="icon" className="public-fuel-region-button" aria-label="지역 이동"
          onClick={event => onOpen(event.currentTarget)}><MapPinned aria-hidden="true" size={18} /></Button>
      </TooltipTrigger>
      <TooltipContent side="bottom" className="pointer-events-none">지역 이동</TooltipContent>
    </Tooltip>
  </TooltipProvider>;
}

const PRODUCT_CHOICES = FUEL_CHART_ORDER.map(code => ({ code, label: fuelProductLabel(code) }));

/**
 * 맨 위 유종·필터 다중 선택. 예전 필터 버튼·서랍의 내용(유종, 지도 최저가, 주유소 조건·품질인증, 상표, 초기화)을
 * 한 팝오버의 묶음으로 담는다. 바꾸면 바로 서버 조건에 적용되고 이 브라우저에 저장된다(저장은 부모가 맡는다).
 * 닫으면 Radix가 이 트리거로 초점을 돌려준다.
 */
export function PublicFuelFilterMenu({ products, onProductsChange, filters = DEFAULT_PUBLIC_FUEL_FILTERS, onFiltersChange }: {
  products: string[]; onProductsChange: (products: string[]) => void;
  filters?: PublicFuelFilters; onFiltersChange?: (filters: PublicFuelFilters) => void;
}) {
  const [open, setOpen] = useState(false);
  const count = onFiltersChange ? activeFilterCount(filters, products) : 0;
  const productText = products.length ? products.map(fuelProductLabel).join(", ") : "전체 유종";
  return <Popover open={open} onOpenChange={setOpen} modal>
    <PopoverTrigger asChild>
      <button type="button" className="public-fuel-filter-trigger"
        aria-label={`유종·필터: ${productText}${count ? `, 조건 ${count}개 적용 중` : ""}`}>
        <SlidersHorizontal aria-hidden="true" size={16} className="public-fuel-filter-trigger-icon" />
        <span className="public-fuel-filter-trigger-value" aria-hidden="true">{productText}</span>
        {count ? <span className="public-fuel-filter-count" aria-hidden="true">{count}</span> : null}
        <ChevronDown aria-hidden="true" size={16} className="public-fuel-filter-trigger-chevron" />
      </button>
    </PopoverTrigger>
    <PopoverContent align="start" collisionPadding={8} aria-label="유종·필터" className="public-fuel-filter-menu">
      <FuelFilterForm products={products} onProductsChange={onProductsChange} filters={filters} onFiltersChange={onFiltersChange}
        onClose={() => setOpen(false)} />
    </PopoverContent>
  </Popover>;
}

function FuelFilterForm({ filters, onFiltersChange, products, onProductsChange, onClose }: {
  filters: PublicFuelFilters; onFiltersChange?: (filters: PublicFuelFilters) => void;
  products: string[]; onProductsChange: (products: string[]) => void; onClose: () => void;
}) {
  const selected = new Set(products);
  const toggleProduct = (code: string, checked: boolean) =>
    onProductsChange(FUEL_CHART_ORDER.filter(value => value === code ? checked : selected.has(value)));
  const dirty = products.length > 0 || (onFiltersChange ? activeFilterCount(filters) > 0 || filters.brands.length > 0 : false);
  return <div className="fuel-filter-form">
    <fieldset className="fuel-filter-section">
      <legend>유종</legend>
      <label className="fuel-filter-row">
        <span>전체 유종</span>
        <input type="checkbox" checked={!products.length} disabled={!products.length} onChange={() => onProductsChange([])} />
      </label>
      {PRODUCT_CHOICES.map(({ code, label }) => <label key={code} className="fuel-filter-row">
        <span>{label}</span>
        <input type="checkbox" checked={selected.has(code)} onChange={event => toggleProduct(code, event.target.checked)} />
      </label>)}
    </fieldset>
    {onFiltersChange ? <FuelStationFilterSections filters={filters} onFiltersChange={onFiltersChange} products={products} /> : null}
    <div className="fuel-filter-actions">
      <Button type="button" variant="outline" disabled={!dirty}
        onClick={() => { onProductsChange([]); onFiltersChange?.(DEFAULT_PUBLIC_FUEL_FILTERS); }}>초기화</Button>
      <Button type="button" onClick={onClose}>닫기</Button>
    </div>
  </div>;
}

function FuelStationFilterSections({ filters, onFiltersChange, products }: {
  filters: PublicFuelFilters; onFiltersChange: (filters: PublicFuelFilters) => void; products: string[];
}) {
  const nearId = useId();
  const allBrands = !filters.brands.length;
  return <>
    <div className="fuel-filter-section">
      <label className="fuel-filter-row" htmlFor={nearId}>
        <span>지도 최저가</span>
        <select id={nearId} value={products.length === 1 ? filters.near_min ?? "" : ""} disabled={products.length !== 1}
          onChange={event => onFiltersChange({ ...filters, near_min: event.target.value ? Number(event.target.value) : null })}>
          <option value="">전체</option>
          {NEAR_MIN_STEPS.map(step => <option key={step} value={step}>~{step}원</option>)}
        </select>
      </label>
      <p className="fuel-filter-hint">{products.length === 1 ? "지금 지도에서 가장 싼 값부터 고른 금액 안의 주유소만 보입니다." : "유종을 하나 고르면 사용할 수 있습니다."}</p>
    </div>
    <fieldset className="fuel-filter-section">
      <legend>주유소 조건</legend>
      {FLAG_FILTERS.map(flag => <label key={flag.key} className="fuel-filter-row">
        <span>{flag.label}</span>
        <input type="checkbox" checked={filters[flag.key]}
          onChange={event => onFiltersChange({ ...filters, [flag.key]: event.target.checked })} />
      </label>)}
    </fieldset>
    <fieldset className="fuel-filter-section">
      <legend>브랜드</legend>
      {BRAND_FILTERS.map(brand => {
        const relevant = brandRelevant(brand, products);
        return <label key={brand.key} className="fuel-filter-row fuel-filter-brand" data-disabled={!relevant || undefined}>
          <span aria-hidden="true" className="fuel-filter-brand-mark"><FuelBrandIcon code={brand.icon === "ETC" ? null : brand.icon} name={brand.label} className="fuel-filter-brand-icon" /></span>
          <span>{brand.label}{!relevant ? <small> · 이 유종 없음(적용 안 함)</small> : null}</span>
          <input type="checkbox" checked={isBrandChecked(filters, brand.key)} disabled={!relevant}
            onChange={event => onFiltersChange(toggleBrand(filters, brand.key, event.target.checked, products))} />
        </label>;
      })}
      <label className="fuel-filter-row">
        <span>브랜드 전체 선택</span>
        <input type="checkbox" checked={allBrands} disabled={allBrands} onChange={() => onFiltersChange({ ...filters, brands: [] })} />
      </label>
    </fieldset>
  </>;
}
