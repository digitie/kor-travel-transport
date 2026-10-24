"use client";
import { useEffect, useState } from "react";
import { seoulDate } from "./journey";
import type { UserPosition } from "./nearby";

export function useNearbyPosition() {
  const [position, setPosition] = useState<UserPosition | null>(null);
  const [positionError, setError] = useState("");
  const [locating, setLocating] = useState(false);
  function locate() {
    if (!navigator.geolocation) { setError("이 브라우저에서는 현재 위치를 확인할 수 없습니다."); return; }
    setLocating(true); setError("");
    navigator.geolocation.getCurrentPosition((result) => {
      setPosition({ latitude: result.coords.latitude, longitude: result.coords.longitude, accuracy: result.coords.accuracy }); setLocating(false);
    }, (reason) => {
      setLocating(false); setError(reason.code === 1 ? "위치 접근을 허용하면 가까운 장소를 찾을 수 있습니다." : "현재 위치를 확인하지 못했습니다. 이름이나 노선으로 검색해 주세요.");
    }, { enableHighAccuracy: false, timeout: 10_000, maximumAge: 60_000 });
  }
  return { position, positionError, locating, locate };
}

export function useSeoulToday() {
  const [today, setToday] = useState(seoulDate);
  useEffect(() => {
    const update = () => setToday(seoulDate());
    const interval = setInterval(update, 30_000);
    document.addEventListener("visibilitychange", update);
    return () => { clearInterval(interval); document.removeEventListener("visibilitychange", update); };
  }, []);
  return today;
}
