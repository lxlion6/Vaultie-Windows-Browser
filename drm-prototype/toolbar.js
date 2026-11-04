'use strict';
const $=id=>document.getElementById(id);
let model={tabs:[],bookmarks:[],downloads:[],settings:{},blocked:0},shown='';
const command=async(name,arg)=>{const r=await window.vaultie.command(name,arg);if(r?.error)throw Error(r.error);return r;};
function node(tag,text,className){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(className)e.className=className;return e;}
function button(text,action,kind){const e=node('button',text,kind);e.addEventListener('click',event=>Promise.resolve(action(event)).catch(error));return e;}
function error(err){$('status').textContent='Fehler: '+String(err?.message||err);}
function paragraph(container,text,cls='muted'){container.appendChild(node('p',text,cls));}
function row(container,label,...controls){const r=node('div',undefined,'entry');r.appendChild(node('span',label,'caption'));for(const c of controls)r.appendChild(c);container.appendChild(r);return r;}
function active(){return model.tabs.find(t=>t.id===model.active)||null;}
function update(data){
 model=data;
 const list=$('tabs');list.replaceChildren();
 for(const tab of data.tabs){
  const el=node('div',undefined,'tab'+(tab.active?' active':''));
  el.draggable=true;el.addEventListener('dragstart',e=>e.dataTransfer.setData('text/plain',String(tab.id)));el.addEventListener('dragover',e=>e.preventDefault());el.addEventListener('drop',e=>{e.preventDefault();command('move-tab',{from:Number(e.dataTransfer.getData('text/plain')),to:tab.id}).catch(error);});
  const title=node('span',tab.title||'Neuer Tab');title.title=tab.url||'';
  el.appendChild(title);
  el.appendChild(button('×',event=>{event.stopPropagation();return command('close-tab',tab.id);},'x'));
  el.addEventListener('click',()=>command('switch-tab',tab.id).catch(error));
  list.appendChild(el);
 }
 const current=active();if(document.activeElement!==$('address'))$('address').value=current?.url==='vaultie://home'?'':(current?.url||'');
 $('back').disabled=!current;
 $('forward').disabled=!current;
 $('bandwidth').textContent=data.settings.bandwidthEnabled?data.settings.bandwidthMbps+' Mbit/s':'∞ Mbit/s';
 $('shield').textContent=data.settings.adblock?'◆ Schutz aktiv':'◇ Schutz aus';
 $('downloads').textContent='↓ Downloads'+(data.downloads.filter(d=>d.status==='Lädt'||d.status==='Pausiert').length?' ('+data.downloads.filter(d=>d.status==='Lädt'||d.status==='Pausiert').length+')':'');
 $('status').textContent=(current?.loading?'Lade Webseite …':'Verlauf ausschließlich lokal gespeichert')+' | DRM: '+(data.widevine||'unbekannt').slice(0,110);
 if(shown==='downloads'||shown==='report')refresh(shown);
}
async function show(name){
 if(shown===name){await hide();return;}
 shown=name;
 $('panel').classList.add('visible');
 await command('panel',true);
 refresh(name);
}
async function hide(){
 shown='';$('panel').classList.remove('visible');
 await command('panel',false);
}
function refresh(name){
 const body=$('panelbody');body.replaceChildren();$('paneltitle').textContent=({
 bookmarks:'Lesezeichen verwalten',downloads:'Downloads',logins:'Gespeicherte Zugangsdaten',
 settings:'Einstellungen',menu:'Vaultie – Menü',vpn:'VPN-Empfehlungen',drm:'Video-Codecs und DRM',
 bandwidth:'Bandbreitenlimit',history:'Verlauf',report:'Schutzbericht',storage:'Browser-Speicher',updates:'Updates',security:'Sicherheit',shortcuts:'Startseite anpassen'
 })[name]||'Vaultie';
 if(name==='bookmarks'){
  const filter=node('input');filter.placeholder='Lesezeichen durchsuchen';body.appendChild(filter);
  function render(q=''){
    const old=body.querySelector('#bookmark-entries');if(old)old.remove();
    const wrap=node('div');wrap.id='bookmark-entries';
    for(const entry of model.bookmarks.filter(v=>String(v.title+' '+v.url).toLowerCase().includes(q.toLowerCase()))){
      row(wrap,entry.title||entry.url,
        button('Öffnen',async()=>{await command('open-bookmark',entry.url);await hide();}),
        button('Bearbeiten',()=>editBookmark(entry)),
        button(model.pinned.includes(entry.url)?'Lösen':'Anheften',async()=>{await command('pin-bookmark',entry.url);render(filter.value);} ),
        button('Löschen',async()=>{await command('remove-bookmark',entry.url);render(filter.value);},'danger'));
    }
    if(!wrap.childNodes.length)paragraph(wrap,'Keine passenden Lesezeichen gespeichert.');
    body.appendChild(wrap);
  }
  filter.addEventListener('input',()=>render(filter.value));render();
 }else if(name==='downloads'){
  body.appendChild(button('Downloadordner öffnen',()=>command('download-folder')));
  body.appendChild(button('Zielordner ändern',()=>command('download-directory')));
  for(const d of model.downloads.slice().reverse()){
   const actions=[button('Ordner',()=>command('download-action',{id:d.id,action:'show'}))];
   if(d.status==='Fertig')actions.push(button('Öffnen',()=>command('download-action',{id:d.id,action:'open'})));
   if(d.status==='Lädt'||d.status==='Pausiert')actions.push(button(d.status==='Pausiert'?'Fortsetzen':'Pausieren',()=>command('download-action',{id:d.id,action:d.status==='Pausiert'?'resume':'pause'})),button('Abbrechen',()=>command('download-action',{id:d.id,action:'cancel'})));
   row(body,d.name+' – '+d.progress+' % – '+d.status,...actions);
  }
  if(!model.downloads.length)paragraph(body,'Noch keine Downloads in dieser Sitzung.');
 }else if(name==='logins'){
  paragraph(body,'Passwörter werden ausschließlich nach deiner Freigabe lokal mit der Windows-Verschlüsselung gespeichert. Den bisherigen verschlüsselten Passwortspeicher kannst du über „Importieren“ übernehmen.');
  if(!model.encryption){paragraph(body,'Windows-Verschlüsselung nicht verfügbar. Speichern ist deaktiviert.');return;}
  body.appendChild(button('Gespeicherten Login ausfüllen',async()=>{
    const r=await command('fill-password');paragraph(body,r?.error||(r===true?'Login ausgefüllt.':'Kein passendes Passwortfeld gefunden.'));}));
  let capturedOrigin=null;const u=node('input');u.placeholder='Benutzername oder E-Mail';
  const p=node('input');p.type='password';p.placeholder='Passwort';p.autocomplete='new-password';
  body.appendChild(button('Aus aktuellem Loginformular übernehmen',async()=>{const v=await command('read-form');u.value=v.username;p.value=v.password;capturedOrigin=v.origin;paragraph(body,'Formular übernommen. Erst „Speichern“ legt den Login verschlüsselt ab.');}));
  body.appendChild(button('Bisherigen Passwortspeicher importieren',async()=>{const v=await command('import-passwords');if(!v.canceled)paragraph(body,v.count+' Zugangsdaten importiert.');}));
  body.appendChild(node('label','Benutzername'));body.appendChild(u);
  body.appendChild(node('label','Passwort'));body.appendChild(p);
  body.appendChild(button('Für diese HTTPS-Webseite verschlüsselt speichern',async()=>{
    const r=await command('save-password',{username:u.value,password:p.value,origin:capturedOrigin});
    p.value='';paragraph(body,r?.error||'Zugangsdaten verschlüsselt gespeichert.');}));
  const entries=node('div');body.appendChild(entries);
  command('list-passwords').then(r=>{for(const v of r.entries)row(entries,v.origin+' – '+v.username,button('Löschen',async()=>{await command('remove-password',v);refresh('logins');},'danger'));}).catch(error);
 }else if(name==='settings'){
  for(const [key,label] of [['adblock','Werbe-/Trackerschutz'],['stripTracking','Trackingparameter entfernen'],['rememberSessions','Website-Sitzungen und Tabs nach Neustart behalten'],['fingerprinting','Fingerprinting-Schutz'],['thirdPartyCookies','Drittanbieter-Cookies blockieren'],['clearHistoryOnExit','Verlauf beim Beenden löschen']]){
    const input=node('input');input.type='checkbox';input.checked=Boolean(model.settings[key]);input.style.width='auto';
    input.addEventListener('change',async()=>{try{const r=await command('settings',{key,value:input.checked});if(r.restart)paragraph(body,'Die Sitzungseinstellung gilt ab dem nächsten Start.');if(r.reload)paragraph(body,'Der Fingerprinting-Schutz gilt beim nächsten Laden einer Seite.');}catch(e){error(e);}});
    const r=node('div',undefined,'row');r.append(input,node('span',label));body.appendChild(r);
  }
  paragraph(body,'Standard: flüchtige Website-Sitzung. Nur bei aktivierter Sitzungsaufbewahrung werden Cookies und Website-Daten für den nächsten Start gespeichert. Lesezeichen und ausdrücklich gespeicherte Logins bleiben lokal erhalten.');
  body.appendChild(button('Cookies, Website-Daten und Cache löschen',async()=>{
    const r=await command('clear-data');paragraph(body,r?.error||'Website-Daten wurden gelöscht.');}));
  paragraph(body,'Für Amazon-/Prime-Domains gelten die bisherigen Kompatibilitätsausnahmen beim Fingerprinting- und Cookie-Schutz.');
 body.appendChild(button('Startseite anpassen',()=>show('shortcuts')));
 }else if(name==='menu'){
  for(const [label,target] of [['Neuer Tab','new'],['Lesezeichen verwalten','bookmarks'],['Gespeicherte Logins','logins'],['Downloads anzeigen','downloads'],['Video-Codecs und DRM prüfen','drm'],['Datenschutz-Einstellungen','settings'],['Bandbreitenlimit','bandwidth'],['VPN-Empfehlungen','vpn'],['Verlauf','history'],['Schutzbericht','report'],['Filterliste importieren','filters'],['Browser-Speicher','storage'],['Auf Updates prüfen','updates'],['Sicherheitshinweise','security'],['Startseite anpassen','shortcuts'],['Lokalen Datenordner öffnen','data-folder']]){
    body.appendChild(button(label,()=>target==='new'?command('new-tab','vaultie://home'):target==='filters'?importFilters():target==='data-folder'?command('data-folder'):show(target)));body.appendChild(node('span','  '));
  }
  paragraph(body,'Vaultie – Entwicklungsfassung mit castLabs/Widevine. Noch keine Freigabe als Ersatz für Vaultie 4.2.');
 }else if(name==='vpn'){
  paragraph(body,'Vaultie stellt selbst keine VPN-Verbindung her.');
  for(const [label,url] of [['Mullvad VPN','https://mullvad.net/'],['NordVPN','https://nordvpn.com/']])
   body.appendChild(button(label,async()=>{await command('new-tab',url);await hide();}));
 }else if(name==='drm'){
  paragraph(body,'Prüft H.264, AAC und Widevine auf dem aktiven HTTPS-Tab.');
  const output=node('pre','Prüfung noch nicht gestartet.');output.style.whiteSpace='pre-wrap';body.appendChild(output);
  body.appendChild(button('Jetzt prüfen',async()=>{
    output.textContent='Prüfung läuft (maximal 15 Sekunden) …';
    const result=await command('drm');
    output.textContent=result?.error||('H.264: '+result.h264+'\nAAC: '+result.aac+'\nWidevine: '+result.widevine+'\n\nEin positiver Test garantiert keine Prime-Video-Freigabe.');
  }));
 }else if(name==='bandwidth'){
  paragraph(body,'Gemeinsames Limit für Upload und Download aller Tabs. Aus = direkte Verbindung. Der lokale Begrenzer entschlüsselt keine HTTPS-Inhalte.');
  checkbox(body,'Begrenzung aktiv',model.settings.bandwidthEnabled,async value=>{await command('settings',{key:'bandwidthEnabled',value});refresh('bandwidth');});
  const slider=node('input');slider.type='range';slider.min='3';slider.max='25';slider.step='1';slider.value=model.settings.bandwidthMbps;
  const output=node('p',slider.value+' Mbit/s');slider.addEventListener('input',()=>output.textContent=slider.value+' Mbit/s');
  slider.addEventListener('change',()=>command('settings',{key:'bandwidthMbps',value:Number(slider.value)}).catch(error));body.append(slider,output);
  paragraph(body,'WebRTC-Sprach- und Videoverbindungen können je nach Dienst mit aktivem Proxy eingeschränkt sein.');
 }else if(name==='history'){
  checkbox(body,'Verlauf beim Beenden löschen',model.settings.clearHistoryOnExit,value=>command('settings',{key:'clearHistoryOnExit',value}));
  body.appendChild(button('Gesamten Verlauf löschen',async()=>{await command('clear-history');refresh('history');},'danger'));
  const search=node('input');search.placeholder='Verlauf durchsuchen';body.appendChild(search);const results=node('div');body.appendChild(results);
  function render(){results.replaceChildren();for(const h of model.history.slice().reverse().filter(h=>(h.title+' '+h.url).toLowerCase().includes(search.value.toLowerCase()))){row(results,(h.title||h.url)+' – '+new Date(h.visited).toLocaleString('de-DE'),button('Öffnen',async()=>{await command('new-tab',h.url);await hide();}),button('Löschen',async()=>{await command('remove-history',h);render();},'danger'));}if(!results.childNodes.length)paragraph(results,'Keine passenden Verlaufseinträge.');}
  search.addEventListener('input',render);render();
 }else if(name==='report'){
  paragraph(body,model.blocked+' Werbe-/Trackinganfragen blockiert; '+model.stripped+' Trackingadressen bereinigt. '+model.filterCount+' Domainregeln aktiv.');
  body.appendChild(button('Filterliste importieren',importFilters));
  paragraph(body,'Domainfilter: HOSTS, reine Domains und einfache ||domain^-Regeln. Komplexe EasyList- und kosmetische Regeln werden nicht unterstützt.');
  for(const [host,count] of Object.entries(model.blockReport).sort((a,b)=>b[1]-a[1]).slice(0,100))row(body,host+' – '+count);
 }else if(name==='storage'){
  paragraph(body,'Interne Browser-Daten: '+((model.storage.bytes||0)/1e9).toFixed(2)+' GB. Zielbudget 5 GB; Cachebereinigung ab 3,8 GB. Downloads werden weder mitgezählt noch gelöscht.');
  if(model.storage.over)paragraph(body,'5 GB überschritten: Verbleibende Website-Daten werden zum Schutz deiner Inhalte nicht automatisch gelöscht.','notice');
  body.appendChild(button('Cache bereinigen und Speicher prüfen',async()=>{await command('storage',true);refresh('storage');}));
 }else if(name==='updates'){
  const result=node('p','Updateprüfung läuft …');body.appendChild(result);
  command('update-check').then(r=>{result.textContent=r.available?'Neue castLabs-Version: '+r.version:'Keine neuere castLabs-Version veröffentlicht. Installiert: '+r.current;if(r.url)body.appendChild(button('Veröffentlichung öffnen',async()=>{await command('new-tab',r.url);await hide();}));}).catch(e=>result.textContent=e.message);
 }else if(name==='shortcuts'){
  paragraph(body,'Lesezeichen lassen sich im Lesezeichenfenster auf der Startseite anheften. Über × auf einer Kachel entfernst du sie.');
  body.appendChild(button('Standard-Schnellwahl wieder anzeigen',async()=>{await command('home-shortcut','restore');paragraph(body,'Standard-Schnellwahl wiederhergestellt.');}));
 }else if(name==='security'){
  paragraph(body,'Kein eingebautes VPN. Der Browser nutzt deine normale Internetverbindung und gegebenenfalls ein separat eingeschaltetes Windows-VPN.');
  paragraph(body,'Verlauf und Lesezeichen bleiben lokal. Nur ausdrücklich gespeicherte Zugangsdaten werden verschlüsselt abgelegt. Website-Sitzungen sind standardmäßig flüchtig.');
  paragraph(body,'Der Domainfilter und die Verringerung von Fingerprinting verhindern nicht jede Form der Wiedererkennung. Websites erhalten technisch erforderliche Anfragen und deine Eingaben.');
  paragraph(body,'Die von dir erfolgreich getestete castLabs-Engine bleibt unverändert. Die ergänzten Browserfunktionen benötigen noch den Gesamtvergleich unter Windows.');
 }
}
function bind(id,name,arg){$(id).addEventListener('click',()=>command(name,arg).catch(error));}
bind('newtab','new-tab','vaultie://home');
bind('back','back');bind('forward','forward');bind('reload','reload');bind('home','home');
bind('bookmark','bookmark');
$('bookmarks').addEventListener('click',()=>show('bookmarks').catch(error));
$('downloads').addEventListener('click',()=>show('downloads').catch(error));
$('logins').addEventListener('click',()=>show('logins').catch(error));
$('shield').addEventListener('click',()=>command('settings',{key:'adblock',value:!model.settings.adblock}).catch(error));
$('vpn').addEventListener('click',()=>show('vpn').catch(error));
$('menu').addEventListener('click',()=>show('menu').catch(error));
$('bandwidth').addEventListener('click',()=>show('bandwidth').catch(error));
$('closepanel').addEventListener('click',()=>hide().catch(error));
$('address').addEventListener('keydown',e=>{if(e.key==='Enter'){command('navigate',$('address').value).catch(error);$('address').blur();}});
document.addEventListener('keydown',e=>{
 if(e.key==='Escape'&&shown){hide().catch(error);return;}
 if(e.ctrlKey){
  switch(e.key.toLowerCase()){
  case 't':e.preventDefault();command('new-tab','vaultie://home').catch(error);break;
  case 'w':e.preventDefault();if(active())command('close-tab',active().id).catch(error);break;
  case 'l':e.preventDefault();$('address').focus();$('address').select();break;
  case 'd':e.preventDefault();command('bookmark').catch(error);break;
  case 'r':e.preventDefault();command('reload').catch(error);break;
  }
 }
});
window.vaultie.onState(update);
window.vaultie.onOpen(name=>{if(name==='address'){$('address').focus();$('address').select();}else show(name).catch(error);});
command('state').then(update).catch(error);

function checkbox(body,label,checked,change){const input=node('input');input.type='checkbox';input.checked=checked;input.style.width='auto';input.addEventListener('change',()=>Promise.resolve(change(input.checked)).catch(error));const r=node('label',undefined,'row');r.append(input,node('span',label));body.appendChild(r);}
async function importFilters(){const r=await command('import-filters');if(!r.canceled)paragraph($('panelbody'),r.count+' Domainregeln importiert; '+r.skipped+' nicht unterstützte Zeilen ausgelassen.');}
function editBookmark(entry){const body=$('panelbody');body.replaceChildren();const title=node('input');title.value=entry.title;const url=node('input');url.value=entry.url;body.append(node('label','Titel'),title,node('label','Adresse'),url,button('Speichern',async()=>{await command('edit-bookmark',{old:entry.url,title:title.value,url:url.value});refresh('bookmarks');}),button('Abbrechen',()=>refresh('bookmarks')));}
