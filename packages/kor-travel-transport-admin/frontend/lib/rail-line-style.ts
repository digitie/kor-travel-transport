import type { Place } from "./journey";

/** 운영기관과 노선을 함께 구분한다. 부산 1호선을 수도권 1호선 색으로 표시하지 않는다. */
export function railLineStyle(line: string, operator = "") {
  const number = /([1-9])호선/.exec(line)?.[1];
  const region = /부산/.test(operator) ? "busan" : /대구/.test(operator) ? "daegu"
    : /인천/.test(operator) ? "incheon" : /대전/.test(operator) ? "daejeon" : /광주/.test(operator) ? "gwangju" : "seoul";
  if (number) return { label: number, color: `var(--rail-${region}-${number}, var(--color-rail))` };
  const known = [
    ["GTX", "gtx", "GTX"], ["신분당", "shinbundang", "신분당"], ["수인", "bundang", "수인분당"],
    ["분당", "bundang", "분당"], ["경의", "gyeongui", "경의중앙"], ["경춘", "gyeongchun", "경춘"],
    ["경강", "gyeonggang", "경강"], ["공항", "arex", "공항"], ["서해", "seohae", "서해"],
    ["우이", "ui", "우이신설"], ["신림", "sillim", "신림"], ["동해", "donghae", "동해"],
    ["김해", "gimhae", "부산김해"], ["의정부", "uijeongbu", "의정부"], ["용인", "everline", "용인"],
    ["김포", "gimpo", "김포"], ["KTX", "korail", "KTX"], ["SRT", "srt", "SRT"],
  ].find(([name]) => line.includes(name));
  return known ? { label: known[2], color: `var(--rail-${known[1]})` }
    : { label: line.replace(/선$/, "") || "철도", color: /코레일/.test(operator) ? "var(--rail-korail)" : "var(--color-rail)" };
}

export function railLines(place: Pick<Place, "line_names" | "subtitle">) {
  return (place.line_names.length ? place.line_names : ["철도"]).map(line => ({ name: line, ...railLineStyle(line, place.subtitle ?? "") }));
}
