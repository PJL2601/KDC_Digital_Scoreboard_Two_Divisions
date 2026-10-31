@echo off
echo KDC Digital Scoreboard - Windows quick start
if not exist .venv (
  py -m venv .venv
)
call .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
echo.
echo Before starting, set FLASK_SECRET_KEY and ADMIN_SETUP_CODE in PowerShell.
echo Example:
echo   $env:FLASK_SECRET_KEY="your-long-random-secret"
echo   $env:ADMIN_SETUP_CODE="your-private-setup-code"
echo   $env:PUBLIC_BASE_URL="http://127.0.0.1:5000"
echo Then run: python app.py
pause
