@echo off
cd /d "%~dp0"
set "PY=%LOCALAPPDATA%\PB-Build\venv\Scripts\python.exe"
if not exist "%PY%" (
  echo Bitte zuerst INSTALLIEREN.bat ausfuehren.
  pause
  exit /b 1
)
"%PY%" "%~dp0browser.py"
if errorlevel 1 pause
