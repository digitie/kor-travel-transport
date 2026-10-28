"use client";

import { Fuel } from "lucide-react";
import { useState } from "react";
import { fuelBrand } from "@/lib/fuel-brands";
import { cn } from "@/lib/utils";

export function FuelBrandIcon({ code, name, className }: { code?: string | null; name?: string | null; className?: string }) {
  const brand = fuelBrand(code, name);
  const [failedImage, setFailedImage] = useState<string>();
  const source = brand.image ? `/fuel-brands/${brand.image}` : null;
  return <span className={cn("fuel-brand-icon", className)} title={brand.name}>
    {source && failedImage !== source
      // 제공기관의 작은 원본 로고를 원래 비율로 표시한다. Next 이미지 변환/외부 요청을 사용하지 않는다.
      // eslint-disable-next-line @next/next/no-img-element
      ? <img src={source} alt={brand.name} width={40} height={24} onError={() => setFailedImage(source)} />
      : <><Fuel size={20} aria-hidden="true" /><span className="sr-only">{brand.name}</span></>}
  </span>;
}
