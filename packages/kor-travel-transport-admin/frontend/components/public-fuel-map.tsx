"use client";

import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { LocateFixed } from "lucide-react";
import { CameraRequest, UserLocationMarker, type CameraTarget } from "@/components/map-overlays";
import { TransportMap } from "@/components/transport-map";
import { Button } from "@/components/ui/button";
import { publicFuelGet } from "@/lib/public-fuel";
import {
  LOCATE_MESSAGES, LOCATE_WATCHDOG_MS, RETRYABLE_LOCATE_FAILURES, isLocateFailure, requestUserPosition, type LocateFailure,
} from "@/lib/locate-user";
import { FUEL_PRODUCT_LABELS } from "@/lib/transport-presentation";

// Keep the shared map's existing paths and request cancellation; only its reader changes.
const loadFuel: typeof publicFuelGet = (path, signal) => publicFuelGet(path.replace(/^transport\//, ""), signal);

const PRODUCT_STORAGE_KEY = "transport.public-fuel.products";
const PRODUCT_STORAGE_EVENT = "transport:public-fuel-products";

function subscribeToProductPreferences(callback: () => void) {
  const onStorage = (event: StorageEvent) => {
    if (event.key === null || event.key === PRODUCT_STORAGE_KEY) callback();
  };
  window.addEventListener("storage", onStorage);
  window.addEventListener(PRODUCT_STORAGE_EVENT, callback);
  return () => {
    window.removeEventListener("storage", onStorage);
    window.removeEventListener(PRODUCT_STORAGE_EVENT, callback);
  };
}

function getStoredProducts() {
  try { return window.localStorage.getItem(PRODUCT_STORAGE_KEY); }
  catch { return null; }
}

function parseProductPreferences(value: string | null): string[] {
  if (value === null) return [];
  try {
    const parsed: unknown = JSON.parse(value);
    if (Array.isArray(parsed)) {
      return [...new Set(parsed.filter((code): code is string =>
        typeof code === "string" && Object.hasOwn(FUEL_PRODUCT_LABELS, code)))];
    }
  } catch { /* 잘못 저장된 값은 전체 유종으로 복원한다. */ }
  return [];
}

export function PublicFuelMap({ refreshEnabled = false }: { refreshEnabled?: boolean }) {
  const [location, setLocation] = useState<CameraTarget>();
  const [locating, setLocating] = useState(false);
  const [locationError, setLocationError] = useState<LocateFailure>();
  // 한 번 위치를 찾은 뒤에는 위치가 바뀌는 대로 점만 옮긴다(카메라는 다시 옮기지 않는다).
  const [userPosition, setUserPosition] = useState<[number, number]>();
  const watch = useRef<number | undefined>(undefined);
  const [temporaryProducts, setTemporaryProducts] = useState<string[]>();
  const storedProducts = useSyncExternalStore(subscribeToProductPreferences, getStoredProducts, () => null);
  const products = useMemo(() => temporaryProducts ?? parseProductPreferences(storedProducts), [temporaryProducts, storedProducts]);
  const request = useRef(0);
  // 진행 중인 요청이 있으면 새 요청을 겹쳐 보내지 않는다(연타·키보드 반복).
  const inFlight = useRef(false);
  const timeout = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => {
    request.current++;
    clearTimeout(timeout.current);
    if (watch.current !== undefined) navigator.geolocation?.clearWatch(watch.current);
    watch.current = undefined;
  }, []);
  function onProductsChange(value: string[]) {
    try {
      window.localStorage.setItem(PRODUCT_STORAGE_KEY, JSON.stringify(value));
      setTemporaryProducts(undefined);
      window.dispatchEvent(new Event(PRODUCT_STORAGE_EVENT));
    } catch {
      setTemporaryProducts(value);
    }
  }

  const inKorea = (longitude: number, latitude: number) => Number.isFinite(longitude) && Number.isFinite(latitude)
    && longitude >= 124 && longitude <= 132 && latitude >= 32 && latitude <= 39.5;
  // 추적을 멈추면 점도 지운다. 오래된 위치를 현재 위치처럼 남기지 않는다.
  function stopWatching() {
    if (watch.current !== undefined) navigator.geolocation?.clearWatch(watch.current);
    watch.current = undefined;
  }
  function startWatching(geolocation: Geolocation) {
    if (watch.current !== undefined || typeof geolocation.watchPosition !== "function") return;
    watch.current = geolocation.watchPosition(next => {
      const { longitude: x, latitude: y } = next.coords;
      if (inKorea(x, y)) setUserPosition([x, y]);
    }, error => {
      // 권한 철회만 추적을 끝낸다. 신호 끊김·시간 초과는 일시적이라 마지막 점을 유지하고 계속 기다린다.
      if (error?.code !== 1) return;
      stopWatching();
      setUserPosition(undefined);
    }, { enableHighAccuracy: false, maximumAge: 30_000 });
  }
  function fail(id: number, failure: LocateFailure) {
    if (request.current !== id) return;
    clearTimeout(timeout.current);
    inFlight.current = false;
    setLocating(false);
    setLocationError(failure);
    if (failure === "denied") { stopWatching(); setUserPosition(undefined); }
  }
  function locate() {
    if (inFlight.current) return;
    const id = ++request.current;
    clearTimeout(timeout.current);
    if (window.isSecureContext === false) { setLocationError("insecure"); return; }
    const geolocation = navigator.geolocation;
    if (!geolocation) { setLocationError("unsupported"); return; }
    inFlight.current = true;
    setLocationError(undefined);
    setLocating(true);
    // 안전 상한: 응답 없는 위치 제공자에서 버튼이 계속 돌지 않게 한다. 늦게 온 위치는 그대로 반영한다
    // (권한 창을 오래 본 경우). 사용자가 다시 누르면 새 요청이 이전 응답을 대신한다.
    timeout.current = setTimeout(() => {
      if (request.current !== id || !inFlight.current) return;
      inFlight.current = false;
      setLocating(false);
      setLocationError("timeout");
    }, LOCATE_WATCHDOG_MS);
    requestUserPosition(geolocation).then(position => {
      if (request.current !== id) return;
      const { longitude, latitude } = position.coords;
      if (!inKorea(longitude, latitude)) { fail(id, "outside"); return; }
      clearTimeout(timeout.current);
      inFlight.current = false;
      setLocating(false);
      setLocationError(undefined);
      setLocation({ center: [longitude, latitude], zoom: 14, id: `location:${id}` });
      setUserPosition([longitude, latitude]);
      startWatching(geolocation);
    }, (failure: unknown) => fail(id, isLocateFailure(failure) ? failure : "unavailable"));
  }
  return <main className="public-fuel-surface" aria-label="주변 주유소 유가 지도">
    <TransportMap mode="fuel" load={loadFuel} mapOnly publicFuel={{ products, onProductsChange, refreshEnabled }} layers={<><CameraRequest target={location} /><UserLocationMarker position={userPosition} /></>} />
    <div className="public-fuel-location">
      <Button type="button" variant="outline" onClick={locate} loading={locating} aria-label="내 위치 주변 유가 보기">
        <LocateFixed aria-hidden="true" size={18} />
      </Button>
      {locationError ? <div className="public-fuel-location-status" data-failure={locationError}>
        <p role="status">{LOCATE_MESSAGES[locationError]}</p>
        {RETRYABLE_LOCATE_FAILURES.has(locationError)
          ? <Button type="button" variant="outline" size="sm" className="public-fuel-location-retry" onClick={locate}>다시 시도</Button> : null}
      </div> : null}
    </div>
  </main>;
}
