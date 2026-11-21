"use client";

import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { LocateFixed } from "lucide-react";
import { CameraRequest, UserLocationMarker, type CameraTarget } from "@/components/map-overlays";
import { TransportMap } from "@/components/transport-map";
import { Button } from "@/components/ui/button";
import { publicFuelGet } from "@/lib/public-fuel";
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
  const [locationError, setLocationError] = useState("");
  // 한 번 위치를 찾은 뒤에는 위치가 바뀌는 대로 점만 옮긴다(카메라는 다시 옮기지 않는다).
  const [userPosition, setUserPosition] = useState<[number, number]>();
  const watch = useRef<number | undefined>(undefined);
  const [temporaryProducts, setTemporaryProducts] = useState<string[]>();
  const storedProducts = useSyncExternalStore(subscribeToProductPreferences, getStoredProducts, () => null);
  const products = useMemo(() => temporaryProducts ?? parseProductPreferences(storedProducts), [temporaryProducts, storedProducts]);
  const request = useRef(0);
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
  function locate() {
    const id = ++request.current;
    clearTimeout(timeout.current);
    if (!navigator.geolocation) { setLocationError("위치를 사용할 수 없습니다."); return; }
    setLocationError("");
    setLocating(true);
    const fallback = () => {
      if (request.current !== id) return;
      request.current++;
      clearTimeout(timeout.current);
      setLocating(false);
      setLocationError("위치를 확인하지 못했습니다.");
      stopWatching();
      setUserPosition(undefined);
    };
    timeout.current = setTimeout(fallback, 6500);
    navigator.geolocation.getCurrentPosition(position => {
      if (request.current !== id) return;
      const { longitude, latitude } = position.coords;
      if (!inKorea(longitude, latitude)) { fallback(); return; }
      clearTimeout(timeout.current);
      request.current++;
      setLocating(false);
      setLocation({ center: [longitude, latitude], zoom: 14, id: `location:${id}` });
      setUserPosition([longitude, latitude]);
      if (watch.current === undefined && typeof navigator.geolocation.watchPosition === "function") {
        watch.current = navigator.geolocation.watchPosition(next => {
          const { longitude: x, latitude: y } = next.coords;
          if (inKorea(x, y)) setUserPosition([x, y]);
        }, () => {
          // 권한 철회·신호 끊김: 추적을 멈추고 점을 지운다. 다시 누르면 새로 찾는다.
          stopWatching();
          setUserPosition(undefined);
        }, { enableHighAccuracy: false, maximumAge: 30_000 });
      }
    }, fallback, { enableHighAccuracy: false, timeout: 6000, maximumAge: 60_000 });
  }
  return <main className="public-fuel-surface" aria-label="주변 주유소 유가 지도">
    <TransportMap mode="fuel" load={loadFuel} mapOnly publicFuel={{ products, onProductsChange, refreshEnabled }} layers={<><CameraRequest target={location} /><UserLocationMarker position={userPosition} /></>} />
    <div className="public-fuel-location">
      <Button type="button" variant="outline" onClick={locate} loading={locating} aria-label="내 위치 주변 유가 보기">
        <LocateFixed aria-hidden="true" size={18} />
      </Button>
      {locationError ? <p className="public-fuel-location-status" role="status">{locationError}</p> : null}
    </div>
  </main>;
}
