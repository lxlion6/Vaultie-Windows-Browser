'use strict';
const { contextBridge, ipcRenderer } = require('electron');
const allowed = new Set(['navigate', 'back', 'forward', 'reload', 'home', 'drm', 'vmp', 'panel']);
contextBridge.exposeInMainWorld('vaultie', {
  command: (cmd, value) => allowed.has(cmd) ? ipcRenderer.invoke('vaultie:command', cmd, value) : Promise.reject(new Error('Unsupported command')),
  onStatus: callback => {
    if (typeof callback !== 'function') return;
    ipcRenderer.on('vaultie:status', (_event, state) => callback(state));
  },
});
