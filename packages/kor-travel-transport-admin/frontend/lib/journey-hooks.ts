"use client";
import { useEffect, useState } from "react";
import { seoulDate } from "./journey";

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
