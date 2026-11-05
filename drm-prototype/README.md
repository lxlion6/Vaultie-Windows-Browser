# Vaultie mit castLabs – Ressourcenoptimierung 0.4.0

Windows 11 x64; Node.js 22 für Entwicklung/Build. Engine unverändert: castLabs ECS `v44.9.3+wvcus`.
Der bisherige DRM-Prototyp wurde von Florian mit Bild und Ton erfolgreich getestet. Diese Fassung ergänzt die bisherigen Vaultie-Funktionen; Details und Prüfgrenzen: [FUNKTIONSABGLEICH.md](FUNKTIONSABGLEICH.md).

## Entwicklung

```powershell
npm ci
node node_modules/electron/install.js
npm run check
npm test
npm start
```

## Windows-Installer

```powershell
npm run package
```

Ausgabe: `output/Vaultie-castLabs-Setup-0.4.0.exe`. Der Installer legt die Verknüpfung **Vaultie Streaming** an. Die reguläre Qt-Version bleibt unverändert. GitHub Actions baut auf dem Entwicklungszweig ein herunterladbares Windows-Artefakt nach Tests.

Website-Sitzungen sind standardmäßig flüchtig; dauerhafte Anmeldungen lassen sich in den Einstellungen einschalten (wirksam ab Neustart). Lesezeichen, Verlauf und ausdrücklich gespeicherte Logins bleiben lokal. Der alte Passwortspeicher lässt sich unter „Zugangsdaten“ über Dateiauswahl importieren. Es werden keine Passwörter automatisch importiert oder als Klartextdatei gespeichert.

Quellen: https://github.com/castlabs/electron-releases und https://www.electronjs.org/docs/latest/api/session . ECS verwaltet die Widevine-Komponente wie im erfolgreichen Prototyp. Der VMP-/Dienstestatus kann weiterhin vom Streaminganbieter abhängen; ein Codec-/EME-Test ersetzt keinen realen Wiedergabetest in der integrierten Fassung.

Die Ansicht bleibt unverändert. Wiederhergestellte Hintergrund-Tabs laden erst bei Auswahl; bereits geladene Seiten bleiben aktiv. Messbedingungen und Grenzen: [PERFORMANCE.md](PERFORMANCE.md).
