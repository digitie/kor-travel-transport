"use client";

import { useEffect, useId, useState, type RefObject } from "react";
import { MapPinned, SlidersHorizontal } from "lucide-react";
import { z } from "zod";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogTitle } from "./ui/dialog";
import { Button } from "./ui/button";
import { FuelBrandIcon } from "./fuel-brand-icon";
import { fuelProductLabel } from "@/lib/transport-presentation";
import {
  activeFilterCount, BRAND_FILTERS, brandRelevant, DEFAULT_PUBLIC_FUEL_FILTERS, FLAG_FILTERS, isBrandChecked,
  NEAR_MIN_STEPS, toggleBrand, type PublicFuelFilters,
} from "@/lib/public-fuel-filters";

// 공개 유가(TRANSPORT_UI_MODE=fuel) 전용: 지역 이동 대화상자와 필터 서랍. 관리 화면은 이 파일을 쓰지 않는다.
type Loader = <T>(path: string, signal?: AbortSignal) => Promise<T>;
const PRODUCT_CHOICES = [["", "전체 유종"], ["B034", "고급휘발유"], ["B027", "휘발유"], ["D047", "경유"], ["C004", "실내등유"], ["K015", "LPG"]] as const;

const catalogSchema = z.object({ items: z.array(z.object({
  sido_value: z.string(), sido_name: z.string(),
  sigungu: z.array(z.object({ sigungu_value: z.string(), sigungu_name: z.string(), station_count: z.number(),
    bounds: z.tuple([z.number(), z.number(), z.number(), z.number()]) })),
})) });
export type FuelAreaCatalog = z.infer<typeof catalogSchema>;
export type FuelAreaChoice = { sido_value: string; sigungu_value: string };

export function PublicFuelTools({ filterCount, onOpenRegion, onOpenFilters }: { filterCount: number; onOpenRegion: () => void; onOpenFilters: () => void }) {
  return <div className="public-fuel-tools" role="group" aria-label="지역 이동과 필터">
    <Button type="button" variant="outline" onClick={onOpenRegion}><MapPinned aria-hidden="true" size={18} />지역</Button>
    <Button type="button" variant="outline" onClick={onOpenFilters} aria-label={filterCount ? `필터 ${filterCount}개 적용 중` : "필터"}>
      <SlidersHorizontal aria-hidden="true" size={18} />필터{filterCount ? <span className="public-fuel-filter-count" aria-hidden="true">{filterCount}</span> : null}
    </Button>
  </div>;
}

/** "이동하세요…": 시/도 → 구/군/시를 고르고 확인하면 그 시군구 주유소 범위로 지도를 옮긴다. */
export function FuelRegionPicker({ open, onOpenChange, load, current, onConfirm, returnFocus }: {
  open: boolean; onOpenChange: (open: boolean) => void; load: Loader; current?: FuelAreaChoice;
  onConfirm: (bounds: [number, number, number, number], label: string) => void;
  /** 트리거 없이 여는 대화상자라 닫을 때 연 버튼으로 초점을 직접 돌려준다. */
  returnFocus?: RefObject<HTMLElement | null>;
}) {
  return <Dialog open={open} onOpenChange={onOpenChange}>
    {open ? <DialogContent className="fuel-region-picker" showCloseButton={false}
      onCloseAutoFocus={event => { event.preventDefault(); returnFocus?.current?.focus(); }}>
      <FuelRegionPickerBody load={load} current={current} onCancel={() => onOpenChange(false)}
        onConfirm={(bounds, label) => { onConfirm(bounds, label); onOpenChange(false); }} />
    </DialogContent> : null}
  </Dialog>;
}

function FuelRegionPickerBody({ load, current, onCancel, onConfirm }: {
  load: Loader; current?: FuelAreaChoice; onCancel: () => void; onConfirm: (bounds: [number, number, number, number], label: string) => void;
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
      <Button type="button" disabled={!sigunguRow} onClick={() => sigunguRow && label && onConfirm(sigunguRow.bounds, label)}
        aria-label={label ? `${label} 지역으로 이동` : "구/군/시를 고르세요"}>{label ?? "구/군/시 선택"}</Button>
    </div>
  </div>;
}

/** 필터 서랍(오른쪽). 바꾸면 바로 적용되고 브라우저에 저장된다. */
export function FuelFilterDrawer({ open, onOpenChange, filters, onFiltersChange, products, onProductsChange, returnFocus }: {
  open: boolean; onOpenChange: (open: boolean) => void;
  filters: PublicFuelFilters; onFiltersChange: (filters: PublicFuelFilters) => void;
  products: string[]; onProductsChange: (products: string[]) => void;
  returnFocus?: RefObject<HTMLElement | null>;
}) {
  // 공통 대화상자의 가운데 정렬(left/top 50%·-50% 이동)을 tailwind-merge가 지우도록 같은 유틸리티로 덮어 오른쪽 서랍으로 둔다.
  return <Dialog open={open} onOpenChange={onOpenChange}>
    {open ? <DialogContent showCloseButton={false}
      className="fuel-filter-drawer top-0 right-0 left-auto translate-x-0 translate-y-0 h-dvh max-h-dvh w-[min(24rem,88vw)] max-w-none sm:max-w-none rounded-none data-open:zoom-in-100 data-closed:zoom-out-100"
      onCloseAutoFocus={event => { event.preventDefault(); returnFocus?.current?.focus(); }}>
      <DialogTitle>필터</DialogTitle>
      <DialogDescription className="sr-only">유종·지도 최저가·주유소 조건·상표를 고르면 지도와 통계에 바로 적용됩니다.</DialogDescription>
      <FuelFilterForm filters={filters} onFiltersChange={onFiltersChange} products={products} onProductsChange={onProductsChange} />
      <DialogClose asChild><Button type="button" variant="outline" className="fuel-filter-close">닫기</Button></DialogClose>
    </DialogContent> : null}
  </Dialog>;
}

function FuelFilterForm({ filters, onFiltersChange, products, onProductsChange }: {
  filters: PublicFuelFilters; onFiltersChange: (filters: PublicFuelFilters) => void;
  products: string[]; onProductsChange: (products: string[]) => void;
}) {
  const productValue = products.length === 1 ? products[0] : products.length ? null : "";
  const nearId = useId();
  const allBrands = !filters.brands.length;
  return <div className="fuel-filter-form">
    <fieldset className="fuel-filter-section">
      <legend>유종</legend>
      {products.length > 1 ? <p className="fuel-filter-hint">여러 유종을 고른 상태입니다({products.map(fuelProductLabel).join(", ")}). 하나를 고르면 바뀝니다.</p> : null}
      {PRODUCT_CHOICES.map(([value, label]) => <label key={value || "all"} className="fuel-filter-row">
        <span>{label}</span>
        <input type="radio" name="fuel-filter-product" checked={productValue === value} onChange={() => onProductsChange(value ? [value] : [])} />
      </label>)}
    </fieldset>
    <div className="fuel-filter-section">
      <label className="fuel-filter-row" htmlFor={nearId}>
        <span>지도 최저가</span>
        <select id={nearId} value={filters.near_min ?? ""} disabled={products.length !== 1}
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
        <input type="checkbox" role="switch" checked={filters[flag.key]} aria-checked={filters[flag.key]}
          onChange={event => onFiltersChange({ ...filters, [flag.key]: event.target.checked })} />
      </label>)}
    </fieldset>
    <fieldset className="fuel-filter-section">
      <legend>상표</legend>
      {BRAND_FILTERS.map(brand => {
        const relevant = brandRelevant(brand, products);
        return <label key={brand.key} className="fuel-filter-row fuel-filter-brand" data-disabled={!relevant || undefined}>
          <FuelBrandIcon code={brand.icon === "ETC" ? null : brand.icon} name={brand.label} className="fuel-filter-brand-icon" />
          <span>{brand.label}{!relevant ? <small> · 이 유종 없음</small> : null}</span>
          <input type="checkbox" checked={isBrandChecked(filters, brand.key)} disabled={!relevant}
            onChange={event => onFiltersChange(toggleBrand(filters, brand.key, event.target.checked))} />
        </label>;
      })}
      <label className="fuel-filter-row">
        <span>브랜드 전체 선택</span>
        <input type="checkbox" checked={allBrands} disabled={allBrands} onChange={() => onFiltersChange({ ...filters, brands: [] })} />
      </label>
    </fieldset>
    <Button type="button" variant="outline" className="fuel-filter-reset" disabled={!activeFilterCount(filters)}
      onClick={() => onFiltersChange(DEFAULT_PUBLIC_FUEL_FILTERS)}>필터 초기화</Button>
  </div>;
}
