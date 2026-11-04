'use strict';
const http=require('node:http'),net=require('node:net'),{Transform}=require('node:stream');
class SharedLimiter{
 constructor(mbps=10){this.configure(mbps);}
 configure(mbps){this.mbps=Math.max(3,Math.min(25,Math.round(Number(mbps)||10)));this.next=performance.now();}
 async pace(size){const now=performance.now();this.next=Math.max(now,this.next)+size*8000/(this.mbps*1e6);await new Promise(r=>setTimeout(r,Math.max(0,this.next-now)));}
 stream(){const limiter=this;return new Transform({highWaterMark:8192,transform(chunk,_encoding,done){(async()=>{for(let i=0;i<chunk.length;i+=8192){const p=chunk.subarray(i,i+8192);await limiter.pace(p.length);if(this.destroyed)return;this.push(p);}done();})().catch(done);}});}
}
class BandwidthProxy{
 constructor(mbps=10){this.limiter=new SharedLimiter(mbps);this.sockets=new Set();this.server=http.createServer((q,r)=>this.request(q,r));this.server.headersTimeout=20000;this.server.requestTimeout=0;this.server.on('connection',s=>this.track(s));this.server.on('clientError',(_e,s)=>s.destroy());this.server.on('connect',(q,c,h)=>this.connect(q,c,h));}
 track(s){this.sockets.add(s);s.on('error',()=>{});s.once('close',()=>this.sockets.delete(s));return s;}
 pipe(source,destination){const paced=this.limiter.stream();source.pipe(paced).pipe(destination);source.on('error',()=>{paced.destroy();destination.destroy();});destination.on('error',()=>{paced.destroy();source.destroy();});destination.once('close',()=>paced.destroy());}
 async start(){await new Promise((resolve,reject)=>{this.server.once('error',reject);this.server.listen(0,'127.0.0.1',resolve);});this.port=this.server.address().port;return this.port;}
 configure(mbps){this.limiter.configure(mbps);}
 request(req,res){let u;try{u=new URL(req.url);if(u.protocol!=='http:'||u.username||u.password)throw Error();}catch{res.writeHead(400);res.end();return;}
 const headers={...req.headers};delete headers['proxy-connection'];delete headers['proxy-authorization'];headers.connection='close';
 const up=http.request(u,{method:req.method,headers,agent:false},incoming=>{res.writeHead(incoming.statusCode,incoming.headers);this.pipe(incoming,res);});up.on('socket',s=>this.track(s));up.on('error',()=>{if(!res.headersSent)res.writeHead(502);res.end();});req.on('aborted',()=>up.destroy());this.pipe(req,up);}
 connect(req,client,head){let u;try{u=new URL('http://'+req.url);if(!u.hostname||u.username||u.password||u.pathname!=='/'||u.search||u.hash)throw Error();}catch{client.end('HTTP/1.1 400 Bad Request\r\n\r\n');return;}
 const upstream=this.track(net.connect({host:u.hostname.replace(/^\[|\]$/g,''),port:Number(u.port)||443}));const timer=setTimeout(()=>upstream.destroy(),15000);upstream.once('error',()=>{clearTimeout(timer);client.destroy();});client.once('close',()=>upstream.destroy());upstream.once('close',()=>client.destroy());
 upstream.once('connect',()=>{clearTimeout(timer);client.write('HTTP/1.1 200 Connection Established\r\n\r\n');const begin=async()=>{if(head.length){await this.limiter.pace(head.length);upstream.write(head);}this.pipe(client,upstream);this.pipe(upstream,client);};begin().catch(()=>client.destroy());});}
 async stop(){for(const s of this.sockets)s.destroy();await new Promise(r=>this.server.close(r));}
}
module.exports={SharedLimiter,BandwidthProxy};
