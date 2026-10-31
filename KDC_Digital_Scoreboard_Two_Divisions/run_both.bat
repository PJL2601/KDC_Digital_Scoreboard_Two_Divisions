@echo off
rem Starts the Boys (port 5001) and Girls (port 5002) scoreboards in two windows.
cd /d "%~dp0"
call setup_windows.bat
if errorlevel 1 (
  pause
  exit /b 1
)
start "KDC Boys" cmd /k run_boys.bat
start "KDC Girls" cmd /k run_girls.bat
echo Boys:  http://127.0.0.1:5001
echo Girls: http://127.0.0.1:5002
timeout /t 5 >nul
