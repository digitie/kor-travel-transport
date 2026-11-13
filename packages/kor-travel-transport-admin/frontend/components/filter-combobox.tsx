"use client";

import { MultiFilterCombobox } from "@/components/multi-filter-combobox";

/**
 * 값·라벨 쌍 옵션을 Map의 다중 선택 콤보박스에 맞춘다. 콤보박스는 문자열 옵션만 받으므로
 * 라벨로 보여 주고 선택 값으로 되돌린다. 라벨은 옵션 안에서 유일해야 한다.
 * 입력 요소의 접근성 이름은 `ariaLabel`(없으면 placeholder)로 준다.
 */
export function FilterCombobox({
  options,
  value,
  onChange,
  placeholder,
  ariaLabel,
}: {
  /** 기존 호출부의 `id`는 입력 요소에 붙일 수 없어 받지 않는다(label 연결은 ariaLabel이 맡는다). */
  id?: string;
  options: { value: string; label: string }[];
  value: string[];
  onChange: (value: string[]) => void;
  placeholder: string;
  ariaLabel?: string;
  /** 예전 밀도 옵션. Map의 다중 선택 콤보박스는 한 가지 밀도만 쓰므로 무시한다. */
  compact?: boolean;
}) {
  const labelOf = (item: string) => options.find((option) => option.value === item)?.label ?? item;
  const valueOf = (label: string) => options.find((option) => option.label === label)?.value ?? label;
  return (
    <MultiFilterCombobox
      ariaLabel={ariaLabel ?? placeholder}
      placeholder={placeholder}
      options={options.map((option) => option.label)}
      values={value.map(labelOf)}
      onChange={(labels) => onChange(labels.map(valueOf))}
    />
  );
}
