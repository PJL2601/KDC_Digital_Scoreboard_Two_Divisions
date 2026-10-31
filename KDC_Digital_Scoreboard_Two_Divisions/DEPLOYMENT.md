# Deploying the Boys and Girls scoreboards separately

Deploy the **same code twice** as two separate services/sites, each with its own settings.
Example addresses only — nothing is hosted for you:

* Boys → `https://boys.example.com`
* Girls → `https://girls.example.com`

## Settings per deployment

| Setting | Boys service | Girls service |
|---|---|---|
| `KDC_DIVISION` | `boys` | `girls` |
| Database | `BOYS_DATABASE_URL` (or SQLite `kdc_boys.db`) | `GIRLS_DATABASE_URL` (or SQLite `kdc_girls.db`) |
| `FLASK_SECRET_KEY` | long random value A | a **different** long random value B |
| `ADMIN_SETUP_CODE` | its own code | its own code |
| `PUBLIC_BASE_URL` | `https://boys.example.com` | `https://girls.example.com` |
| `COOKIE_SECURE` | `1` | `1` |

Generate a secret: `python -c "import secrets;print(secrets.token_urlsafe(48))"`.
Ready-made templates: `.env.boys.example`, `.env.girls.example` (copy the values into your host's environment-variable screen).

* **Start command:** `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2`
* **Install:** `pip install -r requirements.txt` (add `-r requirements-postgres.txt` for PostgreSQL)
* **Health check:** `/health` returns `{"status":"ok","division":"boys"}` — use it to confirm each site is the division you expect.
* Use HTTPS. QR codes and host links are built from `PUBLIC_BASE_URL`, so each site's QR codes point to its own address. After deploying, open **Admin → Host QR codes** on each site and check the link shown under each host.

## Option 1 — SQLite (simplest; needs a persistent disk)
Set `KDC_DB_DIR` to a folder on a **persistent volume** (hosts with ephemeral disks lose SQLite files on every restart).
Include `original_backup/kdc_scoreboard.db` and `data/KDC.xlsx` in the deployed files and set `KDC_AUTO_IMPORT=1`:
on first start the app copies the original database into the division database and imports that division's children.
(`.gitignore` excludes those two files from git; deploy from the ZIP or a private repo with those lines removed, or upload the prepared `kdc_boys.db` / `kdc_girls.db` to the volume.)

## Option 2 — PostgreSQL (recommended for a public event)
1. Create **two separate databases** (e.g. `kdc_boys`, `kdc_girls`) and put each URL in its own service (`BOYS_DATABASE_URL`, `GIRLS_DATABASE_URL`). `postgres://` URLs are accepted.
2. Run once per division from a shell that has the project files and that service's environment variables (or from your own PC with the URL set):
   ```
   pip install -r requirements-postgres.txt
   python migrate_legacy.py --division boys      # copies the original records into the empty Boys database
   python import_participants.py --division boys
   ```
   and the same with `girls` (with `GIRLS_DATABASE_URL`). `migrate_legacy.py` refuses to write into a database that already contains data.
3. Start the services.

> The PostgreSQL path was verified only through its code path on SQLite (see TEST_REPORT.md); it was **not** run against a live PostgreSQL server here. Do a trial on a scratch database first.

## Keeping the divisions apart (built-in guards)
* The app stores its division inside each database and refuses to start on the other division's database.
* `DATABASE_URL` is ignored when `KDC_DIVISION` is set, so a stray shared variable cannot merge the data.
* Different `FLASK_SECRET_KEY`s mean a login cookie from one site is worthless on the other; cookie names also differ.

## Checklist
- [ ] Two services, each with its own `KDC_DIVISION`, database, secret key, setup code, `PUBLIC_BASE_URL`
- [ ] HTTPS + `COOKIE_SECURE=1`
- [ ] `/health` shows the right division on each site
- [ ] Admin password changed (`reset_admin.py boys` / `girls`)
- [ ] Participant counts: Boys 21, Girls 19 (Admin → Participants)
- [ ] Host QR codes downloaded **after** `PUBLIC_BASE_URL` was set
- [ ] Backups of both databases scheduled
