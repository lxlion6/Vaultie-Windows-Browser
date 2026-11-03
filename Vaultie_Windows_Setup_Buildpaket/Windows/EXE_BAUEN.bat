@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Bitte zuerst STARTEN.bat ausfuehren.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --windowed --name Vaultie --icon "%~dp0assets\vaultie.ico" --add-data "%~dp0assets;assets" --collect-all PySide6.QtWebEngineCore --collect-all PySide6.QtWebEngineWidgets browser.py
if errorlevel 1 (
  echo EXE-Bau fehlgeschlagen.
  pause
  exit /b 1
)
echo Programmordner: dist\Vaultie\
pause
