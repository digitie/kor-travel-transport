import Supercluster from "supercluster";
import { expect, it } from "vitest";
import { clusterAtScale } from "./journey";
it("separates sparse fuel at real zoom 10 while default remains 11", () => {
  expect(clusterAtScale(9, 37, 3, 800, 540, 10)).toBe(true);
  expect(clusterAtScale(10, 37, 3, 800, 540, 10)).toBe(false);
  expect(clusterAtScale(10, 37, 3)).toBe(true);
  expect(clusterAtScale(11, 37, 3)).toBe(false);
});
it("retains the mobile and desktop density safety budget", () => {
  expect(clusterAtScale(10, 37, 100, 390, 700, 10)).toBe(true);
  expect(clusterAtScale(10, 37, 100, 1440, 900, 10)).toBe(true);
  expect(clusterAtScale(NaN, 37, 1, 390, 700, 10)).toBe(true);
});

it("radius zero separates nearby stations while retaining coincident leaves for the existing popup", () => {
  const index = new Supercluster({ radius: 0, maxZoom: 19 });
  index.load([[127,37],[127.001,37],[127,37]].map((coordinates, id) => ({ type: "Feature" as const, geometry: { type: "Point" as const, coordinates }, properties: { id } })));
  const groups = index.getClusters([124,32,132,39], 10);
  expect(groups).toHaveLength(2);
  const cluster = groups.find(row => row.properties.cluster)!;
  expect(index.getLeaves(cluster.properties.cluster_id, 10).map(row => row.properties.id).sort()).toEqual([0,2]);
  expect(index.getClusterExpansionZoom(cluster.properties.cluster_id)).toBeGreaterThan(19);
});
