# How the existing database was migrated

## What existed
`kdc_scoreboard.db` (from your uploaded project) — 1 administrator (`kdc_admin`), 1 team (“Test”), 9 games,
3 host assignments (with QR tokens), 1 score submission, 22 audit-log entries.
SHA-256: `fe7f1ab431fb28ac3b4efec7f55cb64daa8de2da63585c0ce5285cd8ec49afeb`

## Choice: BOTH
The same records were copied into **both** divisions; the original was kept as a backup.

| File | Role |
|---|---|
| `original_backup/kdc_scoreboard.db` | Untouched backup (byte-identical, same SHA-256). The app never writes to it. |
| `instance/kdc_boys.db` | Boys database: copy of all original records + new tables + Boys children |
| `instance/kdc_girls.db` | Girls database: copy of all original records + new tables + Girls children |

## How the copy works (`kdc_migrate.py`, `migrate_legacy.py`)
1. The original is opened **read-only** (`mode=ro&immutable=1`): it cannot be modified and no journal files appear next to it. Its SHA-256 is compared before and after.
2. SQLite’s online-backup API creates the division file as an **exact copy** — same schema, same rows, same primary keys. So administrator + password hash, teams, games, **host assignments and their tokens**, score submissions (with status/reviewer/timestamps) and the full audit log are all preserved.
3. The app then runs `create_all()`, which only **adds** the new tables: `participant`, `individual_score`, `app_meta`. Existing tables are not altered (no column changes were needed).
4. A division marker (`app_meta.division`) is stored so a database can never be used by the wrong division.
5. A destination that already contains data is **never overwritten** (re-running is safe).
6. The same copy happens automatically the first time a division starts without a database file (`KDC_AUTO_MIGRATE=0` turns this off).
7. For PostgreSQL targets the script copies the rows table by table (FK order, ids preserved, sequences advanced).

Each division database therefore shows 22 original audit entries + 1 `Imported participants` entry written by the participant import.

Verified result: for all six original tables every row in each division database is identical to the original (see TEST_REPORT.md).

## Things to know
* **Two independent copies from now on.** The same admin account and password exist in both; changing one does not change the other. The “Test” team, the one rejected test score and the three host assignments exist in both divisions — deactivate/remove what you do not need in each.
* **Host tokens are identical in both copies** (exact preservation, so any QR codes already printed keep working). A host link only works on the site whose address is in the QR code, but if you prefer each division to have different tokens, open **Admin → Host QR codes** and re-save each assignment (that rotates the token) before printing new QR codes.
* The original application had **no participant or individual-score data**, so there was nothing to migrate for those; participants come from `KDC.xlsx` (Boys sheet → Boys, Girls sheet → Girls).
* The original was a test database (team “Test”, a rejected score). Nothing was altered or removed; clean up inside each division’s admin if desired.
* To redo a division from scratch: stop the app, move that division’s `.db` file away, start again (it is re-copied from the original and participants re-imported).
