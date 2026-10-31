"""Create .env.boys / .env.girls with random secrets if they do not exist yet.

    python make_env.py boys girls

Each division gets its OWN secret key and setup code. Edit PUBLIC_BASE_URL in
the file if phones on your Wi-Fi must scan the host QR codes (use this
computer's LAN address, e.g. http://192.168.1.20:5001).
"""
import os
import secrets
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PORTS = {"boys": 5001, "girls": 5002}

for division in sys.argv[1:] or list(PORTS):
    if division not in PORTS:
        sys.exit(f"Unknown division: {division}")
    path = os.path.join(HERE, f".env.{division}")
    if os.path.exists(path):
        continue
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(
            f"# Settings for the {division.upper()} scoreboard only. Never share this file.\n"
            f"FLASK_SECRET_KEY={secrets.token_urlsafe(48)}\n"
            f"ADMIN_SETUP_CODE={secrets.token_urlsafe(12)}\n"
            f"# Address that QR codes and host links point to:\n"
            f"PUBLIC_BASE_URL=http://127.0.0.1:{PORTS[division]}\n"
            f"COOKIE_SECURE=0\n"
        )
    print(f"[setup] Created .env.{division} (random secret key + setup code).")
