"use client";

import { Popover } from "@base-ui/react/popover";
import { Info, X } from "lucide-react";
import { useLayoutEffect, useRef, type ReactNode } from "react";

/** 터치·키보드로 여는 제목 옆 보조 설명. 오류와 현재 자료의 경고는 접지 않는다. */
export function InfoButton({ label, children, icon }: { label: string; children: ReactNode; icon?: ReactNode }) {
  const popup = useRef<HTMLDivElement | null>(null);
  const close = useRef<HTMLButtonElement | null>(null);
  const lastPopupFocus = useRef<HTMLElement | null>(null);
  const isOpen = useRef(false);
  // 자료 갱신으로 초점이 있던 링크가 제거되면 닫기 버튼으로 복귀한다. 다른 곳으로 옮긴 초점은 건드리지 않는다.
  useLayoutEffect(() => {
    const previous = lastPopupFocus.current;
    if (isOpen.current && popup.current?.isConnected && previous && !previous.isConnected && document.activeElement === document.body) close.current?.focus({ preventScroll: true });
  });
  return <Popover.Root onOpenChange={(open) => { isOpen.current = open; if (!open) lastPopupFocus.current = null; }}>
    <Popover.Trigger className="info-button" aria-label={`${label} 안내`}>{icon ?? <Info size={15} aria-hidden="true" />}</Popover.Trigger>
    <Popover.Portal><Popover.Positioner sideOffset={6} collisionPadding={12} className="info-positioner">
      <Popover.Popup className="info-popup" ref={popup} onFocusCapture={(event) => { lastPopupFocus.current = event.target instanceof HTMLElement ? event.target : null; }} onBlurCapture={(event) => { if (!(event.relatedTarget instanceof Node) || !popup.current?.contains(event.relatedTarget)) lastPopupFocus.current = null; }}>
        <div className="info-popup-heading"><Popover.Title>{label}</Popover.Title><Popover.Close ref={close} aria-label="안내 닫기" className="info-button"><X size={15} aria-hidden="true" /></Popover.Close></div>
        <Popover.Description render={<div />}>{children}</Popover.Description>
      </Popover.Popup>
    </Popover.Positioner></Popover.Portal>
  </Popover.Root>;
}
