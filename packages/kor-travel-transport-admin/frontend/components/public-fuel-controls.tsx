"use client";

import { useEffect, useId, useRef, useState, type Ref, type RefObject } from "react";
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
import { fuelRegionDefault } from "@/lib/public-fuel-region";

// 공개 유가(TRANSPORT_UI_MODE=fuel) 전용: 맨 위 지역 아이콘 버튼·"지역 이동" 대화상자, 유종·필터 한 곳 선택.
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

/**
 * "지역 이동": 시/도 → 구/군/시를 고르고 확인하면 그 시군구 주유소 범위로 지도를 옮긴다.
 * 처음에는 지역 칩(current)을, 칩이 없으면 지금 지도 중심(center)이 속한 시군구를 고른 채 연다.
 */
export function FuelRegionPicker({ open, onOpenChange, load, current, center, onConfirm, onRelease, returnFocus }: {
  open: boolean; onOpenChange: (open: boolean) => void; load: Loader; current?: FuelAreaChoice;
  /** 지금 지도 중심 [경도, 위도]. 지역 칩이 없을 때 미리 고를 시군구를 찾는 데 쓴다. */
  center?: readonly [number, number];
  onConfirm: ConfirmRegion;
  /** 사용자가 고른 지역이 있을 때만: "해제"로 선택을 풀고 자동(지도 중심) 지역으로 돌아간다. */
  onRelease?: () => void;
  /** 트리거 없이 여는 대화상자라 닫을 때 연 버튼으로 초점을 직접 돌려준다. */
  returnFocus?: RefObject<HTMLElement | null>;
}) {
  return <Dialog open={open} onOpenChange={onOpenChange}>
    {open ? <DialogContent className="fuel-region-picker" showCloseButton={false}
      onCloseAutoFocus={event => { event.preventDefault(); returnFocus?.current?.focus(); }}>
      <FuelRegionPickerBody load={load} current={current} center={center} onCancel={() => onOpenChange(false)}
        onRelease={onRelease ? () => { onRelease(); onOpenChange(false); } : undefined}
        onConfirm={(bounds, region) => { onConfirm(bounds, region); onOpenChange(false); }} />
    </DialogContent> : null}
  </Dialog>;
}

function FuelRegionPickerBody({ load, current, center, onCancel, onConfirm, onRelease }: {
  load: Loader; current?: FuelAreaChoice; center?: readonly [number, number]; onCancel: () => void; onConfirm: ConfirmRegion;
  onRelease?: () => void;
}) {
  const [state, setState] = useState<{ catalog?: FuelAreaCatalog; error?: boolean }>();
  const [retry, setRetry] = useState(0);
  // 사용자가 고르기 전(undefined)에는 목록이 온 뒤 지역 칩 → 지도 중심 순으로 정한 기본값을 쓴다.
  const [picked, setPicked] = useState<{ sido?: string; sigungu?: string }>();
  useEffect(() => {
    const controller = new AbortController();
    load<unknown>("transport/fuel/area-catalog", controller.signal)
      .then(value => { if (!controller.signal.aborted) setState({ catalog: catalogSchema.parse(value) }); })
      .catch(() => { if (!controller.signal.aborted) setState({ error: true }); });
    return () => controller.abort();
  }, [load, retry]);
  const catalog = state?.catalog;
  const initial = picked ? undefined : fuelRegionDefault(catalog, current, center);
  const sido = picked ? picked.sido : initial?.sido_value;
  const sigungu = picked ? picked.sigungu : initial?.sigungu_value;
  const sidoRow = catalog?.items.find(row => row.sido_value === sido) ?? catalog?.items[0];
  const sigunguRow = sidoRow?.sigungu.find(row => row.sigungu_value === sigungu);
  const label = sidoRow && sigunguRow ? `${sidoRow.sido_name} ${sigunguRow.sigungu_name}` : null;
  // 목록이 온 직후 미리 고른 시/도·구/군/시가 각 열에서 보이도록 스크롤한다(긴 목록의 아래쪽 지역).
  const columns = useRef<HTMLDivElement>(null);
  useEffect(() => {
    columns.current?.querySelectorAll<HTMLInputElement>("input:checked")
      .forEach(input => input.closest("label")?.scrollIntoView?.({ block: "nearest" }));
  }, [catalog]);
  return <div className="fuel-region-picker-body" aria-busy={!state}>
    <DialogTitle>지역 이동</DialogTitle>
    <DialogDescription className="sr-only">시/도와 구/군/시를 고르면 그 지역 주유소가 보이도록 지도를 옮깁니다.</DialogDescription>
    {!state ? <p role="status">지역 목록 불러오는 중…</p>
      : state.error || !catalog ? <div role="alert"><p>지역 목록을 불러오지 못했습니다.</p><Button type="button" variant="outline" size="sm" onClick={() => setRetry(value => value + 1)}>다시 시도</Button></div>
      : <div ref={columns} className="fuel-region-columns">
        <fieldset>
          <legend>시/도</legend>
          <div className="fuel-region-options">
            {catalog.items.map(row => <label key={row.sido_value} className="fuel-region-option">
              <input type="radio" name="fuel-region-sido" value={row.sido_value} checked={row.sido_value === sidoRow?.sido_value}
                onChange={() => setPicked({ sido: row.sido_value })} />
              <span>{row.sido_name}</span>
            </label>)}
          </div>
        </fieldset>
        <fieldset>
          <legend>구/군/시</legend>
          <div className="fuel-region-options">
            {sidoRow?.sigungu.map(row => <label key={row.sigungu_value} className="fuel-region-option">
              <input type="radio" name="fuel-region-sigungu" value={row.sigungu_value} checked={row.sigungu_value === sigungu}
                onChange={() => setPicked({ sido: sidoRow?.sido_value, sigungu: row.sigungu_value })} />
              <span>{row.sigungu_name}</span>
            </label>)}
          </div>
        </fieldset>
      </div>}
    <div className="fuel-region-actions">
      <Button type="button" variant="ghost" onClick={onCancel}>취소</Button>
      {onRelease ? <Button type="button" variant="outline" className="fuel-region-release" onClick={onRelease}
        aria-label="해제 — 지도 중심 지역으로">해제</Button> : null}
      <Button type="button" disabled={!sigunguRow} onClick={() => sidoRow && sigunguRow && label && onConfirm(sigunguRow.bounds,
        { sido_value: sidoRow.sido_value, sigungu_value: sigunguRow.sigungu_value, label })}
        aria-label={label ? `${label} 지역으로 이동` : undefined}>{label ?? "구/군/시 선택"}</Button>
    </div>
  </div>;
}


/** 맨 위 줄의 지역 이동 아이콘 버튼. 글자 대신 접근성 이름과 툴팁으로 "지역 이동"을 알린다. */
export function PublicFuelRegionButton({ onOpen, buttonRef }: { onOpen: (opener: HTMLElement) => void; buttonRef?: Ref<HTMLButtonElement> }) {
  // 대화상자를 닫거나 지역을 해제해 초점이 코드로 돌아올 때는 툴팁을 열지 않는다(아래 지역 칩을 가린다).
  // 포인터를 올렸을 때와 키보드로 옮겨 온 초점(:focus-visible)에서만 연다.
  const [tip, setTip] = useState(false);
  const hovered = useRef(false);
  const allow = (target: EventTarget | null) => hovered.current || (target instanceof HTMLElement && target.matches(":focus-visible"));
  return <TooltipProvider delayDuration={300}>
    <Tooltip open={tip} onOpenChange={next => setTip(next && allow(document.activeElement))}>
      <TooltipTrigger asChild>
        <Button ref={buttonRef} type="button" variant="outline" size="icon" className="public-fuel-region-button" aria-label="지역 이동"
          onPointerEnter={() => { hovered.current = true; }} onPointerLeave={() => { hovered.current = false; }}
          onClick={event => onOpen(event.currentTarget)}><MapPinned aria-hidden="true" size={18} /></Button>
      </TooltipTrigger>
      <TooltipContent side="bottom" className="pointer-events-none">지역 이동</TooltipContent>
    </Tooltip>
  </TooltipProvider>;
}

const PRODUCT_CHOICES = FUEL_CHART_ORDER.map(code => ({ code, label: fuelProductLabel(code) }));

/**
 * 통계 화면 링크(`?product=`)로 연 유종. 이 지도에만 쓰고 저장한 선택은 그대로다. saved는 이 브라우저에 저장한 선택([]=전체 유종),
 * onUseSaved는 링크 유종을 버리고 저장한 선택으로 돌아간다(저장 값은 바꾸지 않는다).
 */
export type PublicFuelLinkedProduct = {
  code: string;
  /** 이 브라우저에 저장한 선택. null이면 아직 저장한 적이 없다(지도 기본: 전체 유종). */
  saved: string[] | null;
  /** 유종 선택을 저장할 수 있는가(저장이 막힌 브라우저면 이번 화면에서만 바뀐다). */
  canSave: boolean;
  onUseSaved: () => void;
};
const productListText = (products: string[]) => products.length ? products.map(fuelProductLabel).join(", ") : "전체 유종";
/** 조사 "로/으로": 마지막 글자에 받침(ㄹ 제외)이 있으면 "으로". 한글이 아니면(LPG=엘피지) "로". */
function withRo(word: string) {
  const code = word.charCodeAt(word.length - 1) - 0xac00;
  const final = code >= 0 && code < 11172 ? code % 28 : 0;
  return `${word}${final && final !== 8 ? "으로" : "로"}`;
}

/**
 * 맨 위 유종·필터 다중 선택. 예전 필터 버튼·서랍의 내용(유종, 지도 최저가, 주유소 조건·품질인증, 상표, 초기화)을
 * 한 팝오버의 묶음으로 담는다. 바꾸면 바로 서버 조건에 적용되고 이 브라우저에 저장된다(저장은 부모가 맡는다).
 * 닫으면 Radix가 이 트리거로 초점을 돌려준다.
 */
export function PublicFuelFilterMenu({ products, onProductsChange, filters = DEFAULT_PUBLIC_FUEL_FILTERS, onFiltersChange, linked }: {
  products: string[]; onProductsChange: (products: string[]) => void;
  filters?: PublicFuelFilters; onFiltersChange?: (filters: PublicFuelFilters) => void;
  linked?: PublicFuelLinkedProduct;
}) {
  const [open, setOpen] = useState(false);
  const count = onFiltersChange ? activeFilterCount(filters, products) : 0;
  const productText = productListText(products);
  const noteId = useId();
  return <Popover open={open} onOpenChange={setOpen} modal>
    <PopoverTrigger asChild>
      <button type="button" className="public-fuel-filter-trigger"
        aria-label={`유종·필터: ${productText}${linked ? " (통계 화면에서 연 유종)" : ""}${count ? `, 조건 ${count}개 적용 중` : ""}`}
        data-linked={linked ? "true" : undefined}>
        {/* 통계에서 연 유종이면 맨 앞 필터 아이콘 자리에 "통계" 표시를 둔다(320px에서도 유종 이름이 잘리지 않게 폭을 늘리지 않는다). */}
        {linked ? <span className="public-fuel-filter-linked-mark" aria-hidden="true">통계</span>
          : <SlidersHorizontal aria-hidden="true" size={16} className="public-fuel-filter-trigger-icon" />}
        <span className="public-fuel-filter-trigger-value" aria-hidden="true">{productText}</span>
        {count ? <span className="public-fuel-filter-count" aria-hidden="true">{count}</span> : null}
        <ChevronDown aria-hidden="true" size={16} className="public-fuel-filter-trigger-chevron" />
      </button>
    </PopoverTrigger>
    {/* 링크 유종이면 안내를 대화상자 설명으로 읽히고, 첫 초점은 안내 단추가 아니라 첫 유종 선택에 둔다(연타로 잘못 누르지 않게). */}
    <PopoverContent align="start" collisionPadding={8} aria-label="유종·필터" className="public-fuel-filter-menu"
      aria-describedby={linked ? noteId : undefined}
      onOpenAutoFocus={linked ? event => {
        event.preventDefault();
        (event.currentTarget as HTMLElement | null)?.querySelector<HTMLInputElement>(".fuel-filter-form input")?.focus();
      } : undefined}>
      {/* 돌아가면 안내가 사라지므로(누른 단추도 사라진다) 팝오버를 닫아 초점을 트리거로 돌린다. */}
      {linked ? <LinkedProductNote id={noteId} linked={linked} onDone={() => setOpen(false)} /> : null}
      <FuelFilterForm products={products} onProductsChange={onProductsChange} filters={filters} onFiltersChange={onFiltersChange}
        onClose={() => setOpen(false)} />
    </PopoverContent>
  </Popover>;
}

/** 링크 유종 안내. 여기서 유종을 바꾸면 그 선택을 저장한다는 것과, 저장한 선택으로 돌아가는 단추를 함께 보인다. */
function LinkedProductNote({ id, linked, onDone }: { id: string; linked: PublicFuelLinkedProduct; onDone: () => void }) {
  const opened = `통계 화면에서 고른 ${withRo(fuelProductLabel(linked.code))} 열었습니다.`;
  const saved = linked.saved === null ? null : productListText(linked.saved);
  const rest = !linked.canSave ? "이 브라우저는 유종 선택을 저장할 수 없어, 아래에서 바꾸면 이번 화면에서만 바뀝니다."
    : saved === null ? "아래에서 유종을 고르면 그 선택을 이 브라우저에 저장합니다."
    : `저장한 유종(${saved})은 그대로이며, 아래에서 유종을 바꾸면 그 선택을 저장합니다.`;
  return <div className="fuel-filter-linked">
    <p id={id}>{opened} {rest}</p>
    <Button type="button" variant="outline" size="sm" onClick={() => { linked.onUseSaved(); onDone(); }}>
      {saved === null ? "전체 유종 보기" : "저장한 유종으로 보기"}</Button>
  </div>;
}

function FuelFilterForm({ filters, onFiltersChange, products, onProductsChange, onClose }: {
  filters: PublicFuelFilters; onFiltersChange?: (filters: PublicFuelFilters) => void;
  products: string[]; onProductsChange: (products: string[]) => void; onClose: () => void;
}) {
  const selected = new Set(products);
  const toggleProduct = (code: string, checked: boolean) =>
    onProductsChange(FUEL_CHART_ORDER.filter(value => value === code ? checked : selected.has(value)));
  const close = useRef<HTMLButtonElement>(null);
  const dirty = products.length > 0 || (onFiltersChange ? activeFilterCount(filters) > 0 || filters.brands.length > 0 : false);
  return <div className="fuel-filter-form">
    <fieldset className="fuel-filter-section">
      <legend>유종</legend>
      <label className="fuel-filter-row">
        <span>전체 유종</span>
        {/* 이미 전체면 눌러도 그대로다(비활성으로 바꾸면 누른 순간 초점이 팝오버 밖으로 빠진다). */}
        <input type="checkbox" checked={!products.length} onChange={() => { if (products.length) onProductsChange([]); }} />
      </label>
      {PRODUCT_CHOICES.map(({ code, label }) => <label key={code} className="fuel-filter-row">
        <span>{label}</span>
        <input type="checkbox" checked={selected.has(code)} onChange={event => toggleProduct(code, event.target.checked)} />
      </label>)}
    </fieldset>
    {onFiltersChange ? <FuelStationFilterSections filters={filters} onFiltersChange={onFiltersChange} products={products} /> : null}
    <div className="fuel-filter-actions">
      <Button type="button" variant="outline" disabled={!dirty}
        onClick={() => { onProductsChange([]); onFiltersChange?.(DEFAULT_PUBLIC_FUEL_FILTERS); close.current?.focus(); }}>초기화</Button>
      <Button ref={close} type="button" onClick={onClose}>닫기</Button>
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
          <span aria-hidden="true" className="fuel-filter-brand-mark"><FuelBrandIcon decorative code={brand.icon === "ETC" ? null : brand.icon} name={brand.label} className="fuel-filter-brand-icon" /></span>
          <span>{brand.label}{!relevant ? <small> · 이 유종 없음(적용 안 함)</small> : null}</span>
          <input type="checkbox" checked={isBrandChecked(filters, brand.key)} disabled={!relevant}
            onChange={event => onFiltersChange(toggleBrand(filters, brand.key, event.target.checked, products))} />
        </label>;
      })}
      <label className="fuel-filter-row">
        <span>브랜드 전체 선택</span>
        <input type="checkbox" checked={allBrands} onChange={() => { if (!allBrands) onFiltersChange({ ...filters, brands: [] }); }} />
      </label>
    </fieldset>
  </>;
}
