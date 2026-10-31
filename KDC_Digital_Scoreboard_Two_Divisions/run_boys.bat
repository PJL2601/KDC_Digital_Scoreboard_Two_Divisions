@echo off
rem ------------------------------------------------------------
rem KDC Boys Scoreboard  ->  http://127.0.0.1:5001
rem Uses its own database: instance\kdc_boys.db
rem ------------------------------------------------------------
setlocal
cd /d "%~dp0"
title KDC Boys Scoreboard (port 5001)

call setup_windows.bat
if errorlevel 1 (
  pause
  exit /b 1
)

set "KDC_DIVISION=boys"
set "PORT=5001"

echo.
echo ============================================================
echo  KDC BOYS scoreboard
echo  Open:   http://127.0.0.1:5001
echo  Admin:  http://127.0.0.1:5001/admin
echo  Stop with Ctrl+C
echo ============================================================
echo.
".venv\Scripts\python.exe" app.py
pause
