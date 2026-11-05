'use strict';
const {app,BrowserWindow,WebContentsView,ipcMain,session,dialog,shell,safeStorage,components} = require('electron');
const fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const HOME='vaultie://home';
const {protocol}=require('electron');protocol.registerSchemesAsPrivileged([{scheme:'vaultie',privileges:{standard:true,secure:true,supportFetchAPI:true}}]);
app.commandLine.appendSwitch('disable-quic');
if(process.env.VAULTIE_TEST_USER_DATA)app.setPath('userData',process.env.VAULTIE_TEST_USER_DATA);
let win=null,tabs=new Map(),active=null,seq=0,ready=false,widevine='Nicht geprüft',downloads=[],bookmarks=[],passwords=[],settings={adblock:true,stripTracking:true,rememberSessions:false},blocked=0,closing=false;
let dir,profile,panelOpen=false,htmlFullscreen=false,panelName=null;
const {BandwidthProxy}=require('./bandwidth');
const privacy=require('./privacy'),{checkStorage}=require('./storage');
const crypto=require('node:crypto');
const viewsByContents=new Map();const profiles=new Set();let proxy,history=[],pinned=[],hidden=[],domains=new Set(privacy.DEFAULT_HOSTS),blockReport={},stripped=0,storage={},storageBusy=false;
const seed=crypto.randomBytes(16).toString('hex');
settings={...settings,fingerprinting:true,thirdPartyCookies:true,clearHistoryOnExit:false,bandwidthEnabled:false,bandwidthMbps:10};
const controls=['move-tab','data-folder','import-filters','protection-report','edit-bookmark','pin-bookmark','home-shortcut','clear-history','remove-history','storage','update-check','read-form','list-passwords','remove-password','import-passwords','download-action','download-directory'];

function encryptionAvailable(){return safeStorage.isEncryptionAvailable()&&!(process.platform==='linux'&&safeStorage.getSelectedStorageBackend?.()==='basic_text');}
const read=(p,d)=>{try{return JSON.parse(fs.readFileSync(p,'utf8'));}catch{return d;}};
function save(p,x){const tmp=p+'.tmp';fs.writeFileSync(tmp,JSON.stringify(x,null,2),'utf8');fs.renameSync(tmp,p);}
function file(n){return path.join(dir,n);}
function urlOK(s){try{const u=new URL(s);return /^(https?:)$/.test(u.protocol)&&!u.username&&!u.password?u.href:null;}catch{return null;}}
function clean(s){return settings.stripTracking?privacy.cleanURL(s):s;}
function location(input){const s=String(input||'').trim();if(s===HOME)return HOME;if(urlOK(s))return clean(s);if(/^(?:localhost|(?:[\w-]+\.)+[a-z]{2,})(?::\d+)?(?:[/?#]|$)/i.test(s))return clean('https://'+s);return 'https://www.startpage.com/sp/search?query='+encodeURIComponent(s);}
function selected(){return tabs.get(active);}
function state(full=true){const result={tabs:[...tabs.values()].map(t=>({id:t.id,title:t.title,url:t.url,active:t.id===active,loading:t.loading})),active,bookmarks,downloads:downloads.slice(-70),settings,blocked,history,pinned,hidden,storage,filterCount:domains.size,stripped,blockReport,widevine,encryption:encryptionAvailable()};if(!full){if(panelName!=='history')delete result.history;if(panelName!=='report')delete result.blockReport;}return result;}
function notify(){if(win&&!win.isDestroyed()&&ready)scheduleNotify();}
function layout(){if(!win||win.isDestroyed())return;const t=selected();if(!t?.view)return;const [w,h]=win.getContentSize();const y=htmlFullscreen?0:(panelOpen?520:113);t.view.setBounds({x:0,y,width:Math.max(1,w),height:Math.max(1,h-y-(htmlFullscreen?0:24))});}
function snapshot(t){if(!t?.view||t.view.webContents.isDestroyed())return;const loaded=t.view.webContents.getURL();t.url=loaded==='vaultie://home/'||loaded==='vaultie://home'?HOME:(loaded||t.url);t.title=t.view.webContents.getTitle()||t.title;t.loading=t.view.webContents.isLoading();notify();}
function setActive(id){const t=tabs.get(id);if(!t)return;if(active===id&&t.view)return;if(active!==null&&tabs.get(active)?.view){const old=tabs.get(active).view;old.setVisible(false);win.contentView.removeChildView(old);}active=id;materialize(t);win.contentView.addChildView(t.view);t.view.setVisible(true);layout();t.view.webContents.focus();notify();}
function newTab(address=HOME,switchTo=true){
 const id=++seq;const url=address===HOME?HOME:location(address);
 const t={id,title:url===HOME?'Neuer Tab – Vaultie':new URL(url).hostname,url,view:null,loading:false,pendingAddress:url};tabs.set(id,t);
 if(switchTo)setActive(id);notify();return id;
}
function materialize(t){
 if(t.view)return;
 const view=new WebContentsView({webPreferences:{session:profile,contextIsolation:true,nodeIntegration:false,sandbox:true,backgroundThrottling:true,webRTCIPHandlingPolicy:'disable_non_proxied_udp'}});
 view.setBackgroundColor('#021b22');t.view=view;view.setVisible(false);
  const wc=view.webContents;viewsByContents.set(wc.id,t);
  wc.on('did-finish-load',()=>recordHistory(t));
  wc.on('before-input-event',(event,input)=>shortcut(event,input));
  wc.on('will-attach-webview',event=>event.preventDefault());
  wc.on('enter-html-full-screen',()=>{panelOpen=false;htmlFullscreen=true;win.setFullScreen(true);layout();});
  wc.on('leave-html-full-screen',()=>{htmlFullscreen=false;win.setFullScreen(false);layout();});

  for(const evt of ['did-start-loading','did-stop-loading','did-navigate','did-navigate-in-page','page-title-updated'])wc.on(evt,()=>snapshot(t));
  wc.on('did-fail-load',(_e,code,description,_url,main)=>{if(main&&code!==-3){t.title='Seitenfehler: '+description;notify();}});
  wc.on('will-navigate',(e,url)=>{if(url.startsWith('vaultie://')){e.preventDefault();const command=new URL(url).hostname;if(t.url===HOME){if(command==='unpin'){const target=new URL(url).searchParams.get('url');hidden.push(target);pinned=pinned.filter(x=>x!==target);saveHome();}else if(['bookmarks','history'].includes(command))notifyAndOpen(command);} return;}if(!urlOK(url))e.preventDefault();});
  wc.setWindowOpenHandler(({url})=>{if(urlOK(url))newTab(clean(url),true);return {action:'deny'};});
  visit(t,t.pendingAddress);
  delete t.pendingAddress;
}
function notifyAndOpen(name){if(win&&!win.isDestroyed())win.webContents.send('vaultie:open',name);}
function visit(t,address){
 if(!t.view){t.pendingAddress=address;t.url=address;return;}
 if(address===HOME){t.url=HOME;t.title='Neuer Tab – Vaultie';t.view.webContents.loadURL('vaultie://home/').catch(e=>{t.title=e.message;notify();});}
 else {const dest=location(address);t.view.webContents.loadURL(dest).catch(e=>{t.title=e.message;notify();});}
 notify();
}
function closeTab(id){const t=tabs.get(id);if(!t)return;if(active===id)win.contentView.removeChildView(t.view);tabs.delete(id);if(t.view)viewsByContents.delete(t.view.webContents.id);t.view?.webContents.close();if(!tabs.size)newTab();else if(active===id)setActive([...tabs.keys()][tabs.size-1]);notify();}
function persistTabs(){const items=[...tabs.values()].map(t=>({url:t.url,active:t.id===active})).filter(t=>t.url===HOME||urlOK(t.url));save(file('tabs.json'),items.slice(-25));}
function addBookmark(){const t=selected();if(!t||!urlOK(t.url))return {error:'Nur Webseiten als Lesezeichen.'};if(!bookmarks.some(x=>x.url===t.url)){bookmarks.push({title:t.title||t.url,url:t.url});save(file('bookmarks.json'),bookmarks);}notify();return {ok:true};}
function initFiles(){
 dir=path.join(app.getPath('userData'),'castlabs-profile');fs.mkdirSync(dir,{recursive:true});
 const old=path.join(process.env.LOCALAPPDATA||path.join(os.homedir(),'AppData','Local'),'Vaultie','bookmarks.json');
 if(!fs.existsSync(file('bookmarks.json'))&&fs.existsSync(old)){const items=read(old,[]);if(Array.isArray(items))save(file('bookmarks.json'),items.filter(v=>v&&urlOK(v.url)));}
 const oldDir=path.dirname(old);
 for(const name of ['history.json','pinned.json','hidden_shortcuts.json','filterliste.txt'])if(!fs.existsSync(file(name))&&fs.existsSync(path.join(oldDir,name)))fs.copyFileSync(path.join(oldDir,name),file(name));
 history=read(file('history.json'),[]);if(!Array.isArray(history))history=[];
 pinned=read(file('pinned.json'),[]);if(!Array.isArray(pinned))pinned=[];
 hidden=read(file('hidden_shortcuts.json'),[]);if(!Array.isArray(hidden))hidden=[];
 if(fs.existsSync(file('filterliste.txt'))){try{domains=new Set([...privacy.DEFAULT_HOSTS,...privacy.parseFilters(fs.readFileSync(file('filterliste.txt'),'utf8')).hosts]);}catch{}}
 bookmarks=read(file('bookmarks.json'),[]);if(!Array.isArray(bookmarks))bookmarks=[];
 passwords=fs.existsSync(file('passwords.json'))?JSON.parse(fs.readFileSync(file('passwords.json'),'utf8')):[];if(!Array.isArray(passwords))throw Error('Der Passwortspeicher ist beschädigt. Die Datei wurde nicht verändert.');
 if(!fs.existsSync(file('settings.json'))){const oldSettings=read(path.join(oldDir,'settings.json'),{});const mapping={adblock:'adblock',stripTracking:'strip_tracking_params',rememberSessions:'remember_website_sessions',thirdPartyCookies:'block_third_party_cookies',clearHistoryOnExit:'clear_history_on_exit',bandwidthEnabled:'bandwidth_enabled',bandwidthMbps:'bandwidth_mbps'};for(const [key,oldKey] of Object.entries(mapping))if(typeof oldSettings[oldKey]===typeof settings[key])settings[key]=oldSettings[oldKey];}
 settings={...settings,...read(file('settings.json'),{})};settings.bandwidthMbps=Math.max(3,Math.min(25,Number(settings.bandwidthMbps)||10));
}
async function setupSession(){
 profile=session.fromPartition(settings.rememberSessions?'persist:vaultie-castlabs':'vaultie-private-'+seed);
 profiles.add(profile);
 profile.registerPreloadScript({type:'frame',filePath:path.join(__dirname,'page-preload.js')});
 profile.protocol.handle('vaultie',request=>{
  if(request.url==='vaultie://home/'||request.url==='vaultie://home')return new Response(homeHTML(),{headers:{'content-type':'text/html; charset=utf-8','Content-Security-Policy':"default-src 'none'; img-src data:; style-src 'unsafe-inline'; form-action https://www.startpage.com; base-uri 'none'"}});
  return new Response('Nicht gefunden',{status:404});
 });
 profile.webRequest.onBeforeRequest((details,callback)=>{
  const first=firstParty(details);
  const h=privacy.host(details.url);
  if(settings.adblock&&details.resourceType!=='mainFrame'&&privacy.thirdParty(details.url,first)&&privacy.blockedHost(h,domains)){
   blocked++;blockReport[h]=(blockReport[h]||0)+1;scheduleNotify();return callback({cancel:true});
  }
  const dest=details.resourceType==='mainFrame'&&details.method==='GET'?clean(details.url):details.url;
  if(dest!==details.url){stripped++;scheduleNotify();return callback({redirectURL:dest});}
  callback({});
 });
 profile.webRequest.onBeforeSendHeaders((details,callback)=>{
  const headers={...details.requestHeaders};
  if(settings.thirdPartyCookies&&details.resourceType!=='mainFrame'&&privacy.thirdParty(details.url,firstParty(details)))for(const key of Object.keys(headers))if(key.toLowerCase()==='cookie')delete headers[key];
  callback({requestHeaders:headers});
 });
 profile.webRequest.onHeadersReceived((details,callback)=>{
  const headers={...details.responseHeaders};
  if(settings.thirdPartyCookies&&details.resourceType!=='mainFrame'&&privacy.thirdParty(details.url,firstParty(details)))for(const key of Object.keys(headers))if(key.toLowerCase()==='set-cookie')delete headers[key];
  callback({responseHeaders:headers});
 });
 profile.setPermissionRequestHandler((wc,permission,callback)=>{
  if(['media','notifications','fullscreen','display-capture'].includes(permission)){
   const origin=wc?.getURL();if(!origin?.startsWith('https:'))return callback(false);
   dialog.showMessageBox(win,{type:'question',buttons:['Ablehnen','Erlauben'],defaultId:0,cancelId:0,message:'Berechtigung: '+permission,detail:new URL(origin).origin}).then(r=>callback(r.response===1)).catch(()=>callback(false));
  }else callback(false);
 });
 profile.on('will-download',(_event,item)=>{
  const base=path.basename(item.getFilename()).replace(/[<>:"/\\|?*\x00-\x1f]/g,'_')||'Download';
  const folder=settings.downloadDirectory||app.getPath('downloads');fs.mkdirSync(folder,{recursive:true});
  let dest=path.join(folder,base),i=1;
  while(fs.existsSync(dest)||downloads.some(d=>d.path===dest)){const e=path.extname(base);dest=path.join(folder,path.basename(base,e)+' ('+i+++')'+e);}
  const row={id:downloads.length+1,name:path.basename(dest),progress:0,status:'Lädt',path:dest};
  downloads.push(row);downloadItems.set(row.id,item);item.setSavePath(dest);notify();
  item.on('updated',()=>{const total=item.getTotalBytes();row.progress=total?Math.round(item.getReceivedBytes()*100/total):0;row.received=item.getReceivedBytes();row.total=total;row.status=item.isPaused()?'Pausiert':'Lädt';scheduleNotify();});
  item.once('done',(_e,state)=>{row.status=state==='completed'?'Fertig':state==='cancelled'?'Abgebrochen':'Unterbrochen';downloadItems.delete(row.id);notify();});
 });
 await applyBandwidth();
}
const downloadItems=new Map();let notifyTimer;
function scheduleNotify(){if(!notifyTimer)notifyTimer=setTimeout(()=>{notifyTimer=null;flushNotify();},100);}
function flushNotify(){if(notifyTimer){clearTimeout(notifyTimer);notifyTimer=null;}if(win&&!win.isDestroyed()&&ready)win.webContents.send('vaultie:state',state(false));}
function firstParty(details){const frame=details.frame;try{if(frame?.top?.url&&privacy.host(frame.top.url))return frame.top.url;}catch{}
 const tab=viewsByContents.get(details.webContentsId);return tab?.url||details.initiatorOrigin||'';
}
async function applyBandwidth(){
 if(settings.bandwidthEnabled){if(!proxy){proxy=new BandwidthProxy(settings.bandwidthMbps);await proxy.start();}proxy.configure(settings.bandwidthMbps);}
 await profile.setProxy(settings.bandwidthEnabled?{mode:'fixed_servers',proxyRules:'http://127.0.0.1:'+proxy.port,proxyBypassRules:'<-loopback>'}:{mode:'direct'});
 await profile.closeAllConnections();
 if(!settings.bandwidthEnabled&&proxy){await proxy.stop();proxy=null;}
}
function recordHistory(t){if(!urlOK(t.url))return;const entry={url:t.url,title:t.title,visited:new Date().toISOString()};if(history.at(-1)?.url===entry.url)history[history.length-1]=entry;else history.push(entry);history=history.slice(-2000);save(file('history.json'),history);notify();}
function escapeHTML(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
const defaults=[['YouTube','https://www.youtube.com/','▶','yt'],['Discord','https://discord.com/app','◉','discord'],['WhatsApp','https://web.whatsapp.com/','◉','wa'],['Gmail','https://mail.google.com/','M','gmail'],['Drive','https://drive.google.com/','▲','drive']];
let homeTemplate;function homeHTML(){const html=homeTemplate??=fs.readFileSync(path.join(__dirname,'startseite.html'),'utf8');
 const entries=[...defaults.filter(x=>!hidden.includes(x[1])),...pinned.filter(u=>urlOK(u)&&!hidden.includes(u)&&!defaults.some(d=>d[1]===u)).map(u=>[bookmarks.find(b=>b.url===u)?.title||new URL(u).hostname,u,'★','add'])];
 const cards=entries.map(([title,url,icon,style])=>'<div style="position:relative"><a class="tile" href="'+escapeHTML(url)+'"><span class="appicon '+style+'">'+icon+'</span><strong>'+escapeHTML(title)+'</strong></a><a aria-label="Von Startseite entfernen" style="position:absolute;right:8px;top:4px;color:#b9faf4" href="vaultie://unpin?url='+encodeURIComponent(url)+'">×</a></div>').join('');
 return html.replace(/<div class="shortcutgrid">[\s\S]*?<\/div>\s*<div class="panel">/,'<div class="shortcutgrid">'+cards+'<a class="tile" href="vaultie://bookmarks"><span class="appicon add">＋</span><strong>Lesezeichen</strong></a></div><div class="panel">').replace('Der Verlauf wird niemals gespeichert.','Verlauf ausschließlich lokal gespeichert.');
}
function saveHome(){save(file('pinned.json'),pinned);save(file('hidden_shortcuts.json'),hidden);for(const t of tabs.values())if(t.url===HOME&&t.view)t.view.webContents.reload();notify();}
async function storageCheck(force=false){if(storageBusy)return storage;storageBusy=true;try{storage=await checkStorage(app.getPath('userData'),[...profiles],force);notify();return storage;}finally{storageBusy=false;}}
function shortcut(event,input){if(input.type!=='keyDown')return;const key=input.key.toLowerCase(),ctrl=input.control||input.meta;let action;
 if(ctrl){if(key==='t')action=()=>newTab();if(key==='w')action=()=>closeTab(active);if(key==='l')action=()=>{win.webContents.focus();win.webContents.send('vaultie:open','address');};if(key==='d')action=addBookmark;if(key==='r')action=()=>selected()?.view.webContents.reload();if(key==='h')action=()=>notifyAndOpen('history');if(key==='j')action=()=>notifyAndOpen('downloads');if(key==='tab')action=()=>{const ids=[...tabs.keys()];setActive(ids[(ids.indexOf(active)+(input.shift?-1:1)+ids.length)%ids.length]);};}
 if(input.alt&&key==='arrowleft')action=()=>selected()?.view.webContents.navigationHistory.goBack();if(input.alt&&key==='arrowright')action=()=>selected()?.view.webContents.navigationHistory.goForward();
 if(key==='f11')action=()=>win.setFullScreen(!win.isFullScreen());if(action){event.preventDefault();action();}
}
async function checkDrm(){
 const t=selected();if(!t)return {error:'Kein Tab geöffnet.'};
 if(!urlOK(t.view.webContents.getURL())||!t.view.webContents.getURL().startsWith('https:'))return {error:'Für die Prüfung eine HTTPS-Webseite öffnen.'};
 let timer;try{return await Promise.race([
  t.view.webContents.executeJavaScript('(async()=>{const v=document.createElement("video");const can=s=>v.canPlayType(s)||"nein";const o={h264:can(\'video/mp4; codecs="avc1.42E01E"\'),aac:can(\'audio/mp4; codecs="mp4a.40.2"\')};try{const a=await navigator.requestMediaKeySystemAccess("com.widevine.alpha",[{initDataTypes:["cenc"],videoCapabilities:[{contentType:\'video/mp4; codecs="avc1.42E01E"\'}]}]);o.widevine=a.keySystem;}catch(e){o.widevine=e.name+": "+e.message;}return o;})()',true),
  new Promise(resolve=>{timer=setTimeout(()=>resolve({error:'Zeitlimit bei der DRM-Prüfung (15 Sekunden).'}),15000);})
 ]);}catch(e){return {error:String(e.message||e)};}finally{clearTimeout(timer);}
}
function credentials(cmd,arg){
 if(!encryptionAvailable())return {error:'Windows-Verschlüsselung ist nicht verfügbar. Keine Passwörter werden unverschlüsselt gespeichert.'};
 const t=selected();if(!t||!urlOK(t.url))return {error:'Öffne eine HTTPS-Webseite.'};const origin=new URL(t.url).origin;
 if(!origin.startsWith('https:'))return {error:'Passwörter werden nur für HTTPS gespeichert.'};
 if(cmd==='save-password'){
  if(arg?.origin&&arg.origin!==origin)return {error:'Die aktive Webseite hat sich geändert. Formular erneut übernehmen.'};
  const username=String(arg?.username||'').trim(),password=String(arg?.password||'');
  if(!username||!password)return {error:'Benutzername und Passwort erforderlich.'};
  const value=safeStorage.encryptString(password).toString('base64');
  passwords=passwords.filter(x=>!(x.origin===origin&&x.username===username));
  passwords.push({origin,username,secret:value});save(file('passwords.json'),passwords);
  return {ok:true};
 }
 if(cmd==='get-password'){const entry=passwords.find(x=>x.origin===origin);if(!entry)return {error:'Keine Zugangsdaten für diese Webseite gespeichert.'};
  try{return {origin,username:entry.username,password:safeStorage.decryptString(Buffer.from(entry.secret,'base64'))};}catch{return {error:'Passwort konnte nicht entschlüsselt werden.'};}}
}
async function command(event,cmd,arg){
 if(!win||event.sender!==win.webContents)return {error:'Nicht autorisiert.'};
 const t=selected(),wc=t?.view?.webContents;
 switch(cmd){
 case 'state':return state();
 case 'panel':panelName=typeof arg==='string'?arg:null;panelOpen=Boolean(arg);layout();return {ok:true};
 case 'new-tab':return newTab(typeof arg==='string'?arg:HOME);
 case 'switch-tab':setActive(Number(arg));break;
 case 'close-tab':closeTab(Number(arg));break;
 case 'navigate':if(t)visit(t,location(arg));break;
 case 'back':if(wc?.navigationHistory.canGoBack())wc.navigationHistory.goBack();break;
 case 'forward':if(wc?.navigationHistory.canGoForward())wc.navigationHistory.goForward();break;
 case 'reload':wc?.reload();break;
 case 'home':if(t)visit(t,HOME);break;
 case 'bookmark':return addBookmark();
 case 'remove-bookmark':bookmarks=bookmarks.filter(v=>v.url!==arg);pinned=pinned.filter(u=>u!==arg);saveHome();save(file('bookmarks.json'),bookmarks);break;
 case 'open-bookmark':if(t&&urlOK(arg))visit(t,arg);break;
 case 'settings':{
 const bool=['adblock','stripTracking','rememberSessions','fingerprinting','thirdPartyCookies','clearHistoryOnExit','bandwidthEnabled'];
 if(bool.includes(arg?.key))settings[arg.key]=Boolean(arg.value);
 else if(arg?.key==='bandwidthMbps'){const n=Number(arg.value);if(!Number.isFinite(n))return {error:'Ungültiger Mbit/s-Wert.'};settings.bandwidthMbps=Math.max(3,Math.min(25,Math.round(n)));}
 else return {error:'Unbekannte Einstellung.'};
 if(['bandwidthEnabled','bandwidthMbps'].includes(arg.key))await applyBandwidth();
 save(file('settings.json'),settings);notify();return {ok:true,restart:arg.key==='rememberSessions',reload:arg.key==='fingerprinting'};
 }
 case 'download-folder':await shell.openPath(settings.downloadDirectory||app.getPath('downloads'));break;
 case 'drm':return await checkDrm();
 case 'save-password':case 'get-password':return credentials(cmd,arg);
 case 'fill-password':{
  const v=credentials('get-password');if(v.error)return v;
  // Password is only injected into fields on the matching HTTPS origin; never sent to the page as a message.
  return wc.executeJavaScript('(function(u,p){if(location.origin!=='+JSON.stringify(v.origin)+')return false;const a=document.querySelector("input[autocomplete=username], input[type=email], input[name*=user]");const b=document.querySelector("input[type=password]");if(!b)return false;for(const [el,value] of [[a,u],[b,p]]){if(el){const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,"value").set;setter.call(el,value);el.dispatchEvent(new Event("input",{bubbles:true}));}}return true;})('+JSON.stringify(v.username)+','+JSON.stringify(v.password)+')',true);
 }
 case 'clear-data':await profile.clearStorageData({storages:['cookies','localstorage','indexdb','serviceworkers']});await profile.clearCache();break;
 default:if(controls.includes(cmd))return await extraCommand(cmd,arg);return {error:'Unbekannte Aktion.'};
 }
 notify();return {ok:true};
}
ipcMain.handle('vaultie:command',async(...args)=>{try{const result=await command(...args);if(!['state','get-password','list-passwords','read-form','drm','update-check','protection-report'].includes(args[1]))flushNotify();return result;}catch(e){return {error:String(e.message||e)};}});
 ipcMain.on('vaultie:page-policy',(event)=>{const tab=viewsByContents.get(event.sender.id);let cookieBlocked=false;try{cookieBlocked=settings.thirdPartyCookies&&event.senderFrame!==event.senderFrame.top&&privacy.thirdParty(event.senderFrame.url,event.senderFrame.top.url);}catch{}event.returnValue=tab?{fingerprinting:settings.fingerprinting,seed,cookieBlocked}:{};});

app.whenReady().then(async()=>{
 initFiles();await setupSession();
 let componentTimer;const componentReady=components.whenReady().then(()=>{widevine=JSON.stringify(components.status());notify();}).catch(e=>{widevine='CDM: '+String(e.message||e);notify();});await Promise.race([componentReady,new Promise(resolve=>{componentTimer=setTimeout(()=>{widevine='CDM wird im Hintergrund initialisiert';resolve();},8000);})]);clearTimeout(componentTimer);
 win=new BrowserWindow({width:1280,height:820,minWidth:780,minHeight:520,backgroundColor:'#041d24',title:'Vaultie – Streaming-Entwicklungsfassung',webPreferences:{preload:path.join(__dirname,'preload.js'),contextIsolation:true,nodeIntegration:false,sandbox:true}});
 win.on('resize',layout);win.on('enter-full-screen',layout);win.on('leave-full-screen',layout);win.webContents.on('before-input-event',shortcut);win.webContents.on('will-navigate',event=>event.preventDefault());win.webContents.setWindowOpenHandler(()=>({action:'deny'}));
 win.on('close',event=>{if(closing)return;event.preventDefault();closing=true;persistTabs();if(settings.clearHistoryOnExit){history=[];save(file('history.json'),history);}
 Promise.all([...profiles].filter(p=>!settings.rememberSessions||p!==profile).map(p=>p.clearStorageData())).finally(()=>win?.destroy());});
 win.on('closed',()=>{win=null;tabs.clear();});
 await win.loadFile(path.join(__dirname,'toolbar.html'));ready=true;
 const restore=read(file('tabs.json'),[]);
 if(settings.rememberSessions&&Array.isArray(restore)&&restore.length){let restoredActive;for(const entry of restore.slice(0,20)){if(entry.url!==HOME&&!urlOK(entry.url))continue;const id=newTab(entry.url,false);if(entry.active)restoredActive=id;}if(tabs.size)setActive(restoredActive||[...tabs.keys()][0]);else newTab();}
 else newTab(HOME);
 layout();notify();setInterval(()=>storageCheck().catch(()=>{}),60000).unref();storageCheck().catch(()=>{});if(process.env.VAULTIE_PERF==='1'){await require(process.env.VAULTIE_PERF_SCRIPT)({win,tabs,newTab});return;}if(process.env.VAULTIE_SMOKE==='1'){try{await require('./test/electron-smoke')({win,profile,command,tabs,homeHTML,closeTab,newTab});console.log('VAULTIE_SMOKE_OK');app.exit(0);}catch(e){console.error('VAULTIE_SMOKE_FAILED',e);app.exit(1);}}
}).catch(e=>{console.error('Vaultie startup error',e);dialog.showErrorBox('Vaultie Startfehler',String(e.message||e));app.quit();});
app.on('window-all-closed',()=>{proxy?.stop().catch(()=>{});app.quit();});
async function extraCommand(cmd,arg){
 const t=selected(),wc=t?.view?.webContents;
 switch(cmd){
 case 'move-tab':{const ids=[...tabs.keys()],from=ids.indexOf(Number(arg?.from)),to=ids.indexOf(Number(arg?.to));if(from>=0&&to>=0){ids.splice(to,0,ids.splice(from,1)[0]);tabs=new Map(ids.map(id=>[id,tabs.get(id)]));notify();}return {ok:true};}
 case 'data-folder':await shell.openPath(dir);return {ok:true};
 case 'protection-report':return {blocked,stripped,domains:domains.size,report:blockReport};
 case 'import-filters':{
  const r=await dialog.showOpenDialog(win,{title:'HOSTS- oder einfache Domainfilter importieren',properties:['openFile'],filters:[{name:'Filterlisten',extensions:['txt']}]});if(r.canceled)return {canceled:true};
  if(fs.statSync(r.filePaths[0]).size>12000000)throw Error('Die Datei darf maximal 12 MB groß sein.');
  const text=fs.readFileSync(r.filePaths[0],'utf8'),parsed=privacy.parseFilters(text);
  if(!parsed.hosts.size)throw Error('Keine unterstützten Domainregeln gefunden. Die bisherige Liste bleibt erhalten.');
  fs.writeFileSync(file('filterliste.txt'),text,'utf8');domains=new Set([...privacy.DEFAULT_HOSTS,...parsed.hosts]);notify();return {ok:true,count:parsed.hosts.size,skipped:parsed.skipped};
 }
 case 'edit-bookmark':{
  const item=bookmarks.find(b=>b.url===arg?.old);const url=urlOK(arg?.url);if(!item||!url)return {error:'Gültige HTTP-/HTTPS-Adresse erforderlich.'};
  if(bookmarks.some(b=>b!==item&&b.url===url))return {error:'Diese Adresse ist bereits gespeichert.'};
  pinned=pinned.map(u=>u===item.url?url:u);item.url=url;item.title=String(arg.title||url).slice(0,500);save(file('bookmarks.json'),bookmarks);saveHome();return {ok:true};
 }
 case 'pin-bookmark':if(urlOK(arg)){if(pinned.includes(arg))pinned=pinned.filter(u=>u!==arg);else pinned.push(arg);hidden=hidden.filter(u=>u!==arg);saveHome();}return {ok:true};
 case 'home-shortcut':if(arg==='restore'){hidden=[];saveHome();}return {ok:true};
 case 'clear-history':history=[];save(file('history.json'),history);notify();return {ok:true};
 case 'remove-history':history=history.filter(h=>!(h.url===arg?.url&&h.visited===arg?.visited));save(file('history.json'),history);notify();return {ok:true};
 case 'storage':return storageCheck(Boolean(arg));
 case 'update-check':return checkUpdate();
 case 'read-form':{
  if(!t?.url.startsWith('https:'))return {error:'Zum Speichern eine HTTPS-Anmeldeseite öffnen.'};
  const origin=new URL(t.url).origin;
  const result=await wc.executeJavaScript(`(()=>{if(location.origin!==${JSON.stringify(origin)})return null;const p=[...document.querySelectorAll('input[type=password]')].find(e=>e.getClientRects().length&&!e.disabled);if(!p)return null;const root=p.form||document;const fields=[...root.querySelectorAll('input')].filter(e=>e!==p&&!e.disabled&&e.getClientRects().length);const u=fields.find(e=>e.autocomplete==='username'||e.type==='email'||/user|email|login/i.test(e.name))||fields.find(e=>e.type==='text');return {origin:location.origin,username:u?.value||'',password:p.value};})()`,true);
  return result||{error:'Kein sichtbares Passwortfeld gefunden.'};
 }
 case 'list-passwords':return {entries:passwords.map(x=>({origin:x.origin,username:x.username}))};
 case 'remove-password':passwords=passwords.filter(p=>!(p.origin===arg?.origin&&p.username===arg?.username));save(file('passwords.json'),passwords);return {ok:true};
 case 'import-passwords':return importPasswords();
 case 'download-directory':{
  const r=await dialog.showOpenDialog(win,{title:'Downloadordner auswählen',defaultPath:settings.downloadDirectory||app.getPath('downloads'),properties:['openDirectory','createDirectory']});if(r.canceled)return {canceled:true};settings.downloadDirectory=r.filePaths[0];save(file('settings.json'),settings);notify();return {ok:true};
 }
 case 'download-action':{
  const row=downloads.find(d=>d.id===Number(arg?.id));if(!row)return {error:'Download nicht gefunden.'};const item=downloadItems.get(row.id);
  if(arg.action==='pause'&&item)item.pause();else if(arg.action==='resume'&&item&&item.canResume())item.resume();else if(arg.action==='cancel'&&item)item.cancel();else if(arg.action==='show')shell.showItemInFolder(row.path);else if(arg.action==='open'&&row.status==='Fertig')await shell.openPath(row.path);notify();return {ok:true};
 }
 }
}
async function checkUpdate(){
 // Separate release channel: never replace the tested ECS engine with the old Qt build.
 const response=await profile.fetch('https://api.github.com/repos/lxlion6/Vaultie-Windows-Browser/releases?per_page=20',{headers:{Accept:'application/vnd.github+json','User-Agent':'Vaultie-UpdateCheck'},signal:AbortSignal.timeout(8000)});
 if(!response.ok)throw Error('Updateprüfung: HTTP '+response.status);
 const payload=await response.json();if(!Array.isArray(payload))throw Error('Ungültige Updateantwort.');
 const release=payload.find(r=>!r.draft&&/^castlabs-v\d+\.\d+\.\d+$/.test(r.tag_name));
 const current=require('./package.json').version;let newer=false;
 if(release){const a=release.tag_name.replace('castlabs-v','').split('.').map(Number),b=current.split('.').map(Number);for(let i=0;i<3;i++){if(a[i]!==b[i]){newer=a[i]>b[i];break;}}}
 return {current,available:newer,version:release?.tag_name||'',url:newer&&release.html_url?.startsWith('https://github.com/lxlion6/Vaultie-Windows-Browser/releases/')?release.html_url:null};
}
async function importPasswords(){
 if(process.platform!=='win32'||!encryptionAvailable())return {error:'Der Import benötigt Windows und die lokale Windows-Verschlüsselung.'};
 const result=await dialog.showOpenDialog(win,{title:'Bisherigen verschlüsselten Vaultie-Passwortspeicher importieren',defaultPath:path.join(process.env.LOCALAPPDATA||os.homedir(),'Vaultie','credentials.dat'),properties:['openFile'],filters:[{name:'Vaultie-Passwortspeicher',extensions:['dat']}]});
 if(result.canceled)return {canceled:true};const source=result.filePaths[0];if(fs.statSync(source).size>4000000)throw Error('Passwortdatei ist zu groß.');
 const raw=JSON.parse(fs.readFileSync(source,'utf8'));if(raw.version!==1||typeof raw.encrypted!=='string'||!/^[a-zA-Z0-9+/=]+$/.test(raw.encrypted))throw Error('Ungültiges Format der Passwortdatei.');
 const {spawn}=require('node:child_process');
 const script='Add-Type -AssemblyName System.Security; $s=[Console]::In.ReadToEnd(); $b=[Convert]::FromBase64String($s); $p=[Security.Cryptography.ProtectedData]::Unprotect($b,$null,[Security.Cryptography.DataProtectionScope]::CurrentUser); [Console]::Out.Write([Convert]::ToBase64String($p))';
 const decoded=await new Promise((resolve,reject)=>{const child=spawn('powershell.exe',['-NoProfile','-NonInteractive','-Command',script],{windowsHide:true});let out='',error='';const timer=setTimeout(()=>{child.kill();reject(Error('Zeitlimit beim Passwortimport.'));},15000);child.stdout.on('data',b=>{out+=b;if(out.length>6000000)child.kill();});child.stderr.on('data',b=>{error+=b;});child.on('error',e=>{clearTimeout(timer);reject(e);});child.on('close',code=>{clearTimeout(timer);if(code!==0)reject(Error('Windows konnte den alten Passwortspeicher für diesen Benutzer nicht entschlüsseln.'));else resolve(Buffer.from(out.trim(),'base64').toString('utf8'));});child.stdin.end(raw.encrypted);});
 const items=JSON.parse(decoded);if(!items||Array.isArray(items)||typeof items!=='object')throw Error('Ungültiger Passwortspeicher.');const additions=[];
 for(const [origin,v] of Object.entries(items)){
  if(!urlOK(origin)||new URL(origin).origin!==origin||!origin.startsWith('https:')||typeof v?.username!=='string'||typeof v?.password!=='string')continue;
  if(!passwords.some(p=>p.origin===origin&&p.username===v.username))additions.push({origin,username:v.username,secret:safeStorage.encryptString(v.password).toString('base64')});
 }
 passwords.push(...additions);save(file('passwords.json'),passwords);return {ok:true,count:additions.length};
}
