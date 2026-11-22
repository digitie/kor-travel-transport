"use client";

import { Fuel } from "lucide-react";
import { useState } from "react";
import { fuelBrand } from "@/lib/fuel-brands";
import { cn } from "@/lib/utils";

/**
 * decorative: 옆에 상표 이름 글자가 이미 있는 자리(공개 유가 필터의 브랜드 행)에서는 아이콘이 이름을 다시 싣지 않는다
 * (title 툴팁·대체 글자·sr-only 이름 없음). 그러지 않으면 "기타"처럼 로고가 없는 행에서 이름이 두 번 나온다.
 */
export function FuelBrandIcon({ code, name, className, decorative = false }: { code?: string | null; name?: string | null; className?: string; decorative?: boolean }) {
  const brand = fuelBrand(code, name);
  const [failedImage, setFailedImage] = useState<string>();
  const source = brand.image ? `/fuel-brands/${brand.image}` : null;
  return <span className={cn("fuel-brand-icon", className)} title={decorative ? undefined : brand.name}>
    {source && failedImage !== source
      // 제공기관의 작은 원본 로고를 원래 비율로 표시한다. Next 이미지 변환/외부 요청을 사용하지 않는다.
      // eslint-disable-next-line @next/next/no-img-element
      ? <img src={source} alt={decorative ? "" : brand.name} width={40} height={24} onError={() => setFailedImage(source)} />
      : <><Fuel size={20} aria-hidden="true" />{decorative ? null : <span className="sr-only">{brand.name}</span>}</>}
  </span>;
}
