"""Lightweight smoke test: routes + database initialisation for ONE division.

    set KDC_DIVISION=boys   (or girls; leave unset for the original single mode)
    python smoke_test.py

It only reads the configured database (and creates missing tables), so run it
against a copy if you want to be extra careful. The full automated suite is
in tests/test_divisions.py.
"""
import os
os.environ.setdefault("FLASK_SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("ADMIN_SETUP_CODE", "test-setup-code")
from app import app, db, Game, DIVISION

with app.app_context():
    assert Game.query.count() in (0, 8, 9)
client = app.test_client()
assert client.get("/").status_code == 200
assert client.get("/scoreboard").status_code == 200
data = client.get("/api/scoreboard")
assert data.status_code == 200
assert data.json["division"] == DIVISION
assert "individuals" in data.json
print(f"Smoke test passed ({DIVISION or 'single/original mode'}): home, scoreboard, API and database initialization.")
