import type { ReactNode } from "react";

type Graphic = { id: string; onclick: () => void; onmouseover: () => void; onmouseout: () => void };
type Options = { xAxis?: { min: number; max: number }; series: { id: string; markArea?: { data: { name: string }[][] } }[]; graphic?: Graphic[] };
/** Component tests inspect the domain options; the browser fixture mounts the real engine. */
export function ParkingLinesProbe({ options, height, label }: { options: Options; height: number; label: string }): ReactNode {
  return <div aria-label={label} data-testid="parking-line-probe" data-options={JSON.stringify(options)} style={{ height }}>
    {options.series.filter((line) => line.id !== "parking-history").map((line) => <span key={line.id} data-testid="daily-overlay-line" />)}
    {options.series.flatMap((line) => line.markArea?.data ?? []).map(([band]) => <span key={band.name} data-testid="holiday-band">{band.name}</span>)}
    {options.graphic?.map((marker) => <button key={marker.id} type="button" data-testid="daily-flight-marker" onClick={marker.onclick} onMouseEnter={marker.onmouseover} onMouseLeave={marker.onmouseout}>차트 비행편</button>)}
  </div>;
}
export function lineOptions<T>(): T { return JSON.parse(document.querySelector('[data-testid="parking-line-probe"]')!.getAttribute("data-options")!); }
