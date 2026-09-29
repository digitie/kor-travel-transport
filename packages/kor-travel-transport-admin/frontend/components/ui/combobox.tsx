"use client";

import * as React from "react";
import { Combobox as Primitive } from "@base-ui/react/combobox";
import { CheckIcon, XIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

// shadcn base-nova의 다중 선택 구성을 사용하고 기존 Weather 치수·토큰을 유지한다.
export const Combobox = Primitive.Root;
export const ComboboxValue = Primitive.Value;

export function ComboboxContent({ className, anchor, ...props }: Primitive.Popup.Props & Pick<Primitive.Positioner.Props, "anchor">) {
  return <Primitive.Portal><Primitive.Positioner anchor={anchor} sideOffset={6} align="start" className="isolate z-50">
    <Primitive.Popup data-slot="combobox-content" className={cn("max-h-(--available-height) w-(--anchor-width) max-w-(--available-width) overflow-hidden rounded-md bg-popover text-popover-foreground shadow-md ring-1 ring-foreground/10", className)} {...props} />
  </Primitive.Positioner></Primitive.Portal>;
}

export function ComboboxList({ className, ...props }: Primitive.List.Props) {
  return <Primitive.List data-slot="combobox-list" className={cn("max-h-[min(16rem,var(--available-height))] overflow-y-auto overscroll-contain p-1", className)} {...props} />;
}

export function ComboboxItem({ children, className, ...props }: Primitive.Item.Props) {
  return <Primitive.Item data-slot="combobox-item" className={cn("relative flex min-h-11 w-full cursor-default items-center gap-2 rounded-md py-2 pr-8 pl-2 text-sm outline-none select-none data-highlighted:bg-accent data-highlighted:text-accent-foreground data-disabled:pointer-events-none data-disabled:opacity-50", className)} {...props}>
    <span className="min-w-0 whitespace-normal break-all">{children}</span><Primitive.ItemIndicator className="pointer-events-none absolute right-2"><CheckIcon className="size-4" /></Primitive.ItemIndicator>
  </Primitive.Item>;
}

export function ComboboxEmpty(props: Primitive.Empty.Props) {
  return <Primitive.Empty data-slot="combobox-empty" className="p-3 text-sm text-muted-foreground empty:hidden" {...props} />;
}

export function ComboboxChips({ className, ...props }: React.ComponentPropsWithRef<typeof Primitive.Chips>) {
  return <Primitive.Chips data-slot="combobox-chips" className={cn("flex min-h-(--control-h) min-w-0 flex-wrap items-center gap-1 rounded-md border border-input bg-card px-2 py-1 text-sm focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/50 pointer-coarse:min-h-11", className)} {...props} />;
}

export function ComboboxChip({ children, label, ...props }: Primitive.Chip.Props & { label: string }) {
  return <Primitive.Chip data-slot="combobox-chip" className="flex min-w-0 max-w-full items-center gap-1 rounded-sm bg-muted pl-2 text-sm text-foreground" {...props}>
    <span className="min-w-0 truncate" title={label}>{children}</span>
    <Primitive.ChipRemove data-slot="combobox-chip-remove" aria-label={`${label} 선택 해제`} render={<Button variant="ghost" size="icon-sm" className="pointer-coarse:size-11" />}><XIcon data-icon="inline-end" /></Primitive.ChipRemove>
  </Primitive.Chip>;
}

export function ComboboxChipsInput({ className, ...props }: Primitive.Input.Props) {
  return <Primitive.Input data-slot="combobox-chip-input" className={cn("min-h-[calc(var(--control-h)-0.625rem)] min-w-16 flex-1 bg-transparent outline-none placeholder:text-muted-foreground", className)} {...props} />;
}
