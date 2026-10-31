"""End-to-end tests for the two-division KDC scoreboard.

    python tests/test_divisions.py

Everything runs against TEMPORARY copies (a temp folder is used for the
division databases); the shipped databases and the original backup are never
written. The original backup's SHA-256 is verified at the end.

The Flask app is bound to one division per process, so each division scenario
runs in its own child process, exactly like two real deployments.
"""
import hashlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ORIGINAL = os.path.join(ROOT, "original_backup", "kdc_scoreboard.db")
XLSX = os.path.join(ROOT, "data", "KDC.xlsx")
sys.path.insert(0, ROOT)

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append({"name": name, "ok": bool(ok), "detail": str(detail)})


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def sheet_names(sheet):
    import openpyxl
    wb = openpyxl.load_workbook(XLSX, data_only=True)
    ws = wb[sheet]
    return [" ".join(str(r[0]).split()) for r in list(ws.iter_rows(values_only=True))[1:] if r[0]]


# =====================================================================
# CHILD: one division, run as its own process
# =====================================================================
def child(division):
    import re

    sys.path.insert(0, ROOT)
    import app as kdc
    from werkzeug.security import generate_password_hash
    from sqlalchemy.exc import IntegrityError

    flask_app, db = kdc.app, kdc.db
    other = "girls" if division == "boys" else "boys"
    my_sheet = "Boys" if division == "boys" else "Girls"
    other_sheet = "Girls" if division == "boys" else "Boys"
    base = f"https://{division}.example.com"

    c = flask_app.test_client()

    check(f"[{division}] starts and /health reports division",
          c.get("/health").json == {"status": "ok", "division": division})
    check(f"[{division}] database file is kdc_{division}.db",
          kdc.DATABASE_URI.endswith(f"kdc_{division}.db"), kdc.DATABASE_URI)
    check(f"[{division}] session cookie name is division-specific",
          flask_app.config["SESSION_COOKIE_NAME"] == f"kdc_{division}_session")

    # CSRF protection from the original app still active
    r = c.post("/admin/login", data={"username": "x", "password": "y"})
    check(f"[{division}] CSRF protection still enforced", r.status_code == 400, r.status_code)
    flask_app.config["WTF_CSRF_ENABLED"] = False

    # --- migrated records present ---------------------------------------
    with flask_app.app_context():
        counts0 = {
            "admin": kdc.Admin.query.count(), "team": kdc.Team.query.count(),
            "game": kdc.Game.query.count(), "host": kdc.HostAssignment.query.count(),
            "score": kdc.ScoreSubmission.query.count(), "audit": kdc.AuditLog.query.count(),
        }
        original_admin = kdc.Admin.query.filter_by(username="kdc_admin").first()
        original_hosts = {h.token: (h.game.number, h.host_name, h.host_slot)
                          for h in kdc.HostAssignment.query.all()}
        # test admin with a known password (temp DB only)
        db.session.add(kdc.Admin(username="tester", password_hash=generate_password_hash("a-long-test-password")))
        db.session.commit()
    check(f"[{division}] migrated records present",
          counts0 == {"admin": 1, "team": 1, "game": 9, "host": 3, "score": 1, "audit": counts0["audit"]}
          and counts0["audit"] >= 22 and original_admin is not None, counts0)

    # --- participants import ----------------------------------------------
    with flask_app.app_context():
        stats = kdc.import_participants_from_xlsx(XLSX)
        stats2 = kdc.import_participants_from_xlsx(XLSX)
        names = sorted(p.name for p in kdc.Participant.query.all())
        genders = {p.gender for p in kdc.Participant.query.all()}
    want = sorted(sheet_names(my_sheet))
    foreign = set(sheet_names(other_sheet))
    check(f"[{division}] imports exactly the {my_sheet} sheet (names preserved)", names == want,
          f"{len(names)} vs {len(want)}")
    check(f"[{division}] no {other_sheet} names imported", not (set(names) & foreign))
    check(f"[{division}] gender assigned correctly",
          genders == {"Male" if division == "boys" else "Female"}, genders)
    check(f"[{division}] re-import creates no duplicates",
          stats["added"] == len(want) and stats2["added"] == 0 and stats2["existing"] == len(want), (stats, stats2))
    check(f"[{division}] original spelling kept ('Harvy ambaliya' / 'Patel Moksha')",
          (division == "boys") or ("Harvy ambaliya" in names and "Patel Moksha" in names))

    # --- login ----------------------------------------------------------
    r = c.post("/admin/login", data={"username": "tester", "password": "a-long-test-password"})
    check(f"[{division}] admin login works", r.status_code == 302 and "/admin" in r.headers["Location"])
    check(f"[{division}] admin dashboard renders with children + individual panels",
          (lambda h: "Participants" in h and "Individual leaderboard" in h and f"· {division.title()}" in h)
          (c.get("/admin").get_data(as_text=True)))

    # --- team workflow (existing feature) ---------------------------------
    c.post("/admin/teams", data={"name": f"{division}-Eagles", "color": "#112233", "age_group": "All ages"})
    with flask_app.app_context():
        team = kdc.Team.query.filter_by(name=f"{division}-Eagles").first()
        team_id = team.id
        hosts = {(h.game.number, h.host_slot): h for h in kdc.HostAssignment.query.all()}
        h1 = hosts[(8, "Host 1")]
        h2 = hosts[(8, "Host 2")]
        t1, t2 = h1.token, h2.token
    r = c.post(f"/host/{t1}", data={"team_id": team_id, "main_points": 15, "bonus_points": 2, "bonus_label": "Best teamwork"})
    check(f"[{division}] host submits team score (pending)", r.status_code == 302)
    r = c.post(f"/host/{t2}", data={"team_id": team_id, "main_points": 12})
    check(f"[{division}] duplicate pending team score blocked",
          b"already awaiting" in r.data, r.status_code)
    api = c.get("/api/scoreboard").json
    eagles = [t for t in api["teams"] if t["name"] == f"{division}-Eagles"][0]
    check(f"[{division}] pending team score NOT on leaderboard", eagles["total"] == 0, eagles)
    with flask_app.app_context():
        sid = kdc.ScoreSubmission.query.filter_by(team_id=team_id).first().id
    c.post(f"/admin/scores/{sid}/review", data={"action": "approve"})
    eagles = [t for t in c.get("/api/scoreboard").json["teams"] if t["name"] == f"{division}-Eagles"][0]
    check(f"[{division}] approved team score counts (15+2)", eagles["total"] == 17 and eagles["games"]["8"] == 17, eagles)
    c.post(f"/admin/scores/{sid}/edit", data={"main_points": 12, "bonus_points": 0})
    with flask_app.app_context():
        sc = db.session.get(kdc.ScoreSubmission, sid)
        st = sc.status
    check(f"[{division}] editing a team score resets it to pending", st == "pending", st)
    c.post(f"/admin/scores/{sid}/review", data={"action": "reject"})
    eagles = [t for t in c.get("/api/scoreboard").json["teams"] if t["name"] == f"{division}-Eagles"][0]
    check(f"[{division}] rejected team score excluded", eagles["total"] == 0)
    c.post(f"/admin/scores/{sid}/edit", data={"main_points": 12, "bonus_points": 0})
    c.post(f"/admin/scores/{sid}/review", data={"action": "approve"})
    check(f"[{division}] team CSV export still works",
          b"Eagles" in c.get("/results.csv").data)

    # --- individual scoring --------------------------------------------------
    kid_a, kid_b = want[0], want[1]
    with flask_app.app_context():
        pid = {p.name: p.id for p in kdc.Participant.query.all()}
    r = c.post(f"/host/{t1}", data={"kind": "individual", "participant_id": pid[kid_a], "points": 15})
    check(f"[{division}] host 1 saves an individual score", r.status_code == 302)
    page2 = c.get(f"/host/{t2}").get_data(as_text=True)
    check(f"[{division}] host 2 sees the same individual score",
          kid_a in page2 and "15 pts" in page2 and "Harsh (Host 1)" in page2)
    sel = re.search(r'name="participant_id".*?</select>', page2, re.S).group(0)
    check(f"[{division}] scored child removed from the dropdown", kid_a not in sel and kid_b in sel)
    r = c.post(f"/host/{t2}", data={"kind": "individual", "participant_id": pid[kid_a], "points": 12})
    with flask_app.app_context():
        n = kdc.IndividualScore.query.filter_by(participant_id=pid[kid_a], game_id=8).count()
    check(f"[{division}] duplicate (same child + game) rejected by host 2",
          b"already has a score" in r.data and n == 1, n)
    with flask_app.app_context():
        gid = kdc.Game.query.filter_by(number=8).first().id
        try:
            db.session.add(kdc.IndividualScore(participant_id=pid[kid_a], game_id=gid, points=5, entered_by="raw"))
            db.session.commit()
            dup_db = False
        except IntegrityError:
            db.session.rollback()
            dup_db = True
    check(f"[{division}] database-level UNIQUE constraint blocks duplicates", dup_db)
    r = c.post(f"/host/{t2}", data={"kind": "individual", "participant_id": pid[kid_b], "points": 99})
    with flask_app.app_context():
        n = kdc.IndividualScore.query.filter_by(participant_id=pid[kid_b]).count()
    check(f"[{division}] invalid point value rejected", n == 0 and b"allowed scoring values" in r.data)
    # same child, DIFFERENT game is allowed
    hosts_g1 = [h for h in hosts.values() if h.game.number == 1]
    t_g1 = hosts_g1[0].token
    r = c.post(f"/host/{t_g1}", data={"kind": "individual", "participant_id": pid[kid_a], "points": 10})
    check(f"[{division}] same child can be scored in another game", r.status_code == 302)
    # simultaneous submissions -> exactly one row
    results = []

    def hit(token):
        cl = flask_app.test_client()
        results.append(cl.post(f"/host/{token}", data={"kind": "individual", "participant_id": pid[kid_b], "points": 15}).status_code)
    ths = [threading.Thread(target=hit, args=(t,)) for t in (t1, t2, t1, t2)]
    [t.start() for t in ths]
    [t.join() for t in ths]
    with flask_app.app_context():
        n = kdc.IndividualScore.query.filter_by(participant_id=pid[kid_b], game_id=gid).count()
    check(f"[{division}] 4 simultaneous submissions for one child -> exactly 1 score", n == 1, f"rows={n} codes={results}")

    # inactive / closed game
    c.post(f"/admin/games/{gid}/state", data={"state": "locked"})
    r = c.post(f"/host/{t1}", data={"kind": "individual", "participant_id": pid[want[2]], "points": 15})
    with flask_app.app_context():
        n = kdc.IndividualScore.query.filter_by(participant_id=pid[want[2]]).count()
    check(f"[{division}] locked game blocks individual scoring", n == 0)
    c.post(f"/admin/games/{gid}/state", data={"state": "open"})

    # leaderboard
    api = c.get("/api/scoreboard").json
    ind = api["individuals"]
    top = ind[0]
    check(f"[{division}] individual leaderboard totals/ranks",
          top["name"] == kid_a and top["total"] == 25 and top["games"]["8"] == 15 and top["games"]["1"] == 10
          and top["rank"] == 1 and ind[1]["name"] == kid_b and ind[1]["total"] == 15 and ind[1]["rank"] == 2, top)
    check(f"[{division}] leaderboard lists only this division's children",
          {p["name"] for p in ind} == set(want) and not ({p["name"] for p in ind} & foreign))
    check(f"[{division}] tied children share a rank", len({p["rank"] for p in ind if p["total"] == 0}) == 1)
    check(f"[{division}] API reports its division", api["division"] == division)
    html = c.get("/scoreboard").get_data(as_text=True)
    check(f"[{division}] scoreboard page labelled {division}", f"{division.title()}".upper() in html.upper() and "individuals-btn" in html)
    check(f"[{division}] individual CSV export",
          kid_a.encode() in c.get("/individual-results.csv").data)
    check(f"[{division}] team leaderboard unaffected by individual scores",
          [t for t in api["teams"] if t["name"] == f"{division}-Eagles"][0]["total"] == 12)

    # admin edit / delete individual score
    with flask_app.app_context():
        sc_id = kdc.IndividualScore.query.filter_by(participant_id=pid[kid_a], game_id=gid).first().id
    c.post(f"/admin/individual-scores/{sc_id}/edit", data={"points": 12})
    top = c.get("/api/scoreboard").json["individuals"][0]
    check(f"[{division}] admin can correct an individual score", top["total"] == 22, top)
    c.post(f"/admin/individual-scores/{sc_id}/delete")
    with flask_app.app_context():
        gone = kdc.IndividualScore.query.get(sc_id) is None
        logs = [a.action for a in kdc.AuditLog.query.all()]
    check(f"[{division}] admin can remove a score (and it is audit-logged)",
          gone and "Deleted individual score" in logs and "Edited individual score" in logs)
    r = c.post(f"/host/{t2}", data={"kind": "individual", "participant_id": pid[kid_a], "points": 15})
    check(f"[{division}] removed score can be re-entered", r.status_code == 302)

    # manual add participant keeps division gender
    c.post("/admin/participants", data={"name": "Manual Kid", "age": "9", "gender": "Female" if division == "boys" else "Male"})
    with flask_app.app_context():
        mk = kdc.Participant.query.filter_by(name="Manual Kid").first()
    check(f"[{division}] manual add uses division gender + age", mk and mk.gender == ("Male" if division == "boys" else "Female") and mk.age == 9)

    # --- QR codes and host links ---------------------------------------------
    import cv2
    import numpy as np
    r = c.get(f"/admin/hosts/{h1.id}/qr.png")
    img = cv2.imdecode(np.frombuffer(r.data, np.uint8), cv2.IMREAD_GRAYSCALE)
    img = cv2.resize(img, None, fx=3, fy=3, interpolation=cv2.INTER_NEAREST)
    decoded, _, _ = cv2.QRCodeDetector().detectAndDecode(img)
    check(f"[{division}] QR code decodes to this division's URL",
          decoded == f"{base}/host/{t1}", decoded)
    check(f"[{division}] QR does not mention the other division", other not in decoded)
    adm = c.get("/admin").get_data(as_text=True)
    check(f"[{division}] admin host links use the division URL",
          f"{base}/host/{t1}" in adm and f"https://{other}.example.com" not in adm)

    # state for the parent to cross-check from disk
    print("RESULT:" + json.dumps({
        "checks": RESULTS,
        "cookie": flask_app.config["SESSION_COOKIE_NAME"],
        "tokens": list(original_hosts),
        "kid_a": kid_a,
    }))


# =====================================================================
# PARENT
# =====================================================================
def run_child(division, env_extra, expect_ok=True):
    env = dict(os.environ)
    env.update({
        "KDC_DIVISION": division, "FLASK_SECRET_KEY": f"{division}-secret-for-tests",
        "ADMIN_SETUP_CODE": f"{division}-setup", "PUBLIC_BASE_URL": f"https://{division}.example.com",
    })
    env.pop("DATABASE_URL", None)
    env.update(env_extra)
    p = subprocess.run([sys.executable, os.path.abspath(__file__), "--child", division],
                       env=env, capture_output=True, text=True, cwd=ROOT)
    return p


def tables(path):
    con = sqlite3.connect(path)
    try:
        return {t: con.execute(f'select count(*) from "{t}"').fetchone()[0]
                for (t,) in con.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'")}
    finally:
        con.close()


def q(path, sql, args=()):
    con = sqlite3.connect(path)
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()


def parent():
    original_hash = sha(ORIGINAL)
    original_mtime = os.stat(ORIGINAL).st_mtime_ns
    tmp = tempfile.mkdtemp(prefix="kdc_tests_")
    dbdir = os.path.join(tmp, "db")
    try:
        # ---- A. migration script (both divisions) ---------------------------------
        env = dict(os.environ, KDC_DB_DIR=dbdir)
        env.pop("KDC_DIVISION", None)
        mig = subprocess.run([sys.executable, os.path.join(ROOT, "migrate_legacy.py")],
                             env=env, capture_output=True, text=True, cwd=ROOT)
        check("migrate_legacy.py runs for both divisions", mig.returncode == 0, mig.stdout[-300:] + mig.stderr[-300:])
        boys_db, girls_db = (os.path.join(dbdir, f"kdc_{d}.db") for d in ("boys", "girls"))
        check("two separate database files created",
              os.path.exists(boys_db) and os.path.exists(girls_db) and boys_db != girls_db)
        orig = sqlite3.connect("file:" + ORIGINAL + "?mode=ro&immutable=1", uri=True)
        legacy_tables = ["admin", "team", "game", "host_assignment", "score_submission", "audit_log"]
        for d, path in (("boys", boys_db), ("girls", girls_db)):
            same = True
            for t in legacy_tables:
                a = orig.execute(f'select * from "{t}" order by id').fetchall()
                b = q(path, f'select * from "{t}" order by id')
                same &= (a == b)
            check(f"{d}: every migrated row identical to original (all 6 legacy tables, incl. admin hash, tokens, audit log)", same)
        orig.close()
        check("original backup unchanged after migration (SHA-256 + mtime)",
              sha(ORIGINAL) == original_hash and os.stat(ORIGINAL).st_mtime_ns == original_mtime)
        check("no journal/side files created next to original backup",
              sorted(os.listdir(os.path.dirname(ORIGINAL))) == ["kdc_scoreboard.db"])

        # re-running must not overwrite data
        con = sqlite3.connect(boys_db)
        con.execute("update team set name='EDITED-IN-BOYS' where id=1")
        con.commit(); con.close()
        subprocess.run([sys.executable, os.path.join(ROOT, "migrate_legacy.py")], env=env, capture_output=True, text=True, cwd=ROOT)
        check("re-running migration never overwrites an existing division database",
              q(boys_db, "select name from team where id=1")[0][0] == "EDITED-IN-BOYS")
        con = sqlite3.connect(boys_db)
        con.execute("update team set name='Test' where id=1"); con.commit(); con.close()

        # ---- B. both divisions run their scenarios against their own DB ---------------
        out = {}
        for d in ("boys", "girls"):
            p = run_child(d, {"KDC_DB_DIR": dbdir, "KDC_AUTO_MIGRATE": "0"})
            line = [l for l in p.stdout.splitlines() if l.startswith("RESULT:")]
            if not line:
                check(f"{d} scenario ran", False, p.stdout[-800:] + p.stderr[-1500:])
                continue
            out[d] = json.loads(line[0][7:])
            RESULTS.extend(out[d]["checks"])

        # ---- C. cross-checks from disk -------------------------------------------------
        if len(out) == 2:
            bn = [r[0] for r in q(boys_db, "select name from participant")]
            gn = [r[0] for r in q(girls_db, "select name from participant")]
            check("Boys DB contains only Boys sheet children (+1 manual) and Girls DB only Girls sheet children",
                  set(bn) - {"Manual Kid"} == set(sheet_names("Boys")) and set(gn) - {"Manual Kid"} == set(sheet_names("Girls")))
            check("Boys DB has only Male / Girls DB only Female",
                  {r[0] for r in q(boys_db, "select distinct gender from participant")} == {"Male"}
                  and {r[0] for r in q(girls_db, "select distinct gender from participant")} == {"Female"})
            check("no child name appears in both databases", not ((set(bn) & set(gn)) - {"Manual Kid"}))
            check("team created in Boys does not exist in Girls (and vice versa)",
                  q(boys_db, "select count(*) from team where name='girls-Eagles'")[0][0] == 0
                  and q(girls_db, "select count(*) from team where name='boys-Eagles'")[0][0] == 0
                  and q(boys_db, "select count(*) from team where name='boys-Eagles'")[0][0] == 1
                  and q(girls_db, "select count(*) from team where name='girls-Eagles'")[0][0] == 1)
            check("individual scores / audit entries / admin created in one DB never leak to the other",
                  q(girls_db, "select count(*) from individual_score s join participant p on p.id=s.participant_id where p.name in (select name from participant where gender='Male')")[0][0] == 0
                  and tables(boys_db)["individual_score"] != 0 and tables(girls_db)["individual_score"] != 0
                  and q(boys_db, "select count(*) from audit_log where details like '%girls-Eagles%'")[0][0] == 0
                  and q(girls_db, "select count(*) from audit_log where details like '%boys-Eagles%'")[0][0] == 0)
            check("each DB is tagged with its own division",
                  q(boys_db, "select value from app_meta where key='division'")[0][0] == "boys"
                  and q(girls_db, "select value from app_meta where key='division'")[0][0] == "girls")
            check("session cookie names differ between divisions", out["boys"]["cookie"] != out["girls"]["cookie"])
            check("existing host tokens preserved in both DBs",
                  sorted(r[0] for r in q(boys_db, "select token from host_assignment"))
                  == sorted(r[0] for r in q(girls_db, "select token from host_assignment"))
                  == sorted(out["boys"]["tokens"]))

        # ---- D. safety guards -----------------------------------------------------------
        # girls pointed at the boys database must refuse to start
        p = run_child("girls", {"KDC_DB_DIR": dbdir, "KDC_AUTO_MIGRATE": "0",
                                "GIRLS_DATABASE_URL": "sqlite:///" + boys_db.replace("\\", "/")})
        check("Girls refuses to start on the Boys database (division guard)",
              p.returncode != 0 and "belongs to the 'boys' division" in p.stderr, p.stderr[-300:])
        # generic DATABASE_URL ignored when KDC_DIVISION is set
        probe = ("import os;import app;print('URI='+app.DATABASE_URI)")
        e = dict(os.environ, KDC_DIVISION="boys", KDC_DB_DIR=dbdir, KDC_AUTO_MIGRATE="0",
                 DATABASE_URL="sqlite:///" + os.path.join(tmp, "generic.db").replace("\\", "/"))
        p = subprocess.run([sys.executable, "-c", probe], env=e, capture_output=True, text=True, cwd=ROOT)
        check("generic DATABASE_URL ignored when KDC_DIVISION is set (cannot cause shared DB)",
              p.stdout.strip().endswith("kdc_boys.db") and not os.path.exists(os.path.join(tmp, "generic.db")), p.stdout + p.stderr[-200:])
        # BOYS_DATABASE_URL honoured; postgres:// normalised
        e = dict(os.environ, KDC_DIVISION="girls", GIRLS_DATABASE_URL="postgres://u:p@h:5432/kdc_girls", KDC_SKIP_INIT="1", KDC_AUTO_MIGRATE="0")
        p = subprocess.run([sys.executable, "-c", probe], env=e, capture_output=True, text=True, cwd=ROOT)
        check("GIRLS_DATABASE_URL honoured (postgres:// -> postgresql+psycopg2://)",
              "URI=postgresql+psycopg2://u:p@h:5432/kdc_girls" in p.stdout, p.stdout + p.stderr[-200:])
        # invalid division
        p = subprocess.run([sys.executable, "-c", "import app"], env=dict(os.environ, KDC_DIVISION="both"), capture_output=True, text=True, cwd=ROOT)
        check("invalid KDC_DIVISION rejected", p.returncode != 0 and "Invalid KDC_DIVISION" in p.stderr)

        # ---- E. auto-migration on first start (no explicit script) -----------------------
        auto_dir = os.path.join(tmp, "auto")
        e = dict(os.environ, KDC_DIVISION="girls", KDC_DB_DIR=auto_dir, FLASK_SECRET_KEY="x")
        e.pop("KDC_AUTO_MIGRATE", None)
        p = subprocess.run([sys.executable, "-c",
                            "import app;c=app.app.test_client();print(c.get('/api/scoreboard').status_code)"],
                           env=e, capture_output=True, text=True, cwd=ROOT)
        ag = os.path.join(auto_dir, "kdc_girls.db")
        check("first start auto-copies the original DB into the division DB",
              p.stdout.strip() == "200" and os.path.exists(ag) and tables(ag)["host_assignment"] == 3 and tables(ag)["audit_log"] >= 22, p.stderr[-300:])
        check("original still unchanged after auto-migration", sha(ORIGINAL) == original_hash)

        # ---- F. backward compatibility (no KDC_DIVISION) ----------------------------------
        legacy_copy = os.path.join(tmp, "legacy_copy.db")
        shutil.copy(ORIGINAL, legacy_copy)
        e = dict(os.environ, DATABASE_URL="sqlite:///" + legacy_copy.replace("\\", "/"), FLASK_SECRET_KEY="x")
        e.pop("KDC_DIVISION", None)
        p = subprocess.run([sys.executable, "-c",
                            "import app;c=app.app.test_client();j=c.get('/api/scoreboard').json;"
                            "print(j['division'], len(j['games']), c.get('/health').json['division'])"],
                           env=e, capture_output=True, text=True, cwd=ROOT)
        check("original single-database mode (no KDC_DIVISION, DATABASE_URL) still works",
              p.stdout.strip() == "None 9 None", p.stdout + p.stderr[-300:])
        check("single mode writes no division tag", "app_meta" not in tables(legacy_copy) or q(legacy_copy, "select count(*) from app_meta")[0][0] == 0)

        # ---- G. import edge cases ---------------------------------------------------------
        import openpyxl
        x = os.path.join(tmp, "edge.xlsx")
        wb = openpyxl.Workbook()
        ws = wb.active; ws.title = "Boys"
        ws.append(["Child Name", "Gender", "Age"])
        ws.append(["Ali  Khan", "Male", 8]); ws.append(["Wrong Girl", "Female", 7]); ws.append(["ali khan", "Male", 9]); ws.append([None, None, None])
        ws2 = wb.create_sheet("Girls"); ws2.append(["Child Name", "Gender"]); ws2.append(["Sara Ahmed", "Female"])
        wb.save(x)
        idb = os.path.join(tmp, "imp")
        e = dict(os.environ, KDC_DB_DIR=idb, KDC_AUTO_MIGRATE="0")
        r1 = subprocess.run([sys.executable, os.path.join(ROOT, "import_participants.py"), "--file", x], env=e, capture_output=True, text=True, cwd=ROOT)
        r2 = subprocess.run([sys.executable, os.path.join(ROOT, "import_participants.py"), "--file", x], env=e, capture_output=True, text=True, cwd=ROOT)
        rows = q(os.path.join(idb, "kdc_boys.db"), "select name, gender, age from participant")
        check("import: extra spaces tidied, case-insensitive duplicate skipped, wrong-gender row skipped, age supported",
              rows == [("Ali Khan", "Male", 8)] and "1 skipped (wrong gender)" in r1.stdout, (rows, r1.stdout))
        check("import: Girls sheet only into Girls DB; second run adds nothing",
              q(os.path.join(idb, "kdc_girls.db"), "select name from participant") == [("Sara Ahmed",)] and "0 added" in r2.stdout, r2.stdout)

        # ---- H. row-copy migration path (used for PostgreSQL) on a pre-created empty sqlite DB ----
        rc = os.path.join(tmp, "rowcopy")
        os.makedirs(rc)
        e = dict(os.environ, KDC_DB_DIR=rc, KDC_DIVISION="boys", KDC_AUTO_MIGRATE="0", KDC_SKIP_INIT="1")
        pre = subprocess.run([sys.executable, "-c",
                              "import app;ctx=app.app.app_context();ctx.push();app.db.create_all()"],
                             env=e, capture_output=True, text=True, cwd=ROOT)
        m = subprocess.run([sys.executable, os.path.join(ROOT, "migrate_legacy.py"), "--division", "boys"],
                           env=dict(os.environ, KDC_DB_DIR=rc), capture_output=True, text=True, cwd=ROOT)
        rcdb = os.path.join(rc, "kdc_boys.db")
        same = all(sqlite3.connect("file:" + ORIGINAL + "?mode=ro&immutable=1", uri=True).execute(f'select * from {t} order by id').fetchall()
                   == q(rcdb, f'select * from {t} order by id') for t in legacy_tables)
        check("row-copy migration path (PostgreSQL code path, tested on SQLite) copies all rows identically",
              m.returncode == 0 and same and "Copied rows into the empty target" in m.stdout, m.stdout[-400:] + m.stderr[-400:])

        check("original backup unchanged at the very end (SHA-256)", sha(ORIGINAL) == original_hash)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ---- report ---------------------------------------------------------------------------
    failed = [r for r in RESULTS if not r["ok"]]
    for r in RESULTS:
        print(("PASS  " if r["ok"] else "FAIL  ") + r["name"] + ("" if r["ok"] else f"   -> {r['detail']}"))
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--child":
        child(sys.argv[2])
    else:
        sys.exit(parent())
