'use strict';
const assert=require('node:assert/strict');
module.exports=async({win,profile,command,tabs,homeHTML})=>{
 const timer=setTimeout(()=>{console.error('Smoke timeout');require('electron').app.exit(1);},45000);
 try{
  if(process.env.VAULTIE_SCREENSHOT){await new Promise(r=>setTimeout(r,400));require('node:fs').writeFileSync(process.env.VAULTIE_SCREENSHOT,(await win.capturePage()).toPNG());}
  const event={sender:win.webContents},call=(name,arg)=>command(event,name,arg);
  await win.webContents.executeJavaScript('window.vaultie.command("state")').then(s=>assert.equal(s.settings.rememberSessions,false));
  assert.equal(profile.isPersistent(),false);
  assert.match(homeHTML(),/Verlauf ausschließlich lokal/);
  assert(!homeHTML().includes('Der Verlauf wird niemals gespeichert.'));
  await win.webContents.executeJavaScript('document.getElementById("bandwidth").click()');
  await new Promise(r=>setTimeout(r,200));
  assert.equal(await win.webContents.executeJavaScript('document.querySelector("#panelbody input[type=range]").min'),'3');
  await call('settings',{key:'bandwidthEnabled',value:true});
  assert.match(await profile.resolveProxy('https://example.org'),/PROXY 127\.0\.0\.1:/);
  await call('settings',{key:'bandwidthMbps',value:6});
  await call('settings',{key:'bandwidthEnabled',value:false});
  assert.equal(await profile.resolveProxy('https://example.org'),'DIRECT');
  const http=require('node:http');const server=http.createServer((_req,res)=>res.end('<title>Testseite</title><p>Vaultie Test</p>'));await new Promise(r=>server.listen(0,'127.0.0.1',r));
  try{await call('navigate','http://127.0.0.1:'+server.address().port+'/');const page=[...tabs.values()][0].view.webContents;if(page.isLoading())await new Promise(r=>page.once('did-stop-loading',r));assert.equal(await page.executeJavaScript('navigator.hardwareConcurrency'),4);assert.equal((await call('bookmark')).ok,true);const url=page.getURL();await call('pin-bookmark',url);assert(homeHTML().includes(url));assert((await call('state')).history.some(h=>h.url===url));}finally{server.close();}

  await call('new-tab','vaultie://home');
  const wc=[...tabs.values()].at(-1).view.webContents;
  if(wc.isLoading())await new Promise(r=>wc.once('did-stop-loading',r));
  assert.match(await wc.executeJavaScript('document.body.textContent'),/Vaultie/);
  assert.equal(await wc.executeJavaScript('typeof require'),'undefined');
  assert.equal(await wc.executeJavaScript('typeof window.vaultie'),'undefined');
  const cookieServer=require('node:http').createServer((req,res)=>{res.setHeader('Content-Type','text/html');res.end('<script>document.cookie="probe=secret; path=/";parent.postMessage({cookieProbe:document.cookie},"*")</script>');});await new Promise(r=>cookieServer.listen(0,'127.0.0.1',r));
  try{const parent=[...tabs.values()][0].view.webContents;const src='http://localhost:'+cookieServer.address().port+'/';const cookie=await parent.executeJavaScript(`new Promise((resolve,reject)=>{let timer=setTimeout(()=>reject(Error('Cookie frame timeout')),6000);const handler=e=>{if(e.data&&'cookieProbe' in e.data){clearTimeout(timer);window.removeEventListener('message',handler);resolve(e.data.cookieProbe);}};window.addEventListener('message',handler);const frame=document.createElement('iframe');frame.src=${JSON.stringify(src)};document.body.appendChild(frame);})`);assert.equal(cookie,'','Third-party JavaScript cookies blocked in iframe');}finally{cookieServer.close();}
  const before=tabs.size;await call('close-tab',[...tabs.keys()].at(-1));assert.equal(tabs.size,before-1);
  assert.equal((await command({sender:wc},'clear-history')).error,'Nicht autorisiert.');
  await call('clear-history');assert.equal((await call('state')).history.length,0);
 }finally{clearTimeout(timer);}
};
