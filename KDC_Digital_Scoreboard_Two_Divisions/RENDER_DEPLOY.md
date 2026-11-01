# Deploying the KDC Scoreboard on Render (Boys + Girls)

Two independent web services on Render (from the same code), each pointing at
its **own free external PostgreSQL database** (Render's free tier allows only
one database, so the databases live on Neon or Supabase instead):

| Service    | Division | Database (external) | Example URL                     |
|------------|----------|---------------------|---------------------------------|
| `kdc-boys` | boys     | `kdc_boys`          | `https://kdc-boys.onrender.com` |
| `kdc-girls`| girls    | `kdc_girls`         | `https://kdc-girls.onrender.com`|

The admin login is per-division. Because both databases are migrated from the
same original database, both start with the same `kdc_admin` account — so your
admin credentials are automatically identical on both sites.

---

## Step 0 — Put the files in the right place and push

```
<repo root>/
├── render.yaml            <-- MUST be at the top level
├── RENDER_DEPLOY.md
└── KDC_Digital_Scoreboard_Two_Divisions/
    ├── app.py
    ├── requirements.txt   <-- the psycopg2-binary version
    └── ... (all other project files)
```

- `render.yaml` at the repo root (uses `rootDir: KDC_Digital_Scoreboard_Two_Divisions`
  to build inside the project folder, so your code does not move).
- `requirements.txt` in the project folder, with `psycopg2-binary` (not plain
  `psycopg2`, which fails to build on Render).

```powershell
git add render.yaml
git add KDC_Digital_Scoreboard_Two_Divisions/requirements.txt
git commit -m "Render blueprint (external DB) + psycopg2-binary"
git push
```

---

## Step 1 — Create two free PostgreSQL databases (Neon)

Using **Neon** (neon.tech) — Supabase works too (see note at the end).

1. Sign up at **neon.tech** (sign in with GitHub is easiest).
2. Create a project, e.g. **kdc** (pick a region close to you).
3. In the project, open **Databases** → create two databases:
   - `kdc_boys`
   - `kdc_girls`
4. Open **Connect** (top of the project). For **each** database, choose it in
   the database dropdown and copy its connection string. You'll have two URLs
   that look like:
   ```
   postgresql://<user>:<password>@<host>.neon.tech/kdc_boys?sslmode=require
   postgresql://<user>:<password>@<host>.neon.tech/kdc_girls?sslmode=require
   ```
   Keep both somewhere safe for the next steps. Keep the `?sslmode=require` part.

---

## Step 2 — Create the Blueprint on Render

1. Render dashboard → **New +** → **Blueprint** → connect this repo.
2. Render reads `render.yaml` and shows **2 web services** (no databases now).
3. It will prompt for the two `sync: false` secrets:
   - `BOYS_DATABASE_URL`  → paste the **kdc_boys** connection string
   - `GIRLS_DATABASE_URL` → paste the **kdc_girls** connection string
4. Click **Apply**. Render builds both services (`pip install`, then gunicorn).
   Tables are created automatically on first boot.

> If you earlier created a free `kdc-boys-db` on Render, delete it now
> (it's unused) so it doesn't sit on your one free-database slot.

Check health once both are **Live**:

- `https://kdc-boys.onrender.com/health`  → `{"division":"boys","status":"ok"}`
- `https://kdc-girls.onrender.com/health` → `{"division":"girls","status":"ok"}`

---

## Step 3 — Set each site's real public URL

Render may add a random suffix if a name is taken, so your real URL might be
`kdc-boys-ab12.onrender.com`. QR codes and host links are built from
`PUBLIC_BASE_URL`, so for **each** service → **Environment** → set
`PUBLIC_BASE_URL` to the exact `https://...onrender.com` shown at the top →
**Save** (it redeploys). Do this before handing out any host QR codes.

---

## Step 4 — Migrate your existing data into the two databases

Your source files (`original_backup/kdc_scoreboard.db` and `data/KDC.xlsx`) are
kept out of git, so the migration runs **from your computer** against the Neon
databases. Neon accepts external connections by default — no allowlist needed.

Run from the **inner** project folder (the one with `app.py`, `migrate_legacy.py`,
`original_backup/` and `data/`), with the virtual environment active:

```powershell
pip install -r requirements.txt

# ---- BOYS ----
$env:BOYS_DATABASE_URL = "<kdc_boys connection string>"
python migrate_legacy.py --division boys
python import_participants.py --division boys

# ---- GIRLS ----
$env:GIRLS_DATABASE_URL = "<kdc_girls connection string>"
python migrate_legacy.py --division girls
python import_participants.py --division girls
```

`migrate_legacy.py` prints row counts and refuses to touch a database that
already has data, so run it **before** anyone completes `/setup` on the live
sites. (You won't need `/setup` at all — the admin comes from the original
database.) Expected: admin + 9 games + team + hosts + scores copied, then
**21 Boys / 19 Girls** children imported.

---

## Step 5 — Set a known admin password (same on both)

The migrated admin is `kdc_admin` with its original password. To set a fresh one
you control — identical on both sites — run (same DB URLs as Step 4):

```powershell
python reset_admin.py boys     # username kdc_admin, then the new password
python reset_admin.py girls    # enter the SAME password
```

Now `kdc_admin` + your password logs into both `/admin` pages.

---

## Step 6 — Final checks

- [ ] `/health` shows the correct division on each site
- [ ] Admin login works on both with the same credentials
- [ ] Participant counts: Boys **21**, Girls **19** (Admin → Participants)
- [ ] Host QR codes downloaded **after** `PUBLIC_BASE_URL` was set (Step 3)
- [ ] Scoreboard loads at `/scoreboard` on each site

---

## Free-tier notes (read before event day)

- **Free Render web services sleep after ~15 min idle** (~30–60s to wake). For a
  live event, upgrade each service to a paid instance so it's always instant.
- **Neon free databases auto-suspend when idle** but resume in about a second on
  the next query — fine for low traffic.
- **If you use Supabase instead:** the free plan gives 2 projects (one database
  each) — create one project for Boys, one for Girls, copy each project's
  connection string (Settings → Database → Connection string → URI) into the
  matching Render secret. Note Supabase **pauses** a free project after ~1 week
  of inactivity; open the project to resume it before the event.
- Back up before the event (Admin → CSV export, or `pg_dump`).
