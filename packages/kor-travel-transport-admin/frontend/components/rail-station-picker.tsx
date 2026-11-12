"use client";

import { useEffect, useState } from "react";
import type { RailStation } from "@/lib/general-rail";
import { FilterCombobox } from "./filter-combobox";

type Props = {
  id: string; label: string; stations: RailStation[]; value: RailStation | null;
  onChange: (station: RailStation | null) => void; disabled?: boolean;
  searchRequest?: { revision: number; text: string };
};

/** 역 ID는 TAGO 정본을 유지하고, 역 안내의 이름은 검색어로만 전달한다. */
export function RailStationPicker({ id, label, stations, value, onChange, disabled = false, searchRequest }: Props) {
  const revision = searchRequest?.revision ?? 0;
  const selectedId = value?.station_id ?? "";
  const labels = new Map(stations.map(station => [station.station_id, [station.station_name, station.city_name].filter(Boolean).join(" · ")]));
  const [search, setSearch] = useState({ revision: -1, selectedId: "", text: "" });
  const input = search.revision === revision && search.selectedId === selectedId
    ? search.text : (value ? labels.get(selectedId) ?? value.station_name : searchRequest?.text ?? "");
  useEffect(() => {
    if (revision && !disabled) document.getElementById(id)?.focus();
  }, [revision, disabled, id]);
  function choose(values: string[]) {
    const station = stations.find(row => row.station_id === values[0]) ?? null;
    setSearch({ revision, selectedId: station?.station_id ?? "", text: station ? labels.get(station.station_id) ?? station.station_name : "" });
    onChange(station);
  }
  function searchStations(text: string) {
    const clearsSelection = value && text !== (labels.get(selectedId) ?? value.station_name);
    setSearch({ revision, selectedId: clearsSelection ? "" : selectedId, text });
    if (clearsSelection) onChange(null);
  }
  return <div className="train-station-search">
    <label htmlFor={id}>{label}</label>
    <FilterCombobox id={id} mode="single" disabled={disabled}
      options={stations.map(station => ({ value: station.station_id, label: labels.get(station.station_id) ?? station.station_name }))}
      value={value ? [selectedId] : []} onChange={choose} placeholder={label + " 이름 검색"}
      inputValue={input} onInputValueChange={searchStations} />
  </div>;
}
