"use client";

import { useRef } from "react";
import { Combobox, ComboboxChip, ComboboxChips, ComboboxChipsInput, ComboboxContent, ComboboxEmpty, ComboboxItem, ComboboxList, ComboboxValue } from "@/components/ui/combobox";

export function FilterCombobox({ id, options, value, onChange, placeholder }: {
  id: string;
  options: { value: string; label: string }[];
  value: string[];
  onChange: (value: string[]) => void;
  placeholder: string;
}) {
  const anchor = useRef<HTMLDivElement | null>(null);
  const label = (value: string) => options.find((option) => option.value === value)?.label ?? value;
  return <Combobox multiple items={options.map((option) => option.value)} value={value} onValueChange={(next, details) => {
    // 검색창의 Escape는 목록/검색어만 닫는다. 필터 해제는 칩 삭제로 명시한다.
    if (details.reason === "escape-key") details.cancel();
    else onChange(next);
  }} itemToStringLabel={label}>
    <ComboboxChips ref={anchor}>
      <ComboboxValue>{value.map((item) => <ComboboxChip key={item} label={label(item)}>{label(item)}</ComboboxChip>)}</ComboboxValue>
      <ComboboxChipsInput id={id} placeholder={value.length ? "추가 선택" : placeholder} />
    </ComboboxChips>
    <ComboboxContent anchor={anchor}>
      <ComboboxEmpty>검색 결과가 없습니다.</ComboboxEmpty>
      <ComboboxList>{(item: string) => <ComboboxItem key={item} value={item} disabled={value.length >= 10 && !value.includes(item)}>{label(item)}</ComboboxItem>}</ComboboxList>
    </ComboboxContent>
  </Combobox>;
}
