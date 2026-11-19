import { buttonVariants as commonButtonVariants } from "@kor-travel/ui/button-variants";

import { cn } from "@/lib/utils";

/**
 * disabled 설명(title) 도달성만 덧붙인다. 색상·크기·포커스는 공통 정본이다.
 * 포커스는 공통 recipe의 outline 2px·offset 2px 하나뿐이다(UX-G9.1·FS-7.8). 여기서 `outline-solid`를
 * 다시 붙이면 tailwind-merge가 공통 `outline-none`을 지운 채 쉬는 상태에도 outline-style:solid가 남아
 * 기본 굵기(medium, 3px)의 currentColor 테두리가 덧그려진다. focus outline·ring 조정도 두지 않는다.
 */
const buttonInteractionClasses = "disabled:opacity-100 disabled:pointer-events-auto";

/** Link/a 소비자도 같은 공통 recipe와 Map 상호작용 정책을 쓴다. */
function buttonVariants(options: Parameters<typeof commonButtonVariants>[0] = {}) {
  const { class: classValue, className, ...variants } = options ?? {};
  return cn(
    commonButtonVariants(variants),
    buttonInteractionClasses,
    classValue,
    className,
  );
}

export { buttonVariants, buttonInteractionClasses };
