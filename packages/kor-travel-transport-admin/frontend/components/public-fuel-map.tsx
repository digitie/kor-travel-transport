"use client";

import { useEffect, useRef, useState } from "react";
import { LocateFixed } from "lucide-react";
import { CameraRequest, type CameraTarget } from "@/components/map-overlays";
import { TransportMap } from "@/components/transport-map";
import { Button } from "@/components/ui/button";
import { publicFuelGet } from "@/lib/public-fuel";

// Keep the shared map's existing paths and request cancellation; only its reader changes.
const loadFuel: typeof publicFuelGet = (path, signal) => publicFuelGet(path.replace(/^transport\//, ""), signal);

export function PublicFuelMap() {
  const [location, setLocation] = useState<CameraTarget>();
  const [view, setView] = useState<"map" | "list">("map");
  const [locating, setLocating] = useState(false);
  const [message, setMessage] = useState("현재 지도 범위의 유가를 표시합니다.");
  const request = useRef(0);
  const timeout = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => { request.current++; clearTimeout(timeout.current); }, []);
  function locate() {
    const id = ++request.current;
    clearTimeout(timeout.current);
    if (!navigator.geolocation) { setMessage("위치를 사용할 수 없어 현재 지도 범위를 표시합니다."); return; }
    setLocating(true);
    const fallback = () => {
      if (request.current !== id) return;
      request.current++;
      clearTimeout(timeout.current);
      setLocating(false);
      setMessage("위치를 확인하지 못해 현재 지도 범위를 표시합니다.");
    };
    timeout.current = setTimeout(fallback, 6500);
    navigator.geolocation.getCurrentPosition(position => {
      if (request.current !== id) return;
      const { longitude, latitude } = position.coords;
      if (!Number.isFinite(longitude) || !Number.isFinite(latitude) || longitude < 124 || longitude > 132 || latitude < 32 || latitude > 39.5) { fallback(); return; }
      clearTimeout(timeout.current);
      request.current++;
      setLocating(false);
      setView("map");
      setLocation({ center: [longitude, latitude], zoom: 14, id: `location:${id}` });
      setMessage("내 위치 주변의 유가를 표시합니다.");
    }, fallback, { enableHighAccuracy: false, timeout: 6000, maximumAge: 60_000 });
  }
  return <main className="public-fuel-surface" aria-label="주변 주유소 유가 지도">
    <TransportMap mode="fuel" load={loadFuel} view={view} onViewChange={next => { setView(next); setLocation(undefined); }} layers={<CameraRequest target={location} />} />
    <div className="public-fuel-location">
      <Button type="button" variant="outline" onClick={locate} disabled={locating} aria-label="내 위치 주변 유가 보기"><LocateFixed aria-hidden="true" size={18} />{locating ? "위치 확인 중" : "내 위치"}</Button>
      <p className="public-fuel-location-status" role="status">{message}</p>
    </div>
  </main>;
}
