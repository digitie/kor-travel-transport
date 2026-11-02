// @vitest-environment jsdom
import {act,useState} from "react";
import {createRoot} from "react-dom/client";
import {afterEach,beforeEach,expect,test,vi} from "vitest";
import {RailStationPicker} from "./rail-station-picker";
import type {RailStation} from "@/lib/general-rail";

beforeEach(()=>{
  Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});
  vi.stubGlobal("ResizeObserver",class{observe(){}unobserve(){}disconnect(){}});
  vi.stubGlobal("matchMedia",()=>({matches:false,addEventListener(){},removeEventListener(){}}));
});
afterEach(()=>vi.unstubAllGlobals());

test("실제 단일 Combobox에서 역·지역을 골라 코드 대신 이름을 표시한다",async()=>{
  const rows=[{station_id:"NAT010000",station_name:"서울",city_name:"서울"},{station_id:"NAT014445",station_name:"부산",city_name:"부산"}];
  const selected=vi.fn();
  function Demo(){const[value,setValue]=useState<RailStation|null>(null);return <RailStationPicker id="station" label="출발역" stations={rows} value={value} onChange={row=>{selected(row);setValue(row);}}/>;}
  const container=document.createElement("div");document.body.append(container);const root=createRoot(container);
  try{
    await act(async()=>root.render(<Demo/>));
    const input=container.querySelector("input")!;
    await act(async()=>{input.focus();input.dispatchEvent(new KeyboardEvent("keydown",{key:"ArrowDown",bubbles:true}));});
    const option=[...document.querySelectorAll<HTMLElement>('[role="option"]')].find(row=>row.textContent?.includes("부산"));
    expect(option?.textContent).toContain("부산 · 부산");
    await act(async()=>option!.click());
    expect(selected).toHaveBeenLastCalledWith(rows[1]);expect(input.value).toBe("부산 · 부산");
  }finally{await act(async()=>root.unmount());container.remove();}
});
