'use strict';
const $ = id => document.getElementById(id);
function run(name, arg) { return window.vaultie.command(name, arg).catch(err => { $('status').textContent = 'Fehler: ' + err.message; }); }
for (const name of ['back', 'forward', 'reload', 'home']) $(name).addEventListener('click', () => run(name));
function go() { run('navigate', $('address').value); }
$('go').addEventListener('click', go);
$('address').addEventListener('keydown', e => { if (e.key === 'Enter') go(); });
$('diagnose').addEventListener('click', async () => {
  $('status').textContent = 'Video- und Widevine-Diagnose läuft auf der geöffneten HTTPS-Seite …';
  const report = await run('drm');
  if (report) $('status').textContent = 'H.264: ' + report.h264 + ' | AAC: ' + report.aac + ' | Widevine: ' + report.widevine + (report.error ? ' | ' + report.error : '');
});
window.vaultie.onStatus(s => {
  if (document.activeElement !== $('address')) $('address').value = s.url || '';
  $('back').disabled = !s.canBack;
  $('forward').disabled = !s.canForward;
  $('status').textContent = s.error || ((s.loading ? 'Lädt …' : 'Bereit') + ' | CDM: ' + s.widevine);
});
