"use client";
import { useRef } from "react";
import { Combobox, ComboboxChips, ComboboxChipsInput, ComboboxContent, ComboboxEmpty, ComboboxItem, ComboboxList } from "./ui/combobox";
import type { RailStation } from "@/lib/general-rail";

export function RailStationPicker({id,label,stations,value,onChange,disabled=false}:{id:string;label:string;stations:RailStation[];value:RailStation|null;onChange:(station:RailStation|null)=>void;disabled?:boolean}) {
  const anchor=useRef<HTMLDivElement|null>(null);
  const name=(id:string)=>stations.find(row=>row.station_id===id)?.station_name??id;
  return <div className="train-station-search"><label htmlFor={id}>{label}</label><Combobox items={stations.map(row=>row.station_id)} value={value?.station_id??null} disabled={disabled} itemToStringLabel={name} onValueChange={id=>onChange(stations.find(row=>row.station_id===id)??null)}>
    <ComboboxChips ref={anchor}><ComboboxChipsInput id={id} placeholder={`${label} 이름 검색`} /></ComboboxChips>
    <ComboboxContent anchor={anchor}><ComboboxEmpty>일치하는 역이 없습니다.</ComboboxEmpty><ComboboxList>{(id:string)=><ComboboxItem key={id} value={id}>{name(id)} <small>{id}</small></ComboboxItem>}</ComboboxList></ComboboxContent>
  </Combobox></div>;
}
