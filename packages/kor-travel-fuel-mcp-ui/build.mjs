import { build } from "esbuild";
import { mkdir, writeFile } from "node:fs/promises";
const result = await build({entryPoints:["src/main.ts"],bundle:true,minify:true,format:"esm",target:"es2022",outdir:"dist",write:false,loader:{".png":"dataurl",".svg":"dataurl"},legalComments:"none"});
const js = result.outputFiles.find(file=>file.path.endsWith(".js")).text.replace(/<\/script/gi,"<\\/script");
const css = result.outputFiles.find(file=>file.path.endsWith(".css")).text.replace(/<\/style/gi,"<\\/style");
const html = `<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>내 주변 유가</title><style>${css}</style></head><body><main id="app" aria-label="내 주변 유가"></main><script type="module">${js}</script></body></html>`;
const dir = "../../backend/app/fuel_widget";
await mkdir(dir,{recursive:true});await writeFile(`${dir}/index.html`,html);
console.log(`MCP Apps UI: ${Buffer.byteLength(html)} bytes`);
