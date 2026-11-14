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
      // 콤보박스는 표시용으로 정렬된 목록을 돌려준다. 조회 조건은 선택한 순서를 유지한다.
      onChange={(labels) => {
        const next = labels.map(valueOf);
        onChange([...value.filter((item) => next.includes(item)), ...next.filter((item) => !value.includes(item))]);
      }}
      // 고정 코드 목록 필터다 — 목록 밖 입력을 값으로 만들지 않고, API 상한(10개)을 넘기지 않는다.
      allowCreate={false}
      maxSelected={10}
      maxVisible={options.length}
      emptyText="검색 결과가 없습니다."
      removeLabel={(label) => `${label} 선택 해제`}
    />
  );
}
