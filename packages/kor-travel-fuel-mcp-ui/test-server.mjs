import { createServer } from "node:http";
import { readFileSync } from "node:fs";
const widget=readFileSync(new URL("../../backend/app/fuel_widget/index.html",import.meta.url),"utf8").replace('<script id="fuel-map-config" type="application/json">{}</script>','<script id="fuel-map-config" type="application/json">{"apiKey":"local-test-fixture"}</script>');
const host=readFileSync(new URL("./e2e/host.html",import.meta.url));
createServer((req,res)=>{res.setHeader("Cache-Control","no-store");if(req.url==="/widget"){res.setHeader("Content-Type","text/html;charset=utf-8");res.setHeader("Content-Security-Policy","default-src 'none'; script-src 'unsafe-inline' blob:; style-src 'unsafe-inline'; img-src data: blob: https://api.vworld.kr; connect-src https://api.vworld.kr blob:; worker-src blob:;");res.end(widget);}else if(req.url==="/"){res.setHeader("Content-Type","text/html;charset=utf-8");res.end(host);}else{res.statusCode=404;res.end();}}).listen(12861,"127.0.0.1");
