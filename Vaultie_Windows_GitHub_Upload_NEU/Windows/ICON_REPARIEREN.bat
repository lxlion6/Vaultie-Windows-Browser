@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0ICON_REPARIEREN.ps1"
if errorlevel 1 (echo. & echo FEHLER: Bitte die Meldung oben lesen.)
pause
