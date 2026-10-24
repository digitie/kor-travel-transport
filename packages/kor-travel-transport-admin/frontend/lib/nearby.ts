import { hasCoordinates } from "./journey";

export type UserPosition = { latitude: number; longitude: number; accuracy: number };
export function distanceKm(a: Pick<UserPosition, "latitude" | "longitude">, b: Pick<UserPosition, "latitude" | "longitude">) {
  const rad = Math.PI / 180;
  const lat = (b.latitude - a.latitude) * rad;
  const lon = (b.longitude - a.longitude) * rad;
  const h = Math.sin(lat / 2) ** 2 + Math.cos(a.latitude * rad) * Math.cos(b.latitude * rad) * Math.sin(lon / 2) ** 2;
  return 6371 * 2 * Math.asin(Math.sqrt(Math.min(1, h)));
}
export function nearestPlaces<T extends { longitude: number | null; latitude: number | null }>(items: T[], position: UserPosition) {
  return items.filter(hasCoordinates).map((place) => ({ place, distance: distanceKm(position, place) })).sort((a, b) => a.distance - b.distance);
}
