'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict');
const {parseFilters,blockedHost,DEFAULT_HOSTS,thirdParty,cleanURL}=require('../privacy');
const {folderBytes,checkStorage}=require('../storage');
const {BandwidthProxy}=require('../bandwidth');
const http=require('node:http'),net=require('node:net'),fs=require('node:fs/promises'),os=require('node:os'),path=require('node:path');
test('Domainfilter: HOSTS, Domain- und einfache Adblockregeln; komplexe Regeln bleiben aus',()=>{
 const r=parseFilters('\uFEFF# Kommentar\n0.0.0.0 ads.example\n||tracker.example^\nexample.org\n@@||allowed.example^\n||special.example^$third-party\nexample.com##.banner\n! Kommentar');
 assert.equal(r.hosts.size,3);assert.equal(r.skipped,3);assert(blockedHost('sub.ads.example',r.hosts));assert(!blockedHost('notads.example',r.hosts));assert(blockedHost('sub.doubleclick.net',new Set(DEFAULT_HOSTS)));
 assert.throws(()=>parseFilters('x'.repeat(12000001)),/12 MB/);
});
test('Cookies: echte registrierbare Domains, getrennte github.io-Seiten und Prime-Ausnahmen',()=>{
 assert(!thirdParty('https://login.example.co.uk','https://www.example.co.uk'));assert(thirdParty('https://attacker.co.uk','https://example.co.uk'));assert(thirdParty('https://a.github.io','https://b.github.io'));assert(!thirdParty('https://www.amazon.de','https://www.primevideo.com'));assert(thirdParty('https://amazon.de.evil.org','https://primevideo.com'));assert(!thirdParty('https://localhost:2','https://localhost:1'));
});
test('Tracking entfernt, erforderliche Query- und Fragmentwerte erhalten',()=>{assert.equal(cleanURL('https://example.org/watch?id=3&utm_source=a&gclid=b#play'),'https://example.org/watch?id=3#play');});
test('Speicherbereinigung bewahrt Nutzerdaten und zählt keine Downloads/Symlinks',async()=>{
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'vaultie-test-'));try{await fs.writeFile(path.join(root,'bookmarks.json'),'123');await fs.mkdir(path.join(root,'Downloads'));await fs.writeFile(path.join(root,'Downloads','file'),'large download');
 assert.equal(await folderBytes(root),3);let clears=0;const result=await checkStorage(root,[{clearCache:async()=>{clears++;}}],true);assert.equal(clears,1);assert.equal(result.bytes,3);assert.equal(await fs.readFile(path.join(root,'bookmarks.json'),'utf8'),'123');assert.equal(result.limit,5000000000);assert.equal(result.cleanAt,3800000000);
 }finally{await fs.rm(root,{recursive:true,force:true});}
});
const listen=server=>new Promise(r=>server.listen(0,'127.0.0.1',()=>r(server.address().port)));
const stop=server=>new Promise(r=>server.close(r));
test('HTTP-Proxy: gemeinsames Limit über mehrere Downloads plus Upload, keine Datenänderung',async()=>{
 const payload=Buffer.alloc(160000,113);let received=0;const server=http.createServer((req,res)=>{if(req.method==='POST'){req.on('data',b=>received+=b.length);req.on('end',()=>res.end('OK'));}else res.end(payload);});const port=await listen(server),proxy=new BandwidthProxy(3);await proxy.start();
 function request(method){return new Promise((resolve,reject)=>{const q=http.request({host:'127.0.0.1',port:proxy.port,path:'http://127.0.0.1:'+port+'/',method,agent:false,headers:{host:'127.0.0.1:'+port}},res=>{const chunks=[];res.on('data',c=>chunks.push(c));res.on('end',()=>resolve(Buffer.concat(chunks)));});q.on('error',reject);q.end(method==='POST'?payload:undefined);});}
 try{const before=performance.now();const [a,b,c]=await Promise.all([request('GET'),request('GET'),request('POST')]);const duration=(performance.now()-before)/1000;assert.deepEqual(a,payload);assert.deepEqual(b,payload);assert.equal(c.toString(),'OK');assert.equal(received,payload.length);assert(duration>=1.20,'Aggregiertes 3-Mbit/s-Limit verletzt: '+duration);assert(duration<6,'Übertragung hängt: '+duration);assert.equal(proxy.server.address().address,'127.0.0.1');proxy.configure(25);assert.equal(proxy.limiter.mbps,25);
 }finally{await proxy.stop();await stop(server);}
});
test('CONNECT-Tunnel überträgt bidirektional unveränderte Bytes',async()=>{
 const server=net.createServer(socket=>socket.pipe(socket));const port=await listen(server),proxy=new BandwidthProxy(25);await proxy.start();
 try{const result=await new Promise((resolve,reject)=>{const socket=net.connect(proxy.port,'127.0.0.1');let header=false,buffer=Buffer.alloc(0);socket.on('error',reject);socket.on('connect',()=>socket.write('CONNECT 127.0.0.1:'+port+' HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n'));socket.on('data',chunk=>{buffer=Buffer.concat([buffer,chunk]);if(!header){const i=buffer.indexOf('\r\n\r\n');if(i<0)return;assert.match(buffer.toString(),/^HTTP\/1.1 200/);buffer=buffer.subarray(i+4);header=true;socket.write(Buffer.from([0,1,2,255]));}if(buffer.length===4){socket.destroy();resolve(buffer);}});});assert.deepEqual(result,Buffer.from([0,1,2,255]));
 }finally{await proxy.stop();await stop(server);}
});
