import {expect,test} from "vitest";
import {railLineStyle,railLines} from "./rail-line-style";

test("같은 1호선도 운영기관을 구분하며 GTX·신분당 이름을 보존한다",()=>{
  expect(railLineStyle("1호선","서울교통공사")).toEqual({label:"1",color:"var(--rail-seoul-1, var(--color-rail))"});
  expect(railLineStyle("1호선","부산교통공사").color).toContain("busan-1");
  expect(railLineStyle("GTX-A").label).toBe("GTX");
  expect(railLineStyle("신분당선").color).toBe("var(--rail-shinbundang)");
  expect(railLines({line_names:["2호선","신분당선"],subtitle:"서울"}).map(row=>row.label)).toEqual(["2","신분당"]);
});
