VAULTIE - Setup-EXE fuer Windows erstellen
============================================

DAS ERGEBNIS nach einem erfolgreichen GitHub-Actions-Build:
  Vaultie-Setup.exe

Die EXE ist ein einzelnes Installationsprogramm fuer Windows 10/11 x64.
Nach dem Start installiert der Wizard alle benoetigten Qt/Python-Komponenten
zusammen mit dem Browser. Beim Empfaenger sind KEINE Python-, pip- oder
Qt-Nachinstallationen und keine Konsolenbefehle notwendig.

SO KANNST DU DIE EXE KOSTENLOS ERSTELLEN:
1. Dieses Paket entpacken.
2. GitHub-Repository oeffnen und diese Dateien ins HAUPTVERZEICHNIS laden:
   - Windows/ (Ordner mit browser.py, assets/, requirements.txt, Vaultie.iss)
   - .github/workflows/windows-setup.yml
3. Auf GitHub Actions -> "Vaultie Windows Setup EXE bauen" -> Run workflow.
4. Nach erfolgreichem Build unter Artifacts "Vaultie-Windows-Installer" laden.
5. ZIP des GitHub-Artifacts entpacken; die Vaultie-Setup.exe an Freunde weitergeben.

WICHTIG:
- Die Setup-EXE ist nicht code-signiert. Windows SmartScreen kann deshalb
  eine Warnung zeigen. Der Nutzer muss selbst entscheiden, ob er vertraut.
- Das Setup kann keine vollstaendige Virenfreiheit oder Sicherheitspruefung
  der Browser-Engine garantieren.
- Die Browserdaten bleiben im bestehenden lokalen Profil, nicht in einer Cloud.
- Das Windows-Setup wurde hier nur auf Konfiguration und Python-Syntax geprueft,
  nicht auf einem Windows-Rechner kompiliert oder ausgefuehrt.
- Zur Aktualisierung kuenftig nur die Setup-EXE einer neueren Version starten;
  die lokalen Lesezeichen und Einstellungen werden nicht geloescht.
- Deinstallieren: Windows Einstellungen -> Apps -> Vaultie -> Deinstallieren.
- Die Datei ist ein Installer, keine portable Anwendung.
