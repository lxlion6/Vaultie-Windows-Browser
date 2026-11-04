'use strict';
const {contextBridge,ipcRenderer}=require('electron');
const commands=new Set(['state','new-tab','switch-tab','close-tab','navigate','back','forward','reload','home','bookmark','remove-bookmark','open-bookmark','settings','download-folder','drm','save-password','get-password','fill-password','clear-data','panel','move-tab','data-folder','import-filters','protection-report','edit-bookmark','pin-bookmark','home-shortcut','clear-history','remove-history','storage','update-check','read-form','list-passwords','remove-password','import-passwords','download-action','download-directory']);
contextBridge.exposeInMainWorld('vaultie',{
 command:(name,value)=>commands.has(name)?ipcRenderer.invoke('vaultie:command',name,value):Promise.reject(Error('Unzulässige Funktion')),
 onState:fn=>{if(typeof fn==='function')ipcRenderer.on('vaultie:state',(_e,data)=>fn(data));},
 onOpen:fn=>{if(typeof fn==='function')ipcRenderer.on('vaultie:open',(_e,data)=>fn(data));}
});
