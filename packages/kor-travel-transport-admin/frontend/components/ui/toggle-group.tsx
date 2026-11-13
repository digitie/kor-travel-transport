"use client";

import { createContext, useContext, type ComponentProps } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * 공용 UI 패키지에는 토글 그룹이 없어 Map의 Button을 `aria-pressed` 토글로 쓴다.
 * 단일 선택만 지원한다. 값 배열의 첫 항목이 선택 상태이고, 같은 항목을 다시 누르면 빈 배열이다.
 */
type ToggleGroupContextValue = {
  value: readonly string[];
  onValueChange?: (value: string[]) => void;
  variant: "default" | "outline";
};

const ToggleGroupContext = createContext<ToggleGroupContextValue>({ value: [], variant: "default" });

type ToggleGroupProps = Omit<ComponentProps<"div">, "defaultValue" | "onChange"> & {
  value?: readonly string[];
  onValueChange?: (value: string[]) => void;
  variant?: "default" | "outline";
};

function ToggleGroup({ value = [], onValueChange, variant = "default", className, children, ...props }: ToggleGroupProps) {
  return (
    <ToggleGroupContext.Provider value={{ value, onValueChange, variant }}>
      <div role="group" data-slot="toggle-group" className={cn("inline-flex flex-wrap items-center gap-1", className)} {...props}>
        {children}
      </div>
    </ToggleGroupContext.Provider>
  );
}

type ToggleGroupItemProps = Omit<ComponentProps<typeof Button>, "value"> & {
  value: string;
};

function ToggleGroupItem({ value, className, onClick, children, ...props }: ToggleGroupItemProps) {
  const group = useContext(ToggleGroupContext);
  const pressed = group.value.includes(value);
  return (
    <Button
      type="button"
      variant={pressed ? "secondary" : group.variant === "outline" ? "outline" : "ghost"}
      data-slot="toggle-group-item"
      data-state={pressed ? "on" : "off"}
      aria-pressed={pressed}
      className={className}
      onClick={(event) => {
        onClick?.(event);
        group.onValueChange?.(pressed ? [] : [value]);
      }}
      {...props}
    >
      {children}
    </Button>
  );
}

export { ToggleGroup, ToggleGroupItem };
export type { ToggleGroupItemProps, ToggleGroupProps };
