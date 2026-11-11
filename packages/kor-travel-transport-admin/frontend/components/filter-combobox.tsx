"use client";

import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Popover, PopoverAnchor, PopoverContent } from "@kor-travel/ui/popover";
import { Button } from "@kor-travel/ui/button";
import { Input } from "@kor-travel/ui/input";
import { Check, X } from "lucide-react";

/** 지도 출처·유종 다중 필터. 포털·충돌 회피·외부 클릭은 공통 Radix가 소유한다. */
export function FilterCombobox({ id, options, value, onChange, placeholder, compact = false }: {
  id: string; options: { value: string; label: string }[]; value: string[];
  onChange: (value: string[]) => void; placeholder: string; compact?: boolean;
}) {
  const anchor = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  useEffect(() => {
    if (!open || !anchor.current) return;
    const observer = new ResizeObserver(() => { if (!anchor.current?.getClientRects().length) setOpen(false); });
    observer.observe(anchor.current); return () => observer.disconnect();
  }, [open]);
  const label = (item: string) => options.find((option) => option.value === item)?.label ?? item;
  const selected = new Set(value);
  const filtered = options.filter((option) => option.label.toLocaleLowerCase().includes(query.toLocaleLowerCase()));
  const optionId = (index: number) => `${id}-option-${index}`;
  function toggle(item: string) {
    if (selected.has(item)) onChange(value.filter((current) => current !== item));
    else if (value.length < 10) onChange([...value, item]);
  }
  function keyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const next = !open ? 0 : (active + (event.key === "ArrowDown" ? 1 : -1) + filtered.length) % Math.max(filtered.length, 1);
      setActive(next); setOpen(true);
      requestAnimationFrame(() => document.getElementById(optionId(next))?.scrollIntoView({ block: "nearest" }));
    } else if (event.key === "Enter" && open) {
      event.preventDefault();
      if (filtered[active]) toggle(filtered[active].value);
    } else if (event.key === "Escape" && open) {
      event.preventDefault(); event.stopPropagation(); setOpen(false); setQuery("");
    }
  }
  return <Popover open={open} onOpenChange={setOpen}>
    <PopoverAnchor asChild><div ref={anchor} data-slot="combobox-chips" className={`flex min-w-0 items-center gap-1 rounded-md border ${compact ? "kt-map-combobox" : "flex-wrap p-1"}`}>
      <div className="kt-map-selected-chips">{value.map((item) => <span key={item} data-slot="combobox-chip" className="inline-flex items-center gap-1 rounded-sm bg-secondary pl-1 text-secondary-foreground">
        <span className="min-w-0 truncate" title={label(item)}>{label(item)}</span>
        <Button variant="ghost" size="icon-xs" data-slot="combobox-chip-remove" aria-label={`${label(item)} 선택 해제`}
          onClick={() => onChange(value.filter((current) => current !== item))}><X aria-hidden="true" /></Button>
      </span>)}</div>
      <Input ref={input} id={id} data-slot="combobox-chip-input" role="combobox" aria-expanded={open}
        aria-controls={open ? `${id}-listbox` : undefined} aria-autocomplete="list"
        aria-activedescendant={open && filtered[active] ? optionId(active) : undefined}
        className="min-w-0 flex-1 border-0 bg-transparent shadow-none" autoComplete="off"
        placeholder={value.length ? "추가 선택" : placeholder} value={query} onFocus={() => setOpen(true)}
        onClick={() => setOpen(true)} onChange={(event) => { setQuery(event.target.value); setActive(0); setOpen(true); }} onKeyDown={keyDown} />
    </div></PopoverAnchor>
    <PopoverContent data-slot="combobox-content" align="start" className="max-h-[min(16rem,var(--radix-popover-content-available-height))] w-(--radix-popover-trigger-width) min-w-48 max-w-[calc(100vw-2rem)] overflow-y-auto"
      onOpenAutoFocus={(event) => event.preventDefault()} onCloseAutoFocus={(event) => event.preventDefault()}
      onInteractOutside={(event) => { if (event.target instanceof Node && anchor.current?.contains(event.target)) event.preventDefault(); }}
      onEscapeKeyDown={() => { setQuery(""); input.current?.focus(); }}>
      <div id={`${id}-listbox`} role="listbox" aria-multiselectable="true" aria-label={placeholder}>
        {filtered.map((option, index) => <button key={option.value} id={optionId(index)} type="button" role="option"
          aria-selected={selected.has(option.value)} disabled={value.length >= 10 && !selected.has(option.value)}
          className={`flex min-h-11 w-full items-center gap-2 rounded-sm px-2 text-left whitespace-normal break-words disabled:opacity-50 ${active === index ? "bg-accent" : ""}`}
          onMouseDown={(event) => event.preventDefault()} onMouseMove={() => setActive(index)} onClick={() => toggle(option.value)}>
          <Check aria-hidden="true" size={14} className={selected.has(option.value) ? "" : "invisible"} />{option.label}
        </button>)}
      </div>
      {!filtered.length ? <p data-slot="combobox-empty">검색 결과가 없습니다.</p> : null}
    </PopoverContent>
  </Popover>;
}
