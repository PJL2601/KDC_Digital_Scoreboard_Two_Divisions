"""Copy the ORIGINAL KDC database into the Boys and/or Girls database.

    python migrate_legacy.py                  # both divisions
    python migrate_legacy.py --division boys  # only one
    python migrate_legacy.py --source path\\to\\kdc_scoreboard.db

What it does
------------
* Reads the original database strictly READ-ONLY (it is never modified; its
  SHA-256 is checked before and after as proof).
* Copies every record (admin, teams, games, score submissions, audit log,
  host assignments incl. QR tokens) into each division database, keeping the
  same IDs.
* Never overwrites a division database that already contains data.
* SQLite: the new file is an exact copy of the original (schema + rows), then
  the new tables (participants, individual scores, ...) are added.
* PostgreSQL (BOYS_DATABASE_URL / GIRLS_DATABASE_URL): rows are copied into
  the empty tables.

The app also does the SQLite copy automatically the first time a division
starts, so running this script is optional for local SQLite use.
"""
import argparse
import os
import subprocess
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import kdc_migrate  # noqa: E402  (does not import the Flask app)


def run_worker(division, source):
    """Migrate one division in a child process (the app is per-division)."""
    env = dict(os.environ)
    env["KDC_DIVISION"] = division
    env["KDC_AUTO_MIGRATE"] = "0"   # this script does the copy explicitly
    env["KDC_SKIP_INIT"] = "1"      # tables are created after the copy
    cmd = [sys.executable, os.path.abspath(__file__), "--worker", division]
    if source:
        cmd += ["--source", source]
    return subprocess.call(cmd, env=env)


def parse_dt(value):
    if value is None or isinstance(value, datetime):
        return value
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    return datetime.fromisoformat(value)


def worker(division, source):
    import app as kdc  # KDC_DIVISION / KDC_SKIP_INIT are set by the parent

    legacy = kdc_migrate.find_legacy_db(HERE, source)
    if not legacy:
        print("ERROR: original database not found. Use --source PATH.")
        return 2

    before = kdc_migrate.sha256_file(legacy)
    counts = kdc_migrate.legacy_row_counts(legacy)
    dest = kdc.sqlite_path_from_uri(kdc.DATABASE_URI)
    print(f"\n=== {division.upper()} ===")
    print(f"Original : {legacy}")
    print(f"Target   : {dest or kdc.DATABASE_URI.split('@')[-1]}")
    print(f"Original rows: {counts}")

    if dest and not kdc_migrate.sqlite_file_has_tables(dest):
        # Brand-new SQLite file: exact copy of the original.
        kdc_migrate.copy_sqlite_database(legacy, dest)
        kdc.init_database()
        print("Copied the original SQLite database (exact copy) and added the new tables.")
    else:
        with kdc.app.app_context():
            kdc.db.create_all()
            existing = {
                model.__tablename__: model.query.count()
                for model in (kdc.Admin, kdc.Team, kdc.Game,
                              kdc.HostAssignment, kdc.ScoreSubmission,
                              kdc.AuditLog)
            }
            if any(existing.values()):
                print(f"Target already contains data {existing}; left untouched.")
                kdc.init_database()
                return 0
            copy_rows(kdc, legacy)
        kdc.init_database()
        print("Copied rows into the empty target database.")

    # ---- verification -------------------------------------------------
    after = kdc_migrate.sha256_file(legacy)
    with kdc.app.app_context():
        result = {
            "admin": kdc.Admin.query.count(),
            "team": kdc.Team.query.count(),
            "game": kdc.Game.query.count(),
            "host_assignment": kdc.HostAssignment.query.count(),
            "score_submission": kdc.ScoreSubmission.query.count(),
            "audit_log": kdc.AuditLog.query.count(),
        }
    ok = all(result[t] == counts[t] for t in result)
    print(f"Target rows  : {result}")
    print("Row counts match original: " + ("YES" if ok else "NO  <-- CHECK"))
    print("Original unchanged       : " + ("YES" if before == after else "NO  <-- CHECK"))
    return 0 if ok and before == after else 1


def copy_rows(kdc, legacy):
    """Row-by-row copy (used for PostgreSQL or a pre-created empty SQLite DB)."""
    db = kdc.db
    con = kdc_migrate.open_legacy_readonly(legacy)
    con.row_factory = __import__("sqlite3").Row
    models = [kdc.Admin, kdc.Team, kdc.Game, kdc.HostAssignment,
              kdc.ScoreSubmission, kdc.AuditLog]
    try:
        for model in models:
            table = model.__table__
            cols = {c.name: c for c in table.columns}
            rows = []
            for r in con.execute(f'SELECT * FROM "{table.name}"'):
                row = {}
                for name in r.keys():
                    if name not in cols:
                        continue
                    value = r[name]
                    kind = type(cols[name].type).__name__
                    if kind == "DateTime":
                        value = parse_dt(value)
                    elif kind == "Boolean" and value is not None:
                        value = bool(value)
                    row[name] = value
                rows.append(row)
            if rows:
                db.session.execute(table.insert(), rows)
        db.session.commit()
        # PostgreSQL: move the id counters past the copied ids.
        if db.engine.dialect.name == "postgresql":
            for model in models:
                name = model.__table__.name
                db.session.execute(db.text(
                    f"SELECT setval(pg_get_serial_sequence('{name}', 'id'), "
                    f"COALESCE((SELECT MAX(id) FROM \"{name}\"), 1))"
                ))
            db.session.commit()
    finally:
        con.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--division", choices=["boys", "girls", "both"], default="both")
    parser.add_argument("--source", help="path of the original database "
                        "(default: original_backup/kdc_scoreboard.db)")
    parser.add_argument("--worker", choices=["boys", "girls"], help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.worker:
        return worker(args.worker, args.source)

    divisions = ["boys", "girls"] if args.division == "both" else [args.division]
    status = 0
    for d in divisions:
        status |= run_worker(d, args.source)
    return status


if __name__ == "__main__":
    sys.exit(main())
