# Deploying the KDC Scoreboard on Render (Boys + Girls)

This deploys the **same code twice** as two independent web services, each with
its own PostgreSQL database and its own URL:

| Service    | Division | Database      | Example URL                     |
|------------|----------|---------------|---------------------------------|
| `kdc-boys` | boys     | `kdc-boys-db` | `https://kdc-boys.onrender.com` |
| `kdc-girls`| girls    | `kdc-girls-db`| `https://kdc-girls.onrender.com`|

The admin login is per-division. Because both databases are migrated from the
same original database, both start with the same `kdc_admin` account — so your
admin credentials are automatically identical on both sites.

---

## Step 0 — Put the new files in the right place and push

Your code is nested two folders deep in the repo:

```
<repo root>/
├── render.yaml            <-- MUST be here, at the top level
├── RENDER_DEPLOY.md       <-- this guide (top level is fine)
└── KDC_Digital_Scoreboard_Two_Divisions/
    └── KDC_Digital_Scoreboard_Two_Divisions/
        ├── app.py
        ├── requirements.txt   <-- replace the existing one here
        └── ... (all other project files)
```

- **`render.yaml` → the repo's top level.** Render only detects a Blueprint if
  this file is at the root. It uses `rootDir` to build inside the inner folder,
  so you do **not** move your code.
- **`requirements.txt` → replace the existing one** in the inner
  `.../KDC_Digital_Scoreboard_Two_Divisions/` folder. The only change is
  `psycopg2` → `psycopg2-binary` (plain `psycopg2` needs a compiler + Postgres
  headers and **fails to build on Render**; the `-binary` wheel just works).

Then from the repo root:

```bash
git add render.yaml RENDER_DEPLOY.md
git add KDC_Digital_Scoreboard_Two_Divisions/KDC_Digital_Scoreboard_Two_Divisions/requirements.txt
git commit -m "Add Render blueprint; use psycopg2-binary for Postgres"
git push
```

> Tip: if you'd rather not have the folder-inside-folder, you can move the inner
> files up to the repo root later and delete the `rootDir:` lines from
> `render.yaml`. It's optional — the setup above works as-is.

---

## Step 1 — Create the Blueprint on Render

1. Go to the Render dashboard → **New +** → **Blueprint**.
2. Connect your GitHub account if needed, then pick this repository.
3. Render reads `render.yaml` and shows a plan: **2 databases + 2 web services**.
4. Click **Apply**. Render creates the databases first, then builds and starts
   both services.

The build runs `pip install -r requirements.txt`; the start command is
`gunicorn app:app --bind 0.0.0.0:$PORT --workers 2`. Tables are created
automatically on first boot, so each site comes up with an **empty** database
(you fill it in Step 3).

Check health once both are "Live":

- `https://kdc-boys.onrender.com/health` → `{"division":"boys","status":"ok"}`
- `https://kdc-girls.onrender.com/health` → `{"division":"girls","status":"ok"}`

---

## Step 2 — Set each site's real public URL

Render may append a random suffix to a name that is already taken, so your real
URL might be e.g. `kdc-boys-ab12.onrender.com`. QR codes and host links are
built from `PUBLIC_BASE_URL`, so point it at the real address:

For **each** service → **Environment** → edit `PUBLIC_BASE_URL` to the exact
`https://...onrender.com` shown at the top of that service → **Save Changes**
(the service redeploys). Do this before you hand out any host QR codes.

---

## Step 3 — Migrate your existing data into the two databases

Your source files (`original_backup/kdc_scoreboard.db` and `data/KDC.xlsx`) are
kept out of git on purpose, so the migration runs **from your computer** against
Render's databases. This copies the admin, 9 games, team, host assignments,
scores and audit log into each database, then adds the children (21 Boys / 19
Girls).

**3a. Temporarily allow your computer to reach each database**

For **each** database (`kdc-boys-db`, `kdc-girls-db`) → **Access Control** →
**Add source** → enter your current IP (Render shows a "add my IP" helper), or
`0.0.0.0/0` for a short window → **Save**. Then copy that database's
**External Database URL** (Connect → External).

> Remove this access again at the end of the step — see 3d.

**3b. Prepare your computer (one time)**

Run these from the **inner** project folder — the one that contains `app.py`,
`migrate_legacy.py`, `original_backup/` and `data/`
(`...\KDC_Digital_Scoreboard_Two_Divisions\KDC_Digital_Scoreboard_Two_Divisions`):

```bash
# with the virtual environment active
pip install -r requirements.txt
```

**3c. Run the migration — Boys, then Girls**

Windows PowerShell:

```powershell
$env:BOYS_DATABASE_URL = "<Boys External Database URL>"
python migrate_legacy.py --division boys
python import_participants.py --division boys

$env:GIRLS_DATABASE_URL = "<Girls External Database URL>"
python migrate_legacy.py --division girls
python import_participants.py --division girls
```

macOS/Linux:

```bash
BOYS_DATABASE_URL="<Boys External Database URL>" python migrate_legacy.py --division boys
BOYS_DATABASE_URL="<Boys External Database URL>" python import_participants.py --division boys
GIRLS_DATABASE_URL="<Girls External Database URL>" python migrate_legacy.py --division girls
GIRLS_DATABASE_URL="<Girls External Database URL>" python import_participants.py --division girls
```

`migrate_legacy.py` prints row counts and refuses to touch a database that
already contains data, so run it **before** anyone completes `/setup` on the
live sites. (You won't need `/setup` at all — the admin comes from the original
database.)

**3d. Lock the databases back down**

Return each database's **Access Control** to blocked (remove the IP /
`0.0.0.0/0` you added). The live services keep working because they connect over
Render's internal network, not the external URL.

---

## Step 4 — Set a known admin password (same on both)

The migrated admin is `kdc_admin` with its original password. To set a fresh
password you control — and keep it identical on both sites — run, with external
access still open from Step 3a and the same `..._DATABASE_URL` set:

```bash
python reset_admin.py boys     # enter username kdc_admin, then the new password
python reset_admin.py girls    # enter the SAME password
```

Now `kdc_admin` + your password logs into both `kdc-boys.onrender.com/admin`
and `kdc-girls.onrender.com/admin`.

---

## Step 5 — Final checks

- [ ] `/health` shows the correct division on each site
- [ ] Admin login works on both with the same credentials
- [ ] Participant counts: Boys **21**, Girls **19** (Admin → Participants)
- [ ] Host QR codes downloaded **after** `PUBLIC_BASE_URL` was set (Step 2)
- [ ] Scoreboard loads at `/scoreboard` on each site

---

## Free-tier notes (read before event day)

- **Free web services sleep after ~15 min idle** and take ~30–60s to wake on the
  first request. For a live event, upgrade each service to a paid instance so the
  scoreboard is always instant.
- **Free PostgreSQL has storage/time limits** and Render has, in the past,
  expired free databases after a set period. Confirm Render's current free-tier
  terms; for anything you can't lose, back up (Admin → CSV export, or
  `pg_dump`) and consider a paid database.
- Keep `COOKIE_SECURE=1` (already set) — Render serves HTTPS, and this makes the
  login cookie HTTPS-only.
