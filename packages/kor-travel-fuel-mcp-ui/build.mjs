import { build } from "esbuild";
import { mkdir, writeFile } from "node:fs/promises";
import { gzipSync } from "node:zlib";
// MapLibre6의 worker와 shared 모듈을 하나의 module worker로 묶어 blob 상대 import를 없앤다.
const workerBuild=await build({entryPoints:["node_modules/maplibre-gl/dist/maplibre-gl-worker.mjs"],bundle:true,minify:true,format:"esm",platform:"browser",target:"es2022",write:false});
const worker=workerBuild.outputFiles[0].text;
const result = await build({entryPoints:["src/main.ts"],define:{__FUEL_MAP_WORKER__:JSON.stringify(worker)},bundle:true,minify:true,format:"esm",target:"es2022",outdir:"dist",write:false,loader:{".png":"dataurl",".svg":"dataurl"},legalComments:"none"});
const js = result.outputFiles.find(file => file.path.endsWith(".js")).contents;
const css = result.outputFiles.find(file => file.path.endsWith(".css")).text.replace(/<\/style/gi, "<\\/style");
const payload = gzipSync(js, { level: 9 }).toString("base64");
// Keep the MCP resource self-contained. Recreate the existing inline module
// after decoding; no network fetch, eval, or extra CSP origin is needed.
const bootstrap = `
try {
  const payload = document.getElementById("fuel-widget-payload");
  const bytes = Uint8Array.from(atob(payload.textContent), x => x.charCodeAt(0));
  payload.remove();
  const decoded = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"));
  const script = document.createElement("script");
  script.type = "module";
  script.textContent = await new Response(decoded).text();
  document.body.append(script);
} catch {
  document.getElementById("app").textContent = "유가 지도를 시작하지 못했습니다.";
}`;
const html = `<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>내 주변 유가</title><style>${css}</style></head><body><main id="app" aria-label="내 주변 유가"><p role="status">유가 지도를 여는 중입니다.</p></main><script id="fuel-map-config" type="application/json">{}</script><script id="fuel-widget-payload" type="application/octet-stream">${payload}</script><script type="module">${bootstrap}</script></body></html>`;
const dir = "../../backend/app/fuel_widget";
await mkdir(dir,{recursive:true});await writeFile(`${dir}/index.html`,html);
console.log(`MCP Apps UI: ${Buffer.byteLength(html)} bytes`);
