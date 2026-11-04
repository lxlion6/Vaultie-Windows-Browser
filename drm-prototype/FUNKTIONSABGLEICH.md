# Vaultie 4.2 – verbindlicher Funktionsabgleich zur castLabs-Entwicklungsfassung

Quelle: Vaultie_Windows_Setup_Buildpaket/Windows/browser.py, bandwidth_proxy.py, storage_manager.py, credentials.py, assets/fingerprint.js und assets/startseite.html.
Stand: 04.11.2026. [vorhanden] bedeutet ausschließlich im Entwicklungsquellcode umgesetzt, nicht praktisch auf Windows nachgewiesen.
Diese Datei ist eine Abnahmeliste, keine Zusicherung der vollständigen Funktionsfähigkeit.

| Funktion | Vaultie 4.2 | castLabs-Entwicklung | Freigabekriterium |
|---|---|---|---|
| Dunkles Türkis-Design, Tabs, Navigationsleiste | ja | angenähert, nicht pixelgenau abgenommen | 1:1 Sichtvergleich |
| Original-Startseite mit Grafik und Suchfeld | ja | originale HTML-Datei eingebunden | Start, Links, Schnellwahl prüfen |
| Tabs schließen, öffnen, wechseln, Tastenkürzel | ja | vorhanden (Code) | Klick- und Tastaturtest |
| Videocodecs H.264/AAC | in 4.2 nicht verfügbar | castLabs-Engine, positiver Prototyptest | Bild/Ton in Gesamtbrowser |
| Widevine | in 4.2 nicht funktionsfähig nachgewiesen | positiver Prototyptest | DRM-Medienwiedergabe |
| Werbeblocker mit einfacher Domainliste | ja | einfache feste Liste implementiert | Domainfilter wie 4.2 |
| Externe HOSTS-/Adblock-Domainfilter importieren | ja | FEHLT | 12-MB-Begrenzung, gültige Formate |
| Werbe-/Trackingzähler und Bericht | ja | Zähler im Code, Bericht FEHLT | UI zeigt korrekte Werte |
| Linktracking-Parameter entfernen | ja | vorhanden (Code) | Queryparameter-Tests |
| Bandbreitenbegrenzer 3–25 Mbit/s | ja, lokaler Proxy, Gesamtlimit Upload + Download | FEHLT | globales Limit bei mehreren Tabs, Neustart, Aus=Direkt |
| Browser-Fingerprinting-Schutz | ja, lokales JavaScript | FEHLT | Schutzwirkung und Kompatibilität testen |
| Drittanbieter-Cookies deaktivieren | ja, schaltbar | FEHLT | Cookies tatsächlich blockiert |
| Standardmäßig flüchtige Cookies und Sitzungen | ja | FEHLT (castLabs-Profil persistent) | Standard ohne Persistenz, opt-in |
| Optional Sitzungen nach Neustart behalten | ja | nur Tab-URLs wiederherstellbar | Cookie-Persistenz nach Opt-in |
| Passwortspeicher lokal verschlüsselt | ja, DPAPI | neuer verschlüsselter Speicher | Verschlüsselung + erfolgreiche Anmeldung testen |
| Bestehende gespeicherte Passwörter übernehmen | ja, bisherige Datei | FEHLT | nach ausdrücklicher Zustimmung und Sicherheitsprüfung |
| Passwörter aus Formular speichern/ausfüllen | ja | manuelle Eingabe/Speicherung, Autofill im Code | echte Login-Tests |
| Lesezeichen speichern und verwalten | ja | speichern/öffnen/löschen | Test und vorhandene Daten erhalten |
| Lesezeichen bearbeiten, suchen, Startseiten-Pins | ja | teilweise; Bearbeiten/Pins FEHLEN | vollständiger Funktionsvergleich |
| Verlauf lokal mit Suche | ja | FEHLT | lokal protokollieren, durchsuchen, löschen |
| Verlauf beim Beenden löschen | ja | FEHLT | Löschtest |
| Downloads, Fortschritt, Zielordner | ja | einfache Downloads implementiert | Mehrfachdownloads, Konfliktvermeidung |
| Speicherbudget 5 GB, Cachebereinigung | ja | FEHLT | StorageBudget-Verhalten erhalten, Nutzerdaten schützen |
| VPN-Empfehlungen Mullvad/NordVPN | ja | vorhanden (Code) | Links korrekt |
| Update-Abfrage | ja | FEHLT | sichere Versionserkennung |
| Cookies/Cache löschen | ja | vorhanden (Code) | Nachweis ohne Passwort-/Lesezeichenverlust |
| Sicherheitshinweise und Einstellungen | ja | teilweise | alle Schaltflächen funktionsfähig |

**Verbindlich:** Fehlende Einträge dürfen nicht als umgesetzt oder funktionsfähig bezeichnet werden. Keine Freigabe als regulärer Vaultie-Browser vor Vergleichstests und Abschluss. Keine Änderung der regulären 4.2-Version bis dahin.
