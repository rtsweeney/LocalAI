@echo off
rem Double-click this file to open AI Home, the control panel for everything in this folder.
rem It needs Python. If Python is missing, this installs it first using Windows own installer.
cd /d "%~dp0"
python -c "import sys" >nul 2>nul
if errorlevel 1 (
  echo AI Home needs Python, which is not installed yet. Installing it now...
  echo Approve the Windows permission prompt if one appears.
  winget install --exact --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
  echo.
  echo Done. Close this window, then double-click "Start AI Home.bat" again.
  pause
  exit /b
)
python home\home.py
if errorlevel 1 pause
