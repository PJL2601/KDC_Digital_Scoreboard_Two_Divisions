# Test report

Run: `python tests/test_divisions.py` — **111/111 checks passed**, 0 failures (Linux, Python 3.13, Flask 3.1, SQLAlchemy 2.1).
The suite runs each division in its own process (as two real deployments would), against temporary database copies.
Additionally `smoke_test.py` was run for both divisions against the shipped databases.

## Your 12 required tests

| # | Requirement | Result | Evidence (checks in the log below) |
|---|---|---|---|
| 1 | Both configurations start | PASS | `[boys]/[girls] starts and /health reports division`; admin, scoreboard, API render |
| 2 | Boys uses only the Boys DB | PASS | `[boys] database file is kdc_boys.db`; Boys-created team/scores absent from Girls DB |
| 3 | Girls uses only the Girls DB | PASS | `[girls] database file is kdc_girls.db`; Girls-created data absent from Boys DB; Girls refuses to start on the Boys DB |
| 4 | Both DBs contain migrated records | PASS | every row of all 6 original tables identical to the original in both DBs (admin hash, team, 9 games, 3 hosts + tokens, score, audit log) |
| 5 | Original backup unchanged | PASS | SHA-256 and mtime identical after migration, after auto-migration and at the end; no side files created |
| 6 | Boys participants only in Boys | PASS | Boys DB = exactly the 21 names of the Boys sheet, all Male |
| 7 | Girls participants only in Girls | PASS | Girls DB = exactly the 19 names of the Girls sheet, all Female; no name in both |
| 8 | Individual scoring works | PASS | host 1 saves; host 2 sees the same score; scored child leaves the dropdown; per-game totals/ranks correct; admin correct/remove; CSV |
| 9 | Duplicates prevented | PASS | second host rejected; DB UNIQUE constraint rejects a raw insert; 4 simultaneous submissions -> exactly 1 row; same child in another game allowed |
| 10 | Team scoring + approval workflow | PASS | pending is excluded; approve counts (15+2); edit resets to pending; reject excludes; duplicate pending blocked; CSV; CSRF still enforced |
| 11 | Leaderboards show the correct division | PASS | API/scoreboard/CSV list only that division's children and teams; API reports its division |
| 12 | QR codes / host links use the right URL | PASS | PNG decoded with OpenCV = `https://<division>.example.com/host/<token>`; admin host links show the same; other division's URL never appears |

## Extra checks
Re-import creates no duplicates; extra spaces/case-duplicates/wrong-gender rows/Age column handled; migration never overwrites existing data;
first start auto-copies the original; original single-database mode (no `KDC_DIVISION`, `DATABASE_URL`) still works and writes no division tag;
generic `DATABASE_URL` ignored when a division is set; `GIRLS_DATABASE_URL` honoured (`postgres://` normalised); invalid division rejected;
row-copy migration path (used for PostgreSQL) verified on SQLite; locked game blocks individual scoring.

## Not tested here (be aware)
* The Windows `.bat` files could not be run on this Linux machine (written carefully, but try them once on Windows).
* A **live PostgreSQL server** was not available; the URL handling and row-copy code path were tested, the server connection was not.
* Phones scanning a printed QR code on a real network (the QR image content was decoded and verified instead).
* Pages were checked visually with a headless browser (Chromium) on desktop and phone widths.

## Issues found and fixed during testing
* Newer SQLAlchemy defaults `postgresql://` to a different driver -> URLs are now normalised to `postgresql+psycopg2://` (requirements-postgres.txt installs it).
* (Test bug) the manual-add test child was counted as a name shared by both DBs; test corrected.

## Full log
```
PASS  migrate_legacy.py runs for both divisions
PASS  two separate database files created
PASS  boys: every migrated row identical to original (all 6 legacy tables, incl. admin hash, tokens, audit log)
PASS  girls: every migrated row identical to original (all 6 legacy tables, incl. admin hash, tokens, audit log)
PASS  original backup unchanged after migration (SHA-256 + mtime)
PASS  no journal/side files created next to original backup
PASS  re-running migration never overwrites an existing division database
PASS  [boys] starts and /health reports division
PASS  [boys] database file is kdc_boys.db
PASS  [boys] session cookie name is division-specific
PASS  [boys] CSRF protection still enforced
PASS  [boys] migrated records present
PASS  [boys] imports exactly the Boys sheet (names preserved)
PASS  [boys] no Girls names imported
PASS  [boys] gender assigned correctly
PASS  [boys] re-import creates no duplicates
PASS  [boys] original spelling kept ('Harvy ambaliya' / 'Patel Moksha')
PASS  [boys] admin login works
PASS  [boys] admin dashboard renders with children + individual panels
PASS  [boys] host submits team score (pending)
PASS  [boys] duplicate pending team score blocked
PASS  [boys] pending team score NOT on leaderboard
PASS  [boys] approved team score counts (15+2)
PASS  [boys] editing a team score resets it to pending
PASS  [boys] rejected team score excluded
PASS  [boys] team CSV export still works
PASS  [boys] host 1 saves an individual score
PASS  [boys] host 2 sees the same individual score
PASS  [boys] scored child removed from the dropdown
PASS  [boys] duplicate (same child + game) rejected by host 2
PASS  [boys] database-level UNIQUE constraint blocks duplicates
PASS  [boys] invalid point value rejected
PASS  [boys] same child can be scored in another game
PASS  [boys] 4 simultaneous submissions for one child -> exactly 1 score
PASS  [boys] locked game blocks individual scoring
PASS  [boys] individual leaderboard totals/ranks
PASS  [boys] leaderboard lists only this division's children
PASS  [boys] tied children share a rank
PASS  [boys] API reports its division
PASS  [boys] scoreboard page labelled boys
PASS  [boys] individual CSV export
PASS  [boys] team leaderboard unaffected by individual scores
PASS  [boys] admin can correct an individual score
PASS  [boys] admin can remove a score (and it is audit-logged)
PASS  [boys] removed score can be re-entered
PASS  [boys] manual add uses division gender + age
PASS  [boys] QR code decodes to this division's URL
PASS  [boys] QR does not mention the other division
PASS  [boys] admin host links use the division URL
PASS  [girls] starts and /health reports division
PASS  [girls] database file is kdc_girls.db
PASS  [girls] session cookie name is division-specific
PASS  [girls] CSRF protection still enforced
PASS  [girls] migrated records present
PASS  [girls] imports exactly the Girls sheet (names preserved)
PASS  [girls] no Boys names imported
PASS  [girls] gender assigned correctly
PASS  [girls] re-import creates no duplicates
PASS  [girls] original spelling kept ('Harvy ambaliya' / 'Patel Moksha')
PASS  [girls] admin login works
PASS  [girls] admin dashboard renders with children + individual panels
PASS  [girls] host submits team score (pending)
PASS  [girls] duplicate pending team score blocked
PASS  [girls] pending team score NOT on leaderboard
PASS  [girls] approved team score counts (15+2)
PASS  [girls] editing a team score resets it to pending
PASS  [girls] rejected team score excluded
PASS  [girls] team CSV export still works
PASS  [girls] host 1 saves an individual score
PASS  [girls] host 2 sees the same individual score
PASS  [girls] scored child removed from the dropdown
PASS  [girls] duplicate (same child + game) rejected by host 2
PASS  [girls] database-level UNIQUE constraint blocks duplicates
PASS  [girls] invalid point value rejected
PASS  [girls] same child can be scored in another game
PASS  [girls] 4 simultaneous submissions for one child -> exactly 1 score
PASS  [girls] locked game blocks individual scoring
PASS  [girls] individual leaderboard totals/ranks
PASS  [girls] leaderboard lists only this division's children
PASS  [girls] tied children share a rank
PASS  [girls] API reports its division
PASS  [girls] scoreboard page labelled girls
PASS  [girls] individual CSV export
PASS  [girls] team leaderboard unaffected by individual scores
PASS  [girls] admin can correct an individual score
PASS  [girls] admin can remove a score (and it is audit-logged)
PASS  [girls] removed score can be re-entered
PASS  [girls] manual add uses division gender + age
PASS  [girls] QR code decodes to this division's URL
PASS  [girls] QR does not mention the other division
PASS  [girls] admin host links use the division URL
PASS  Boys DB contains only Boys sheet children (+1 manual) and Girls DB only Girls sheet children
PASS  Boys DB has only Male / Girls DB only Female
PASS  no child name appears in both databases
PASS  team created in Boys does not exist in Girls (and vice versa)
PASS  individual scores / audit entries / admin created in one DB never leak to the other
PASS  each DB is tagged with its own division
PASS  session cookie names differ between divisions
PASS  existing host tokens preserved in both DBs
PASS  Girls refuses to start on the Boys database (division guard)
PASS  generic DATABASE_URL ignored when KDC_DIVISION is set (cannot cause shared DB)
PASS  GIRLS_DATABASE_URL honoured (postgres:// -> postgresql+psycopg2://)
PASS  invalid KDC_DIVISION rejected
PASS  first start auto-copies the original DB into the division DB
PASS  original still unchanged after auto-migration
PASS  original single-database mode (no KDC_DIVISION, DATABASE_URL) still works
PASS  single mode writes no division tag
PASS  import: extra spaces tidied, case-insensitive duplicate skipped, wrong-gender row skipped, age supported
PASS  import: Girls sheet only into Girls DB; second run adds nothing
PASS  row-copy migration path (PostgreSQL code path, tested on SQLite) copies all rows identically
PASS  original backup unchanged at the very end (SHA-256)

111/111 checks passed
```
