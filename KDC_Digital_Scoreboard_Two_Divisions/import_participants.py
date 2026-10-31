"""Import the children from KDC.xlsx into the Boys and/or Girls database.

    python import_participants.py                      # both, data\\KDC.xlsx
    python import_participants.py --division boys
    python import_participants.py --file C:\\path\\to\\KDC.xlsx

* The "Boys" sheet goes ONLY into the Boys database and the "Girls" sheet ONLY
  into the Girls database.
* Columns: "Child Name", "Gender" and an optional "Age".
* Names are kept exactly as written (only extra spaces are tidied).
* Safe to run again and again: children already present are skipped.
"""
import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_FILE = os.path.join(HERE, "data", "KDC.xlsx")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--division", choices=["boys", "girls", "both"], default="both")
    parser.add_argument("--file", default=DEFAULT_FILE)
    parser.add_argument("--worker", choices=["boys", "girls"], help=argparse.SUPPRESS)
    args = parser.parse_args()

    if not os.path.isfile(args.file):
        print(f"ERROR: file not found: {args.file}")
        return 2

    if args.worker:
        os.environ["KDC_DIVISION"] = args.worker
        sys.path.insert(0, HERE)
        import app as kdc
        with kdc.app.app_context():
            stats = kdc.import_participants_from_xlsx(args.file)
            total = kdc.Participant.query.count()
        print(f"{args.worker.upper():5} sheet {stats['sheets']}: "
              f"{stats['added']} added, {stats['existing']} already present, "
              f"{stats['skipped_wrong_gender']} skipped (wrong gender) "
              f"-> {total} children in database")
        return 0

    status = 0
    for d in (["boys", "girls"] if args.division == "both" else [args.division]):
        env = dict(os.environ, KDC_DIVISION=d)
        status |= subprocess.call(
            [sys.executable, os.path.abspath(__file__), "--worker", d,
             "--file", args.file], env=env)
    return status


if __name__ == "__main__":
    sys.exit(main())
