'use strict';
const $=id=>document.getElementById(id);
let model={tabs:[],bookmarks:[],downloads:[],settings:{},blocked:0},shown='';
const command=(name,arg)=>window.vaultie.command(name,arg);
function node(tag,text,className){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(className)e.className=className;return e;}
function button(text,action,kind){const e=node('button',text,kind);e.addEventListener('click',()=>Promise.resolve(action()).catch(error));return e;}
function error(err){$('status').textContent='Fehler: '+String(err?.message||err);}
function paragraph(container,text,cls='muted'){container.appendChild(node('p',text,cls));}
function row(container,label,...controls){const r=node('div',undefined,'entry');r.appendChild(node('span',label,'caption'));for(const c of controls)r.appendChild(c);container.appendChild(r);return r;}
function active(){return model.tabs.find(t=>t.id===model.active)||null;}
function update(data){
 model=data;
 const list=$('tabs');list.replaceChildren();
 for(const tab of data.tabs){
  const el=node('div',undefined,'tab'+(tab.active?' active':''));
  const title=node('span',tab.title||'Neuer Tab');title.title=tab.url||'';
  el.appendChild(title);
  el.appendChild(button('×',event=>{event.stopPropagation();return command('close-tab',tab.id);},'x'));
  el.addEventListener('click',()=>command('switch-tab',tab.id).catch(error));
  list.appendChild(el);
 }
 const current=active();if(document.activeElement!==$('address'))$('address').value=current?.url==='vaultie://home'?'':(current?.url||'');
 $('back').disabled=!current;
 $('forward').disabled=!current;
 $('shield').textContent=data.settings.adblock?'◆ Schutz aktiv':'◇ Schutz aus';
 $('status').textContent=(current?.loading?'Lade Webseite …':'Verlauf ausschließlich lokal gespeichert')+' | DRM: '+(data.widevine||'unbekannt').slice(0,110);
 if(shown==='bookmarks'||shown==='downloads'||shown==='settings')refresh(shown);
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
 bandwidth:'Bandbreitenlimit',history:'Verlauf'
 })[name]||'Vaultie';
 if(name==='bookmarks'){
  const filter=node('input');filter.placeholder='Lesezeichen durchsuchen';body.appendChild(filter);
  function render(q=''){
    const old=body.querySelector('#bookmark-entries');if(old)old.remove();
    const wrap=node('div');wrap.id='bookmark-entries';
    for(const entry of model.bookmarks.filter(v=>String(v.title+' '+v.url).toLowerCase().includes(q.toLowerCase()))){
      row(wrap,entry.title||entry.url,
        button('Öffnen',async()=>{await command('open-bookmark',entry.url);await hide();}),
        button('Löschen',()=>command('remove-bookmark',entry.url),'danger'));
    }
    if(!wrap.childNodes.length)paragraph(wrap,'Keine passenden Lesezeichen gespeichert.');
    body.appendChild(wrap);
  }
  filter.addEventListener('input',()=>render(filter.value));render();
 }else if(name==='downloads'){
  body.appendChild(button('Downloadordner öffnen',()=>command('download-folder')));
  for(const d of model.downloads.slice().reverse())row(body,d.name+' – '+d.progress+' % – '+d.status);
  if(!model.downloads.length)paragraph(body,'Noch keine Downloads in dieser Sitzung.');
 }else if(name==='logins'){
  paragraph(body,'Passwörter werden ausschließlich nach deiner Freigabe lokal mit der Windows-Verschlüsselung gespeichert. Die bisherige Qt-Passwortdatenbank wird nicht übernommen.');
  if(!model.encryption){paragraph(body,'Windows-Verschlüsselung nicht verfügbar. Speichern ist deaktiviert.');return;}
  body.appendChild(button('Gespeicherten Login ausfüllen',async()=>{
    const r=await command('fill-password');paragraph(body,r?.error||'Das Formular wurde geprüft.');}));
  const u=node('input');u.placeholder='Benutzername oder E-Mail';
  const p=node('input');p.type='password';p.placeholder='Passwort';p.autocomplete='new-password';
  body.appendChild(node('label','Benutzername'));body.appendChild(u);
  body.appendChild(node('label','Passwort'));body.appendChild(p);
  body.appendChild(button('Für diese HTTPS-Webseite verschlüsselt speichern',async()=>{
    const r=await command('save-password',{username:u.value,password:p.value});
    p.value='';paragraph(body,r?.error||'Zugangsdaten verschlüsselt gespeichert.');}));
 }else if(name==='settings'){
  for(const [key,label] of [['adblock','Werbe-/Trackerschutz'],['stripTracking','Trackingparameter entfernen'],['rememberSessions','Tabs beim nächsten Start wiederherstellen']]){
    const input=node('input');input.type='checkbox';input.checked=Boolean(model.settings[key]);input.style.width='auto';
    input.addEventListener('change',()=>command('settings',{key,value:input.checked}).catch(error));
    const r=node('div',undefined,'row');r.append(input,node('span',label));body.appendChild(r);
  }
  paragraph(body,'Datenschutz: Cookies werden derzeit in einem separaten dauerhaften castLabs-Profil gespeichert. Das unterscheidet sich von der privaten Standardsitzung des bisherigen Vaultie.');
  body.appendChild(button('Cookies, Website-Daten und Cache löschen',async()=>{
    const r=await command('clear-data');paragraph(body,r?.error||'Website-Daten wurden gelöscht.');}));
  paragraph(body,'Bandbreitenbegrenzung, Fingerprinting-Schutz und Import des bisherigen Passwortspeichers sind hier noch nicht gleichwertig umgesetzt.');
 }else if(name==='menu'){
  for(const [label,target] of [['Neuer Tab','new'],['Lesezeichen verwalten','bookmarks'],['Gespeicherte Logins','logins'],['Downloads anzeigen','downloads'],['Video-Codecs und DRM prüfen','drm'],['Datenschutz-Einstellungen','settings'],['Bandbreitenlimit','bandwidth'],['VPN-Empfehlungen','vpn']]){
    body.appendChild(button(label,()=>target==='new'?command('new-tab','vaultie://home'):show(target)));body.appendChild(node('span','  '));
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
  paragraph(body,'Die zuvor vorhandene Bandbreitenbegrenzung ist in der neuen Engine noch nicht implementiert. Es wurde absichtlich keine funktionslose Einstellung eingebaut.');
 }else if(name==='history'){
  paragraph(body,'Die alte lokale Verlaufsdatenbank wurde nicht importiert. Der Entwicklungsbrowser legt derzeit keine eigene Verlaufsliste an.');
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
window.vaultie.onOpen(name=>show(name).catch(error));
command('state').then(update).catch(error);
