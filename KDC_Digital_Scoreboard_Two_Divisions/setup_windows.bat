@echo off
rem ------------------------------------------------------------
rem KDC Digital Scoreboard - one-time / repeatable Windows setup
rem   * creates the .venv and installs requirements (first run only)
rem   * creates .env.boys / .env.girls with random secrets (if missing)
rem   * imports the children from data\KDC.xlsx (safe to repeat)
rem Called automatically by run_boys.bat and run_girls.bat.
rem ------------------------------------------------------------
cd /d "%~dp0"
set "PY=.venv\Scripts\python.exe"

if not exist "%PY%" (
  echo [setup] Creating virtual environment...
  where py >nul 2>nul
  if not errorlevel 1 (
    py -3 -m venv .venv
  ) else (
    python -m venv .venv
  )
)
if not exist "%PY%" goto :nopython

if not exist ".venv\.kdc_deps_ok" (
  echo [setup] Installing requirements ^(first run only^)...
  "%PY%" -m pip install --upgrade pip
  "%PY%" -m pip install -r requirements.txt
  if errorlevel 1 goto :piperror
  echo ok> ".venv\.kdc_deps_ok"
)

"%PY%" make_env.py boys girls
if errorlevel 1 exit /b 1

if exist "data\KDC.xlsx" (
  "%PY%" import_participants.py
  if errorlevel 1 exit /b 1
)
exit /b 0

:nopython
echo.
echo ERROR: Python 3.10 or newer was not found.
echo Install it from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^) and run this again.
exit /b 1

:piperror
echo.
echo ERROR: could not install the requirements. Check your internet connection and try again.
exit /b 1
