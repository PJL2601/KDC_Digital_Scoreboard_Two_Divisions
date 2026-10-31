# KDC 2026 Digital Scoreboard — Boys & Girls divisions

One Flask application, run as **two independent scoreboards**:

| | Boys | Girls |
|---|---|---|
| Setting | `KDC_DIVISION=boys` | `KDC_DIVISION=girls` |
| SQLite database | `instance/kdc_boys.db` | `instance/kdc_girls.db` |
| PostgreSQL (optional) | `BOYS_DATABASE_URL` | `GIRLS_DATABASE_URL` |
| Local address | http://127.0.0.1:5001 | http://127.0.0.1:5002 |
| Participants imported from | `Boys` sheet of `data/KDC.xlsx` | `Girls` sheet |

Each division has its **own** participants, individual scores, team scores, admin login,
host assignments/QR tokens, leaderboards, secret key, setup code and public URL.
Nothing you do in one can change the other.

Everything from the original app is kept (team scoring, host QR codes, approval workflow,
admin dashboard, public scoreboard, CSV export, audit log). **New:** participants and
**individual scoring** (one score per child per game), an individual leaderboard on the
scoreboard / admin / CSV, and the Boys/Girls split.

Other documents: [DEPLOYMENT.md](DEPLOYMENT.md) · [MIGRATION.md](MIGRATION.md) · [TEST_REPORT.md](TEST_REPORT.md)

---

## Quick start on Windows

1. Install **Python 3.10 or newer** from https://www.python.org/downloads/ — tick **“Add python.exe to PATH”**.
2. Unzip the project (for example to `C:\KDC\`).
3. Double-click **`run_boys.bat`** → Boys scoreboard at http://127.0.0.1:5001
4. Double-click **`run_girls.bat`** → Girls scoreboard at http://127.0.0.1:5002
   (or **`run_both.bat`** to start both in two windows).

The first run automatically: creates a `.venv`, installs the requirements, creates
`.env.boys` / `.env.girls` with random secrets, creates each division's database from your
existing data (see MIGRATION.md) and imports the children from `data\KDC.xlsx`.
Later runs start in seconds. Stop a scoreboard with `Ctrl+C`.

The ZIP already contains ready-made `instance\kdc_boys.db` and `instance\kdc_girls.db`
(migrated + participants imported), so it also works straight away.

**Admin login:** your existing administrator (`kdc_admin`, same password as before) exists in
both divisions. Sign in at `/admin/login` of each site. Change a password with
`.venv\Scripts\python reset_admin.py boys` (or `girls`).

### Using the scoreboards from phones (host QR codes)
`127.0.0.1` on a phone means the phone itself. For hosts scanning QR codes on the event Wi-Fi:

1. Find this PC's address (`ipconfig` → IPv4, e.g. `192.168.1.20`) and allow Python through the Windows firewall when asked.
2. Edit `.env.boys` → `PUBLIC_BASE_URL=http://192.168.1.20:5001`; edit `.env.girls` → `PUBLIC_BASE_URL=http://192.168.1.20:5002`.
3. Restart the `.bat`. In **Admin → Host QR codes** each host link now shows the address it points to, and the downloaded QR code uses it.

---

## Event workflow

1. **Admin → Teams / Host QR codes**: add teams, assign Host 1 and Host 2 for each game, download and print the QR codes (each host gets their own).
2. **Admin → Participants**: the children are already imported. Add a late arrival with *Add child* (name + optional age); deactivate a child who did not come.
3. Hosts scan their QR code. Their page has two forms:
   * **Submit team score** — unchanged: goes to *pending*, the admin approves/rejects, only approved points count.
   * **Score a child** — pick a child and the outcome. **One score per child per game**: after saving, the child disappears from the dropdown, and *both* hosts of that game see the same shared list. Individual scores count immediately.
4. **Admin** can correct or remove an individual score (*Recorded individual scores*), so a mistake can be re-entered. All changes are audit-logged.
5. Project **/scoreboard** on the TV. Use the **Overview** (teams), **Individuals** and **Spotlight** buttons.
6. Export team results (`/results.csv`) and individual results (`/individual-results.csv`) from the admin page.

Individual scores use the same point options as that game's team scoring (Game 8: 15 / 12 / 9 / 5 …). Children with the same total share a rank.

## Participants and the Excel file

`data\KDC.xlsx` has a **Boys** and a **Girls** sheet (`Child Name`, `Gender`, optional `Age` column).

```
.venv\Scripts\python import_participants.py                  (both divisions)
.venv\Scripts\python import_participants.py --division boys
.venv\Scripts\python import_participants.py --file C:\path\KDC.xlsx
```
* Boys sheet → Boys database only; Girls sheet → Girls database only. A row whose gender does not match the division is skipped.
* Names are kept exactly as written (only repeated spaces are tidied). A name already present (case-insensitive) is never duplicated, so you can re-run it safely.

## Settings reference

Set as environment variables, or in `.env.boys` / `.env.girls` / `.env` (real environment variables win; then `.env.<division>`; then `.env`). The `.env.example` files are templates only and are not loaded automatically: copy the appropriate example to `.env` or `.env.boys` / `.env.girls`, then replace sample values. Division-specific files are loaded when `KDC_DIVISION` is selected; the `run_boys.bat` and `run_girls.bat` launchers set it for you. Restart the app after changing settings.
A `BOYS_` / `GIRLS_` prefix (e.g. `GIRLS_FLASK_SECRET_KEY`) overrides the plain name for that division.

| Variable | Meaning |
|---|---|
| `KDC_DIVISION` | `boys` or `girls`. **Unset = original single-scoreboard mode** (uses `DATABASE_URL`, exactly as before) |
| `FLASK_SECRET_KEY` | Long random value, **different per division** |
| `ADMIN_SETUP_CODE` | Setup code for `/setup` (only needed if the database has no admin) |
| `PUBLIC_BASE_URL` | Address of *this* division's site; used by QR codes and host links (default: the address the browser used) |
| `BOYS_DATABASE_URL` / `GIRLS_DATABASE_URL` | Optional PostgreSQL (else SQLite file in `instance/`) |
| `KDC_DB_DIR` | Folder for the SQLite files (default `instance/`) |
| `COOKIE_SECURE=1` | Set behind HTTPS |
| `KDC_AUTO_MIGRATE=0` | Disable the automatic first-start copy of the original database |
| `LEGACY_DATABASE_PATH` | Where the original database is (default `original_backup/kdc_scoreboard.db`) |
| `KDC_AUTO_IMPORT=1`, `PARTICIPANTS_FILE` | Import the Excel list at start-up (for hosts without a shell) |

Safety guards: each database is tagged with its division and the app **refuses to start** if `KDC_DIVISION` does not match
(so Boys can never run on the Girls database); the generic `DATABASE_URL` is **ignored** when `KDC_DIVISION` is set;
each division uses its own session-cookie name so logging into one site never logs you out of the other.

## Project layout

```
app.py                  the application (all routes, models, division logic)
kdc_migrate.py          read-only copy helpers for the original database
migrate_legacy.py       copy the original DB into Boys and/or Girls
import_participants.py  import data\KDC.xlsx
make_env.py             creates .env.boys / .env.girls with random secrets
run_boys.bat / run_girls.bat / run_both.bat / setup_windows.bat
reset_admin.py          reset an admin password:  reset_admin.py boys|girls
smoke_test.py           quick route check
tests/test_divisions.py full automated suite (see TEST_REPORT.md)
original_backup/        the ORIGINAL database, untouched (never written by the app)
data/KDC.xlsx           the participant list
instance/               kdc_boys.db, kdc_girls.db
templates/ static/      pages and styling
```

## Running the tests
```
.venv\Scripts\python tests\test_divisions.py
```
Uses temporary copies; your real databases and the original backup are never written.

## Privacy
The database and Excel file contain children's names. Keep the project in a **private** repository
and never publish the `.db` files (`.gitignore` already excludes them).

## Known limits (unchanged from the original app)
Single administrator per division, QR links are bearer links (keep them private; re-saving a host assignment rotates its token),
and the Flask development server (`app.py`) is for local use — use gunicorn for hosting (see DEPLOYMENT.md).
