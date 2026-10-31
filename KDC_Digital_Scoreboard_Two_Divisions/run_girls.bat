@echo off
rem ------------------------------------------------------------
rem KDC Girls Scoreboard  ->  http://127.0.0.1:5002
rem Uses its own database: instance\kdc_girls.db
rem ------------------------------------------------------------
setlocal
cd /d "%~dp0"
title KDC Girls Scoreboard (port 5002)

call setup_windows.bat
if errorlevel 1 (
  pause
  exit /b 1
)

set "KDC_DIVISION=girls"
set "PORT=5002"

echo.
echo ============================================================
echo  KDC GIRLS scoreboard
echo  Open:   http://127.0.0.1:5002
echo  Admin:  http://127.0.0.1:5002/admin
echo  Stop with Ctrl+C
echo ============================================================
echo.
".venv\Scripts\python.exe" app.py
pause
