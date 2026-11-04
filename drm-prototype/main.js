'use strict';
const { app, BrowserWindow, WebContentsView, components, ipcMain, session, shell } = require('electron');
const path = require('node:path');

const START_PAGE = 'https://shaka-player-demo.appspot.com/';
let win = null;
let view = null;
let uiReady = false;
let widevineStatus = 'Ungeprüft';
let navigationError = '';

function validUrl(raw) {
  try {
    const u = new URL(raw);
    return (u.protocol === 'https:' || u.protocol === 'http:') ? u.href : null;
  } catch { return null; }
}
function sendStatus() {
  if (!win || win.isDestroyed() || !uiReady) return;
  win.webContents.send('vaultie:status', {
    url: view?.webContents.getURL() || '',
    title: view?.webContents.getTitle() || '',
    loading: view?.webContents.isLoading() || false,
    canBack: view?.webContents.canGoBack() || false,
    canForward: view?.webContents.canGoForward() || false,
    widevine: widevineStatus,
    error: navigationError,
  });
}
function setBounds() {
  if (!win || !view || win.isDestroyed()) return;
  const [w, h] = win.getContentSize();
  view.setBounds({ x: 0, y: 92, width: Math.max(w, 1), height: Math.max(h - 92, 1) });
}
function navigate(input) {
  let url = validUrl(input);
  if (!url) url = 'https://www.startpage.com/sp/search?query=' + encodeURIComponent(input || '');
  navigationError = '';
  view.webContents.loadURL(url).catch(e => {
    navigationError = e.message;
    sendStatus();
  });
}
async function checkDrm() {
  if (!view || view.webContents.isDestroyed()) return;
  const target = validUrl(view.webContents.getURL());
  if (!target || !target.startsWith('https:')) {
    return { error: 'Öffne zuerst eine HTTPS-Seite, um Widevine zu prüfen.' };
  }
  return await view.webContents.executeJavaScript(`(async () => {
    const v = document.createElement('video');
    const can = type => v.canPlayType(type) || 'nein';
    const result = {
      h264: can('video/mp4; codecs="avc1.42E01E"'),
      aac: can('audio/mp4; codecs="mp4a.40.2"'),
      widevine: 'noch nicht geprüft'
    };
    try {
      if (!navigator.requestMediaKeySystemAccess) throw new Error('EME API fehlt');
      const access = await navigator.requestMediaKeySystemAccess('com.widevine.alpha', [{
        initDataTypes: ['cenc'],
        videoCapabilities: [{ contentType: 'video/mp4; codecs="avc1.42E01E"' }]
      }]);
      result.widevine = access.keySystem;
    } catch (err) { result.widevine = String(err.name || 'Error') + ': ' + String(err.message || ''); }
    return result;
  })()`, true);
}
async function create() {
  win = new BrowserWindow({
    width: 1280, height: 830, minWidth: 800, minHeight: 530,
    backgroundColor: '#11191d',
    title: 'Vaultie – DRM-Test (kein Produktivbrowser)',
    webPreferences: { preload: path.join(__dirname, 'preload.js'), contextIsolation: true, nodeIntegration: false, sandbox: true }
  });
  const profile = session.fromPartition('persist:vaultie-drm-prototype');
  view = new WebContentsView({
    webPreferences: { session: profile, contextIsolation: true, nodeIntegration: false, sandbox: true }
  });
  view.setBackgroundColor('#11191d');
  win.contentView.addChildView(view);
  win.on('resize', setBounds);
  win.on('closed', () => { view = null; win = null; uiReady = false; });
  view.webContents.on('did-start-loading', sendStatus);
  view.webContents.on('did-stop-loading', sendStatus);
  view.webContents.on('did-navigate', sendStatus);
  view.webContents.on('did-navigate-in-page', sendStatus);
  view.webContents.on('page-title-updated', sendStatus);
  view.webContents.on('did-fail-load', (_e, code, description, url, isMainFrame) => {
    if (isMainFrame && code !== -3) { navigationError = description + ' (' + code + ')'; sendStatus(); }
  });
  view.webContents.on('will-navigate', (event, url) => {
    if (!validUrl(url)) event.preventDefault();
  });
  view.webContents.setWindowOpenHandler(({ url }) => {
    if (validUrl(url)) navigate(url);
    return { action: 'deny' };
  });
  await win.loadFile(path.join(__dirname, 'toolbar.html'));
  uiReady = true;
  setBounds();
  navigate(START_PAGE);
  sendStatus();
}
ipcMain.handle('vaultie:command', async (event, cmd, arg) => {
  if (!win || event.sender !== win.webContents || !view) return null;
  switch (cmd) {
    case 'navigate': navigate(String(arg || '')); break;
    case 'back': if (view.webContents.canGoBack()) view.webContents.goBack(); break;
    case 'forward': if (view.webContents.canGoForward()) view.webContents.goForward(); break;
    case 'reload': view.webContents.reload(); break;
    case 'home': navigate(START_PAGE); break;
    case 'drm': {
      let timer;
      try {
        return await Promise.race([
          checkDrm(),
          new Promise(resolve => {
            timer = setTimeout(() => resolve({ error: 'Zeitlimit nach 15 Sekunden. Widevine oder die Webseite antwortet nicht.' }), 15000);
          })
        ]);
      } catch (err) {
        return { error: String(err?.message || err) };
      } finally {
        clearTimeout(timer);
      }
    }
    case 'vmp': await shell.openExternal('https://github.com/castlabs/electron-releases/wiki/vmp'); break;
    default: return null;
  }
  sendStatus();
  return null;
});
app.whenReady().then(async () => {
  try {
    // In ECS the CDM component installer must be ready before creating the window.
    await components.whenReady();
    widevineStatus = JSON.stringify(components.status());
  } catch (err) {
    widevineStatus = 'CDM-Installation fehlgeschlagen: ' + String(err.message || err);
  }
  await create();
}).catch(err => {
  console.error('DRM prototype startup failure', err);
  app.quit();
});
app.on('window-all-closed', () => app.quit());
