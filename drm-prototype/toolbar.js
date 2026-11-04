'use strict';
const $ = id => document.getElementById(id);
function run(name, arg) { return window.vaultie.command(name, arg).catch(err => { $('status').textContent = 'Fehler: ' + err.message; }); }
for (const name of ['back', 'forward', 'reload', 'home']) $(name).addEventListener('click', () => run(name));
function go() { run('navigate', $('address').value); }
$('go').addEventListener('click', go);
$('address').addEventListener('keydown', e => { if (e.key === 'Enter') go(); });
$('diagnostics-close').addEventListener('click', () => $('diagnostics').close());
$('diagnostics').addEventListener('close', () => { void run('panel', false); });
$('diagnose').addEventListener('click', async () => {
  const dlg = $('diagnostics');
  const result = $('diagnostics-result');
  result.textContent = 'Prüfe H.264, AAC und Widevine.\nDie Abfrage wird nach spätestens 15 Sekunden beendet.';
  try {
    await window.vaultie.command('panel', true);
  } catch (err) {
    $('status').textContent = 'Diagnosefenster konnte nicht vorbereitet werden: ' + String(err?.message || err);
    return;
  }
  if (!dlg.open) dlg.showModal();
  $('diagnose').disabled = true;
  try {
    const report = await window.vaultie.command('drm');
    if (!report) throw new Error('Keine Antwort von der Browser-Engine.');
    if (report.error) {
      result.textContent = 'Prüfung nicht abgeschlossen:\n' + report.error;
    } else {
      result.textContent = 'H.264: ' + (report.h264 || 'nicht verfügbar') +
        '\nAAC: ' + (report.aac || 'nicht verfügbar') +
        '\nWidevine: ' + (report.widevine || 'nicht verfügbar') +
        '\n\nHinweis: Eine positive Prüfung garantiert nicht, dass Prime Video Filme abspielt.';
    }
  } catch (err) {
    result.textContent = 'Prüfung fehlgeschlagen:\n' + String(err?.message || err);
  } finally {
    $('diagnose').disabled = false;
  }
});
window.vaultie.onStatus(s => {
  if (document.activeElement !== $('address')) $('address').value = s.url || '';
  $('back').disabled = !s.canBack;
  $('forward').disabled = !s.canForward;
  $('status').textContent = s.error || ((s.loading ? 'Lädt …' : 'Bereit') + ' | CDM: ' + s.widevine);
});
