"use client";

import { Popover, PopoverTrigger, PopoverContent } from "@kor-travel/ui/popover";
import { Button } from "@kor-travel/ui/button";
import { Info, X } from "lucide-react";
import { useLayoutEffect, useRef, useState, type ReactNode } from "react";

/** 터치·키보드로 여는 제목 옆 보조 설명. 오류와 현재 자료의 경고는 접지 않는다. */
export function InfoButton({ label, children, icon }: { label: string; children: ReactNode; icon?: ReactNode }) {
  const [open, setOpen] = useState(false);
  const popup = useRef<HTMLDivElement | null>(null);
  const close = useRef<HTMLButtonElement | null>(null);
  const lastPopupFocus = useRef<HTMLElement | null>(null);
  const isOpen = useRef(false);
  // 자료 갱신으로 초점이 있던 링크가 제거되면 닫기 버튼으로 복귀한다. 다른 곳으로 옮긴 초점은 건드리지 않는다.
  useLayoutEffect(() => {
    const previous = lastPopupFocus.current;
    if (isOpen.current && popup.current?.isConnected && previous && !previous.isConnected && document.activeElement === document.body) close.current?.focus({ preventScroll: true });
  });
  return <Popover open={open} onOpenChange={(open) => { setOpen(open); isOpen.current = open; if (!open) lastPopupFocus.current = null; }}>
    <PopoverTrigger className="info-button" aria-label={`${label} 안내`}>{icon ?? <Info size={15} aria-hidden="true" />}</PopoverTrigger>

      <PopoverContent sideOffset={6} collisionPadding={12} aria-label={label} className="info-popup" ref={popup} onFocusCapture={(event) => { lastPopupFocus.current = event.target instanceof HTMLElement ? event.target : null; }} onBlurCapture={(event) => { if (!(event.relatedTarget instanceof Node) || !popup.current?.contains(event.relatedTarget)) lastPopupFocus.current = null; }}>
        <div className="info-popup-heading"><h2>{label}</h2><Button onClick={() => setOpen(false)} ref={close} aria-label="안내 닫기" className="info-button"><X size={15} aria-hidden="true" /></Button></div>
        <div>{children}</div>
      </PopoverContent>

  </Popover>;
}
