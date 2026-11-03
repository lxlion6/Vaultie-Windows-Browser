@echo off
setlocal
cd /d "%~dp0"
title Vaultie - Einmalige Installation

echo Vaultie wird fuer dieses Windows-Benutzerkonto installiert.
echo Fuer den erstmaligen Build sind Python und Internet erforderlich.
echo.
where py >nul 2>nul
if errorlevel 1 (
  echo FEHLER: Python-Launcher fehlt. Python 3.11 oder 3.12 installieren.
  pause
  exit /b 1
)
rem Kurzer Pfad vermeidet die zuvor aufgetretenen PySide6-Pfadfehler.
set "BUILDROOT=%LOCALAPPDATA%\PB-Build"
if not exist "%BUILDROOT%" mkdir "%BUILDROOT%"
if not exist "%BUILDROOT%\venv\Scripts\python.exe" (
  py -3 -m venv "%BUILDROOT%\venv"
  if errorlevel 1 goto failed
)
"%BUILDROOT%\venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
"%BUILDROOT%\venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --windowed --name Vaultie --icon "%~dp0assets\vaultie.ico" --add-data "%~dp0assets;assets" --distpath "%BUILDROOT%\dist" --workpath "%BUILDROOT%\work" --specpath "%BUILDROOT%" --collect-all PySide6.QtWebEngineCore --collect-all PySide6.QtWebEngineWidgets "%~dp0browser.py"
if errorlevel 1 goto failed
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_windows.ps1" -BuildSource "%BUILDROOT%\dist\Vaultie"
if errorlevel 1 goto failed
echo.
echo FERTIG: Vaultie aktualisiert. Desktop-Symbol kann genutzt werden.
pause
exit /b 0
:failed
echo.
echo FEHLER: Installation nicht abgeschlossen. Bitte Fehlermeldung pruefen.
pause
exit /b 1
