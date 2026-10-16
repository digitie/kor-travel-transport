// loopback 전용 실제 HTTP fixture. provider·DB·앱을 import하지 않는다.
import http from 'node:http';
import readline from 'node:readline';
const mode=process.argv[2],calls=[],sockets=new Set(),timers=new Set();
const later=(fn,ms)=>{const t=setTimeout(()=>{timers.delete(t);fn();},ms);timers.add(t);};
const server=http.createServer((req,res)=>{
  calls.push({method:req.method,path:req.url,connection:req.headers.connection});
  req.on('error',()=>{});res.on('error',()=>{});
  if(mode==='redirect'){res.writeHead(302,{Location:'/redirect-target'});res.end();return;}
  if(mode==='unavailable'){res.writeHead(503);res.end('no');return;}
  if(mode==='no_content'){res.writeHead(204);res.end();return;}
  if(mode==='upper_2xx'){res.writeHead(299);res.end('ok');return;}
  if(mode==='oversized_length'){res.writeHead(200,{'Content-Length':1048577});res.end();return;}
  if(mode==='oversized_chunked'){res.writeHead(200);res.end(Buffer.alloc(1048577));return;}
  if(mode==='max_body'){res.writeHead(200,{'Content-Length':1048576});res.end(Buffer.alloc(1048576));return;}
  if(mode==='aborted'){res.writeHead(200,{'Content-Length':100});res.write('partial');later(()=>res.socket?.destroy(),20);return;}
  if(mode==='headers_stall'){res.writeHead(200);res.flushHeaders();return;}
  if(mode==='slow_drip'){
    res.writeHead(200);res.flushHeaders();
    const t=setInterval(()=>res.write('x'),200);timers.add(t);
    later(()=>{clearInterval(t);timers.delete(t);res.end();},8000);return;
  }
  res.writeHead(200,{'Content-Type':'text/html'});res.write('<html>');later(()=>res.end('ok</html>'),40);
});
server.on('connection',s=>{sockets.add(s);s.on('close',()=>sockets.delete(s));});
server.on('clientError',(_e,s)=>s.destroy());
let finished=false;
function stop(){
  if(finished)return;finished=true;
  for(const t of timers)clearTimeout(t);
  for(const s of sockets)s.destroy();
  const done=()=>process.stdout.write(JSON.stringify({calls})+'\n',()=>process.exit(0));
  if(server.listening)server.close(done);else done();
}
readline.createInterface({input:process.stdin}).on('line',line=>{if(line==='stop')stop();});
server.listen(0,'127.0.0.1',()=>{
  const port=server.address().port;
  if(mode==='closed')server.close(()=>console.log(JSON.stringify({port})));
  else console.log(JSON.stringify({port}));
});
