# Vaultie 4.2 → castLabs: Funktionsübernahme

Stand: 4. November 2026. Basis: development/vaultie-castlabs-browser.
Die castLabs-Version v44.9.3+wvcus bleibt erhalten. Florian bestätigt den erfolgreichen DRM-Prototyp mit Bild und Ton. Die Qt-Version 4.2 bleibt unverändert.

## Ergänzt im Quellcode

- Gemeinsamer lokaler TCP-Proxy: 3–25 Mbit/s für Upload und Download aller Tabs, ein-/ausschaltbar, Aus = direkte Verbindung. Keine HTTPS-Entschlüsselung. QUIC deaktiviert; WebRTC nutzt keine nichtproxierten UDP-Verbindungen. Einzelne Echtzeitdienste können im Proxybetrieb eingeschränkt sein.
- Gleiche 26 Standard-Domainfilter wie 4.2, Import von HOSTS, Domainlisten und einfachen `||domain^`-Regeln (maximal 12 MB). Keine komplexen/kosmetischen EasyList-Regeln. Schutzbericht und Trackingbereinigung bei GET-Hauptnavigationen.
- Fingerprinting-Code aus 4.2 mit neuem Sitzungsschlüssel; bisherige Amazon-/Prime-Ausnahmen erhalten. Schutz ist eine Verringerung von Merkmalen, keine Garantie gegen Wiedererkennung.
- Drittanbieter-Cookies: Domainabgleich über Public Suffix List einschließlich privater Suffixe; Cookie-/Set-Cookie-Headerfilter, Document-Cookie-Sperre für fremde Frames. Amazon-/Prime-Ausnahmen wie bisher.
- Flüchtige Standardsitzung. Dauerhafte Website-Sitzung und Tab-Wiederherstellung optional ab nächstem Start. Beim Deaktivieren wird das bisher aktive persistente Profil beim Beenden bereinigt.
- Lokaler Verlauf, Suche, einzelnes/gesamtes Löschen, optionales Löschen beim Beenden; maximal 2.000 Einträge.
- Lesezeichen bearbeiten, suchen, löschen, auf Startseite anheften. Original-Startseitengrafik und HTML bleiben erhalten; Schnellwahl entfernen/zurücksetzen. Falsche frühere Aussage „Verlauf wird niemals gespeichert“ korrigiert.
- Lokale verschlüsselte Logins: Formular übernehmen, ausdrücklich speichern, ausfüllen, verwalten/löschen. Unter Windows optionaler Import der bisherigen DPAPI-Datei über Dateiauswahl; Quelldatei bleibt unverändert. Keine automatische Passwortübernahme, keine Klartextdatei.
- Downloads mit eindeutigem Zielnamen, Fortschritt, Pause/Fortsetzen/Abbrechen, Öffnen/Ordner anzeigen; Zielordner auswählbar.
- Speicherprüfung jede Minute: Zielbudget 5 GB, Cachebereinigung ab 3,8 GB, Downloads ausgenommen. Keine automatische Löschung von Passwörtern/Lesezeichen/Website-Daten. 5 GB sind wie bisher keine garantierte harte Grenze.
- Updateprüfung im getrennten castLabs-Releasekanal (`castlabs-v…`), ohne automatische Installation. Keine Rückkehr zur Qt-Engine durch Updates.
- Tab-Umsortierung, Tastenkürzel auch bei Fokus auf Webseiten, lokaler Datenordner, VPN-Links und Sicherheitshinweise.
- Windows-Installer mit Desktopverknüpfung „Vaultie Streaming“; separate Entwicklungs-App-ID schützt den bisherigen Browser.

## Prüfung und verbleibende Grenzen

`npm run check` und `npm test`: Syntax-, Modul-, Netzwerk- und DOM-Tests. Netzwerkprüfung umfasst parallelen Upload/Download unter gemeinsamem Limit und einen binären CONNECT-Tunnel. Windows-CI führt zusätzlich einen echten Electron-Start mit UI-Brücke, privater Sitzung, Proxy-Umschaltung, lokaler Webseite, Lesezeichen, Startseite und Verlauf durch und erstellt danach das Windows-Paket.

Neun lokale automatisierte Tests bestanden. Echter ECS-Starttest unter Linux ebenfalls bestanden, einschließlich Document-Cookie-Sperre in einem fremden iframe. Ein Windows-CI-Lauf wurde durch die automatische Freigabeprüfung vor dem öffentlichen GitHub-Upload blockiert. Windows-Binärpaket wird lokal erstellt; ein Windows-Lauf ist damit nicht nachgewiesen.

Ein erfolgreicher CI-Lauf ersetzt keinen visuellen 1:1-Abgleich mit Florians Bildschirm. Der Windows-DPAPI-Import benötigt eine echte alte Passwortdatei des gleichen Windows-Benutzers und muss vor Ort geprüft werden. Der bestätigte DRM-Test bezieht sich auf den vorherigen Prototyp; Streaming in der integrierten Fassung muss anschließend erneut geprüft werden.

„Lokale Widevine-Datei wählen“ aus Qt wird nicht übernommen: In ECS übernimmt der vorhandene Komponenten-Updater die CDM-Verwaltung. Die funktionierende Engine wird nicht durch eine fremde DLL ersetzt.
