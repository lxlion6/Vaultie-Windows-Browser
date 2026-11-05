# Vaultie 0.4.0: geringerer Ressourcenverbrauch ohne Designänderung

Basis ist die von Florian vollständig funktionsfähig bestätigte Version 0.3.0 mit unveränderter castLabs-Engine.

- Wiederhergestellte Tabs erscheinen sofort in der Tab-Leiste. Ihre Webseiten werden erst beim Auswählen geladen; die zuvor aktive Seite wird direkt geladen. Bereits geöffnete Tabs bleiben mit ihrem Zustand und ihren Hintergrundverbindungen erhalten. Es gibt kein automatisches Entladen von Chats, Formularen oder Streams.
- Unsichtbare Ansichten werden explizit ausgeblendet. Nur die sichtbare Ansicht wird bei Fensteränderungen neu positioniert. Standardmäßige Chromium-Hintergrunddrosselung bleibt eingeschaltet.
- Statusereignisse werden zusammengefasst. Die Oberfläche ersetzt die Tab-Leiste nicht mehr bei jedem Downloadfortschritt oder blockierten Request. Unveränderte Berichte/Downloadlisten werden nicht erneut aufgebaut.
- Vollständiger Verlauf und Schutzbericht werden nur bei Bedarf zur Oberfläche übertragen. Benutzeraktionen erhalten weiterhin direkt den aktualisierten Zustand.
- Bereits eingelesene Startseitenvorlage wird wiederverwendet. Netzwerkereignisse finden ihre Tab-Zuordnung über eine Map statt über neue Arrays bei jedem Request.

## Gemessener Vergleich

Isolierte Linux-ECS-Läufe, gleiche Engine und Startseite, kein externes Netz für die Testseiten, ein aktiver und zwölf wiederhergestellte Startseiten-Tabs. Je Lauf drei Sekunden Einschwingzeit und zwei Sekunden CPU-Messintervall. Reproduzierbarer Test: `test/performance.cjs`.

| Messwert | 0.3.0 | 0.4.0 |
|---|---:|---:|
| Sichtbare Tab-Einträge | 13 | 13 |
| Geladene WebContentsViews | 13 | 1 |
| Gemeldete App-Prozesse | 17 | 5 |
| Summe Prozess-Working-Sets | 1.554,58 MiB | 482,63 MiB |
| CPU im kurzen Leerlauffenster | 0,055 % | 0,111 % |

Die Working-Set-Summe sank in diesem Szenario um 68,95 %. Gemeinsame Speicherseiten können in den Prozesswerten mehrfach gezählt werden; das ist keine Messung des einzigartigen physischen RAM. Es ist keine pauschale Einsparungszusage für Windows oder für dreizehn bereits geladene Webseiten. Die kurzen CPU-Werte belegen keine Verbesserung im Leerlauf. Für aktive Webseiten und Medien hängt der Verbrauch weiterhin von deren Inhalt ab.

Bildvergleich: Fensteroberfläche und sichtbare Startseite waren vor/nach der Änderung pixelgleich (identische Aufnahmebedingungen, jeweils 780 Pixel breit).

Regressionen: bisherige Funktionsprüfungen; zusätzliche Prüfung für unveränderte Tab-DOM-Elemente und Teilzustände; echter ECS-Test für verzögertes Laden, anschließendes Öffnen sowie Erhalt von JavaScript-Zustand beim Tabwechsel. Windows-CI prüft Funktionen und erzeugt den Installer.
