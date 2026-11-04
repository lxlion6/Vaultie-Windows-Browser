'use strict';
const {app,BrowserWindow,WebContentsView,ipcMain,session,dialog,shell,safeStorage,components} = require('electron');
const fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const HOME='vaultie://home';
const BLOCKED=['doubleclick.net','googlesyndication.com','googleadservices.com','adnxs.com','taboola.com','outbrain.com','scorecardresearch.com','criteo.com','rubiconproject.com','pubmatic.com','adsrvr.org'];
const TRACK=new Set(['fbclid','gclid','dclid','msclkid','twclid','igshid','mc_cid','mc_eid']);
let win=null,tabs=new Map(),active=null,seq=0,ready=false,widevine='Nicht geprüft',downloads=[],bookmarks=[],passwords=[],settings={adblock:true,stripTracking:true,rememberSessions:false},blocked=0,closing=false;
let dir,profile;
const read=(p,d)=>{try{return JSON.parse(fs.readFileSync(p,'utf8'));}catch{return d;}};
function save(p,x){const tmp=p+'.tmp';fs.writeFileSync(tmp,JSON.stringify(x,null,2),'utf8');fs.renameSync(tmp,p);}
function file(n){return path.join(dir,n);}
function urlOK(s){try{const u=new URL(s);return /^(https?:)$/.test(u.protocol)?u.href:null;}catch{return null;}}
function clean(s){if(!settings.stripTracking)return s;try{const u=new URL(s);if(!urlOK(s))return s;let dirty=false;for(const k of [...u.searchParams.keys()])if(k.toLowerCase().startsWith('utm_')||TRACK.has(k.toLowerCase())){u.searchParams.delete(k);dirty=true;}return dirty?u.href:s;}catch{return s;}}
function location(input){const s=String(input||'').trim();if(s===HOME)return HOME;if(urlOK(s))return clean(s);if(/^(?:localhost|(?:[\w-]+\.)+[a-z]{2,})(?::\d+)?(?:[/?#]|$)/i.test(s))return clean('https://'+s);return 'https://www.startpage.com/sp/search?query='+encodeURIComponent(s);}
function selected(){return tabs.get(active);}
function state(){return {tabs:[...tabs.values()].map(t=>({id:t.id,title:t.title,url:t.url,active:t.id===active,loading:t.loading})),active,bookmarks,downloads:downloads.slice(-70),settings,blocked,widevine,encryption:safeStorage.isEncryptionAvailable()};}
function notify(){if(win&&!win.isDestroyed()&&ready)win.webContents.send('vaultie:state',state());}
function layout(){if(!win||win.isDestroyed())return;const [w,h]=win.getContentSize();for(const t of tabs.values())t.view.setBounds({x:0,y:113,width:Math.max(1,w),height:Math.max(1,h-137)});}
function snapshot(t){if(!t||t.view.webContents.isDestroyed())return;t.url=t.view.webContents.getURL()||t.url;t.title=t.view.webContents.getTitle()||t.title;t.loading=t.view.webContents.isLoading();notify();}
function setActive(id){const t=tabs.get(id);if(!t)return;if(active!==null&&tabs.has(active))win.contentView.removeChildView(tabs.get(active).view);active=id;win.contentView.addChildView(t.view);layout();t.view.webContents.focus();notify();}
function newTab(address=HOME,switchTo=true){
  const id=++seq;
  const view=new WebContentsView({webPreferences:{session:profile,contextIsolation:true,nodeIntegration:false,sandbox:true}});
  view.setBackgroundColor('#021b22');
  const t={id,title:'Neuer Tab',url:HOME,view,loading:false};tabs.set(id,t);
  const wc=view.webContents;
  for(const evt of ['did-start-loading','did-stop-loading','did-navigate','did-navigate-in-page','page-title-updated'])wc.on(evt,()=>snapshot(t));
  wc.on('did-fail-load',(_e,code,description,_url,main)=>{if(main&&code!==-3){t.title='Seitenfehler: '+description;notify();}});
  wc.on('will-navigate',(e,url)=>{if(url.startsWith('vaultie://')){e.preventDefault();const command=url.slice('vaultie://'.length).split('/')[0];if(command==='bookmarks')notifyAndOpen('bookmarks');else if(command==='history')notifyAndOpen('history');return;}if(!urlOK(url))e.preventDefault();});
  wc.setWindowOpenHandler(({url})=>{if(urlOK(url))newTab(clean(url),true);return {action:'deny'};});
  if(switchTo||tabs.size===1)setActive(id);
  visit(t,address);
  notify();return id;
}
function notifyAndOpen(name){if(win&&!win.isDestroyed())win.webContents.send('vaultie:open',name);}
function visit(t,address){
 if(address===HOME){t.url=HOME;t.title='Neuer Tab – Vaultie';t.view.webContents.loadFile(path.join(__dirname,'startseite.html')).catch(e=>{t.title=e.message;notify();});}
 else {const dest=location(address);t.view.webContents.loadURL(dest).catch(e=>{t.title=e.message;notify();});}
 notify();
}
function closeTab(id){const t=tabs.get(id);if(!t)return;if(active===id)win.contentView.removeChildView(t.view);tabs.delete(id);t.view.webContents.close();if(!tabs.size)newTab();else if(active===id)setActive([...tabs.keys()][tabs.size-1]);notify();}
function persistTabs(){const items=[...tabs.values()].map(t=>({url:t.url,active:t.id===active})).filter(t=>t.url===HOME||urlOK(t.url));save(file('tabs.json'),items.slice(-25));}
function addBookmark(){const t=selected();if(!t||!urlOK(t.url))return {error:'Nur Webseiten als Lesezeichen.'};if(!bookmarks.some(x=>x.url===t.url)){bookmarks.push({title:t.title||t.url,url:t.url});save(file('bookmarks.json'),bookmarks);}notify();return {ok:true};}
function initFiles(){
 dir=path.join(app.getPath('userData'),'castlabs-profile');fs.mkdirSync(dir,{recursive:true});
 const old=path.join(process.env.LOCALAPPDATA||path.join(os.homedir(),'AppData','Local'),'Vaultie','bookmarks.json');
 if(!fs.existsSync(file('bookmarks.json'))&&fs.existsSync(old)){const items=read(old,[]);if(Array.isArray(items))save(file('bookmarks.json'),items.filter(v=>v&&urlOK(v.url)));}
 bookmarks=read(file('bookmarks.json'),[]);if(!Array.isArray(bookmarks))bookmarks=[];
 passwords=read(file('passwords.json'),[]);if(!Array.isArray(passwords))passwords=[];
 settings={...settings,...read(file('settings.json'),{})};
}
function setupSession(){
 profile=session.fromPartition('persist:vaultie-castlabs');
 profile.webRequest.onBeforeRequest((details,callback)=>{
  if(!settings.adblock||details.resourceType==='mainFrame')return callback({});
  try{const host=new URL(details.url).hostname; if(BLOCKED.some(x=>host===x||host.endsWith('.'+x))){blocked++;notify();return callback({cancel:true});}}catch{}
  callback({});
 });
 profile.on('will-download',(_event,item)=>{
  const row={id:downloads.length+1,name:item.getFilename(),progress:0,status:'Lädt',path:path.join(app.getPath('downloads'),item.getFilename())};
  downloads.push(row);item.setSavePath(row.path);notify();
  item.on('updated',()=>{const total=item.getTotalBytes();row.progress=total?Math.round(item.getReceivedBytes()*100/total):0;notify();});
  item.once('done',(_e,state)=>{row.status=state==='completed'?'Fertig':state;notify();});
 });
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
 if(!safeStorage.isEncryptionAvailable())return {error:'Windows-Verschlüsselung ist nicht verfügbar. Keine Passwörter werden unverschlüsselt gespeichert.'};
 const t=selected();if(!t||!urlOK(t.url))return {error:'Öffne eine HTTPS-Webseite.'};const origin=new URL(t.url).origin;
 if(!origin.startsWith('https:'))return {error:'Passwörter werden nur für HTTPS gespeichert.'};
 if(cmd==='save-password'){
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
 const t=selected(),wc=t?.view.webContents;
 switch(cmd){
 case 'state':return state();
 case 'new-tab':return newTab(typeof arg==='string'?arg:HOME);
 case 'switch-tab':setActive(Number(arg));break;
 case 'close-tab':closeTab(Number(arg));break;
 case 'navigate':if(t)visit(t,location(arg));break;
 case 'back':if(wc?.canGoBack())wc.goBack();break;
 case 'forward':if(wc?.canGoForward())wc.goForward();break;
 case 'reload':wc?.reload();break;
 case 'home':if(t)visit(t,HOME);break;
 case 'bookmark':return addBookmark();
 case 'remove-bookmark':bookmarks=bookmarks.filter(v=>v.url!==arg);save(file('bookmarks.json'),bookmarks);break;
 case 'open-bookmark':if(t&&urlOK(arg))visit(t,arg);break;
 case 'settings':if(arg?.key==='adblock'||arg?.key==='stripTracking'||arg?.key==='rememberSessions'){settings[arg.key]=Boolean(arg.value);save(file('settings.json'),settings);}break;
 case 'download-folder':await shell.openPath(app.getPath('downloads'));break;
 case 'drm':return await checkDrm();
 case 'save-password':case 'get-password':return credentials(cmd,arg);
 case 'fill-password':{
  const v=credentials('get-password');if(v.error)return v;
  // Password is only injected into fields on the matching HTTPS origin; never sent to the page as a message.
  return wc.executeJavaScript('(function(u,p){if(location.origin!=='+JSON.stringify(v.origin)+')return false;const a=document.querySelector("input[autocomplete=username], input[type=email], input[name*=user]");const b=document.querySelector("input[type=password]");if(!b)return false;for(const [el,value] of [[a,u],[b,p]]){if(el){const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,"value").set;setter.call(el,value);el.dispatchEvent(new Event("input",{bubbles:true}));}}return true;})('+JSON.stringify(v.username)+','+JSON.stringify(v.password)+')',true);
 }
 case 'clear-data':await profile.clearStorageData({storages:['cookies','localstorage','indexdb','serviceworkers']});await profile.clearCache();break;
 default:return {error:'Unbekannte Aktion.'};
 }
 notify();return {ok:true};
}
ipcMain.handle('vaultie:command',command);
app.whenReady().then(async()=>{
 initFiles();setupSession();
 try{await components.whenReady();widevine=JSON.stringify(components.status());}catch(e){widevine='CDM: '+String(e.message||e);}
 win=new BrowserWindow({width:1280,height:820,minWidth:780,minHeight:520,backgroundColor:'#041d24',title:'Vaultie – Streaming-Entwicklungsfassung',webPreferences:{preload:path.join(__dirname,'preload.js'),contextIsolation:true,nodeIntegration:false,sandbox:true}});
 win.on('resize',layout);
 win.on('close',()=>{closing=true;persistTabs();});
 win.on('closed',()=>{win=null;tabs.clear();});
 await win.loadFile(path.join(__dirname,'toolbar.html'));ready=true;
 const restore=read(file('tabs.json'),[]);
 if(settings.rememberSessions&&Array.isArray(restore)&&restore.length){for(const entry of restore.slice(0,20))newTab(entry.url,false);setActive([...tabs.keys()][0]);}
 else newTab(HOME);
 layout();notify();
}).catch(e=>{console.error('Vaultie startup error',e);dialog.showErrorBox('Vaultie Startfehler',String(e.message||e));app.quit();});
app.on('window-all-closed',()=>app.quit());
