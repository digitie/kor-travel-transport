import L from "leaflet";
import type { Station, Query } from "./model";
import { money } from "./model";
import "leaflet/dist/leaflet.css";
/** 표시 상한은20곳이다. 화면에서 겹치는 값은 묶고 최대 확대에서도 목록으로 선택한다. */
export class FuelMap {
    private map: L.Map;
    private markers = L.layerGroup();
    private tiles: L.TileLayer;
    private circle: L.Circle | null = null;
    private rows: Station[] = [];
    private selected: string | null = null;
    private onSelect: (station: Station) => void = () => { };
    constructor(container: HTMLElement, onTileError: () => void, query: Query) {
        this.map = L.map(container, { scrollWheelZoom: false, attributionControl: true }).setView([query.latitude, query.longitude], 12);
        this.tiles = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a>' });
        this.tiles.on("tileerror", onTileError);
        this.tiles.addTo(this.map);
        this.markers.addTo(this.map);
        this.map.on("zoomend moveend", () => this.draw());
    }
    private draw() {
        this.markers.clearLayers();
        if (this.circle) {
            const center = document.createElement("span");
            center.className = "fuel-origin";
            center.textContent = "검색 중심";
            L.marker(this.circle.getLatLng(), { icon: L.divIcon({ html: center, className: "fuel-origin-host", iconSize: [72, 24], iconAnchor: [36, -12] }) }).addTo(this.markers);
        }
        const groups: {
            point: L.Point;
            rows: Station[];
        }[] = [];
        for (const station of this.rows) {
            if (station.latitude == null || station.longitude == null)
                continue;
            const point = this.map.project([station.latitude, station.longitude]);
            const group = station.station_key === this.selected ? null : groups.find(group => group.rows[0].station_key !== this.selected && group.point.distanceTo(point) < 80);
            if (group)
                group.rows.push(station);
            else
                groups.push({ point, rows: [station] });
        }
        for (const { rows } of groups) {
            const first = rows[0], single = rows.length === 1;
            const label = document.createElement("span");
            label.className = "fuel-marker" + (this.selected === first.station_key ? " is-selected" : "");
            label.textContent = money(Math.min(...rows.map(station => station.price)));
            if (!single) {
                const count = document.createElement("small");
                count.textContent = `${rows.length}곳`;
                label.append(count);
            }
            const marker = L.marker([first.latitude!, first.longitude!], { title: single ? `${first.name} ${money(first.price)}원` : `주유소 ${rows.length}곳 · 최저 ${label.firstChild?.textContent}원 · 확대 또는 목록 선택`, alt: single ? first.name : `주유소 ${rows.length}곳`, keyboard: true, zIndexOffset: this.selected === first.station_key ? 1000 : 0,
                icon: L.divIcon({ html: label, className: "fuel-marker-host", iconSize: [74, single ? 32 : 46], iconAnchor: [37, single ? 32 : 46] }) }).addTo(this.markers);
            marker.on("click", () => {
                if (single) {
                    this.onSelect(first);
                    return;
                }
                if (this.map.getZoom() < 19) {
                    this.map.fitBounds(L.latLngBounds(rows.map(s => [s.latitude!, s.longitude!] as [
                        number,
                        number
                    ])), { padding: [30, 30], maxZoom: 19, animate: false });
                    return;
                }
                const list = document.createElement("div");
                list.className = "fuel-map-choices";
                for (const station of rows) {
                    const button = document.createElement("button");
                    button.type = "button";
                    button.textContent = `${station.name} · ${money(station.price)}원/L`;
                    button.onclick = () => { this.map.closePopup(); this.onSelect(station); };
                    list.append(button);
                }
                marker.bindPopup(list).openPopup();
            });
        }
    }
    update(query: Query, rows: Station[], selected: string | null, onSelect: (station: Station) => void) {
        this.rows = rows;
        this.selected = selected;
        this.onSelect = onSelect;
        this.circle?.remove();
        this.circle = L.circle([query.latitude, query.longitude], { radius: query.radius_m, weight: 1, fillOpacity: .05 }).addTo(this.map);
        this.map.fitBounds(this.circle.getBounds(), { padding: [25, 25], maxZoom: 16, animate: false });
        this.map.invalidateSize();
        this.draw();
    }
    focus(station: Station) { if (station.latitude != null && station.longitude != null)
        this.map.setView([station.latitude, station.longitude], Math.max(15, this.map.getZoom()), { animate: false }); }
    retry() { this.tiles.redraw(); }
    destroy() { this.map.remove(); }
}
