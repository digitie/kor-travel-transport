"use client";
import { useEffect, useRef, useState } from "react";
import { Combobox, ComboboxChips, ComboboxChipsInput, ComboboxContent, ComboboxEmpty, ComboboxItem, ComboboxList } from "./ui/combobox";
import type { RailStation } from "@/lib/general-rail";

export function RailStationPicker({id,label,stations,value,onChange,disabled=false,searchRequest}:{id:string;label:string;stations:RailStation[];value:RailStation|null;onChange:(station:RailStation|null)=>void;disabled?:boolean;searchRequest?:{revision:number;text:string}}) {
  const anchor=useRef<HTMLDivElement|null>(null);
  const requestRevision=searchRequest?.revision??0;
  const [search,setSearch]=useState({revision:0,text:""});
  const input=search.revision===requestRevision?search.text:searchRequest?.text??"";
  useEffect(()=>{if(requestRevision&&!disabled)document.getElementById(id)?.focus();},[requestRevision,disabled,id]);
  const labels=new Map(stations.map(row=>[row.station_id,[row.station_name,row.city_name].filter(Boolean).join(" · ")]));
  const name=(id:string)=>labels.get(id)??id;
  return <div className="train-station-search"><label htmlFor={id}>{label}</label><Combobox inputValue={input} onInputValueChange={text=>setSearch({revision:requestRevision,text})} items={stations.map(row=>row.station_id)} value={value?.station_id??null} disabled={disabled} itemToStringLabel={name} onValueChange={id=>onChange(stations.find(row=>row.station_id===id)??null)}>
    <ComboboxChips ref={anchor}><ComboboxChipsInput id={id} placeholder={`${label} 이름 검색`} /></ComboboxChips>
    <ComboboxContent anchor={anchor}><ComboboxEmpty>일치하는 역이 없습니다.</ComboboxEmpty><ComboboxList>{(id:string)=><ComboboxItem key={id} value={id}>{name(id)}</ComboboxItem>}</ComboboxList></ComboboxContent>
  </Combobox></div>;
}
