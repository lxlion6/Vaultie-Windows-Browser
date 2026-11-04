# Vaultie – isolierter Widevine-Prototyp (Windows x64)

**Kein fertiger Browser und keine Änderung an Vaultie 4.2.** Dieser Prototyp dient ausschließlich dazu, Codecs, Widevine-CDM und VMP bei castLabs Electron for Content Security zu prüfen.

## Quelle und Grenzen
- Offizieller ECS-Code: https://github.com/castlabs/electron-releases
- Verwendet die veröffentlichte stabile Version `v44.9.3+wvcus` (Stand 4. November 2026).
- ECS installiert die Widevine-CDM-Komponente beim ersten Programmstart über den Komponenten-Updater. Eine Internetverbindung ist erforderlich.
- Die veröffentlichten ECS-Binaries sind nur für Entwicklungszwecke VMP-signiert. **Prime Video / Netflix können sie deshalb ablehnen.** Der produktive VMP-Signaturdienst EVS erfordert Registrierung: https://github.com/castlabs/electron-releases/wiki/EVS
- Video/DRM-Prüfung zeigt nur Codec-/EME-Verfügbarkeit. **Sie ersetzt keinen echten Wiedergabetest**.
- Keine Passwortmigration und kein Ersatz für den bestehenden Vaultie-Browser.
- Ungeprüfte Streamingdienste und ungetestete UI dürfen nicht als funktionsfähig veröffentlicht werden.

## Durchführung
Unter Windows 11 mit Node.js 22 oder neuer:
```powershell
npm install
npm run check
npm start
```
Die Shaka-Demoseite öffnet sich. Dort kann DRM-Testmaterial abgespielt werden. Die Schaltfläche „Video/DRM prüfen“ testet H.264/AAC und den EME-Zugriff auf `com.widevine.alpha` im Kontext einer HTTPS-Seite.

## Windows-Paket (nur interner Test)
```powershell
npm run package
```
Der Ausgabeordner liegt unter `output/win-unpacked` (genauer Name abhängig von Builder-Version und Plattform). **Nicht als Produktivinstaller veröffentlichen**.

## Freigabekriterien
1. H.264/AAC positiv im Diagnosefenster
2. EME/Widevine-Zugang positiv
3. Testclip läuft tatsächlich (Ton und Bild)
4. VMP-Lab bestätigt den geeigneten Status: https://github.com/castlabs/electron-releases/wiki/vmp
5. Erst dann Produktionssignierung/EVS und Prime-Video-Test
6. Erst nach allen Tests wird über eine Integration in Vaultie entschieden
