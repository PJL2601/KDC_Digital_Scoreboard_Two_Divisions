# ============================================================
# KDC DIGITAL SCOREBOARD — KIDS DIWALI CELEBRATION 2026
# ============================================================
#
# PURPOSE:
# This application manages games, teams, hosts, scores, and
# the live leaderboard for the KDC 2026 event.
#
# MAIN FEATURES:
# 1. Administrator login and initial setup.
# 2. Team creation and activation/deactivation.
# 3. Game management.
# 4. Host assignments with unique access tokens.
# 5. QR code generation for game hosts.
# 6. Score submission and administrator approval.
# 7. Public leaderboard and JSON API.
# 8. CSV export and audit logging.
# 9. TWO DIVISIONS: the same code runs as a Boys scoreboard or a
#    Girls scoreboard (KDC_DIVISION=boys|girls). Each division uses
#    its own database, admin, hosts/QR tokens, teams and scores.
# 10. INDIVIDUAL SCORING: one score per child per game, shown on
#    an individual leaderboard next to the existing team scoring.
#
# HOW TO CUSTOMIZE:
# - Change game names in GAME_NAMES.
# - Change scoring rules in DEFAULT_CRITERIA.
# - Change bonus options in BONUS_OPTIONS.
# - Modify database models to change stored data.
# - Modify Flask routes to change application behavior.
# - Modify HTML templates to change the user interface.
#
# ============================================================


# ============================================================
# SECTION 1: IMPORTS
# ============================================================

import os
import secrets
import sys

from datetime import datetime
from functools import wraps
from io import BytesIO
from pathlib import Path

# QR code generation
import qrcode

# Flask components for routing, templates, sessions, and responses
from flask import (
    Flask,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

# Database integration
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError

# Helpers for copying the original database (see kdc_migrate.py)
import kdc_migrate

# Protects POST forms against Cross-Site Request Forgery (CSRF)
from flask_wtf.csrf import CSRFProtect

# Secure password hashing and verification
from werkzeug.security import (
    generate_password_hash,
    check_password_hash,
)


# ============================================================
# SECTION 2: FLASK APPLICATION CONFIGURATION
# ============================================================

# Create the Flask application.
app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _log(message):
    """Small start-up logger (visible in the console / hosting logs)."""
    print(f"[KDC] {message}", file=sys.stderr, flush=True)


# ------------------------------------------------------------
# 2.1 Optional .env files (no extra package needed)
# ------------------------------------------------------------
#
# Precedence (highest first):
#   1. Real environment variables
#   2. .env.<division>   (for example .env.boys / .env.girls)
#   3. .env
#
# This makes it easy to keep separate settings for each division
# on one computer. On a hosting service, simply use its environment
# variable settings instead.

def _parse_env_file(path):
    values = {}
    if not os.path.isfile(path):
        return values
    with open(path, encoding="utf-8-sig") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            values[key.strip()] = value
    return values


_base_env = _parse_env_file(os.path.join(BASE_DIR, ".env"))
_division_name = (
    os.environ.get("KDC_DIVISION") or _base_env.get("KDC_DIVISION") or ""
).strip().lower()
_division_env = (
    _parse_env_file(os.path.join(BASE_DIR, f".env.{_division_name}"))
    if _division_name
    else {}
)
for _key, _value in {**_base_env, **_division_env}.items():
    os.environ.setdefault(_key, _value)


# ------------------------------------------------------------
# 2.2 Division selection
# ------------------------------------------------------------
#
# KDC_DIVISION=boys  -> Boys scoreboard  (database: kdc_boys.db)
# KDC_DIVISION=girls -> Girls scoreboard (database: kdc_girls.db)
#
# If KDC_DIVISION is NOT set, the application behaves exactly like
# the original single-scoreboard version (backward compatible).

DIVISIONS = {
    "boys": {
        "label": "Boys",
        "gender": "Male",
        "db_file": "kdc_boys.db",
        "sheet": "boys",
    },
    "girls": {
        "label": "Girls",
        "gender": "Female",
        "db_file": "kdc_girls.db",
        "sheet": "girls",
    },
}

DIVISION = _division_name or None

if DIVISION is not None and DIVISION not in DIVISIONS:
    raise RuntimeError(
        f"Invalid KDC_DIVISION={DIVISION!r}. Use 'boys' or 'girls' "
        "(or leave it unset for the original single-database mode)."
    )

DIVISION_INFO = DIVISIONS.get(DIVISION) if DIVISION else None
DIVISION_LABEL = DIVISION_INFO["label"] if DIVISION_INFO else ""


def div_env(name, default=None):
    """Read a setting for this deployment.

    A division-specific variable (BOYS_<NAME> / GIRLS_<NAME>) wins over
    the plain <NAME>. This lets one computer hold separate secrets and
    URLs for each division, while separate deployments simply set the
    plain names.
    """
    if DIVISION:
        value = os.environ.get(f"{DIVISION.upper()}_{name}")
        if value not in (None, ""):
            return value
    value = os.environ.get(name)
    return value if value not in (None, "") else default


# ------------------------------------------------------------
# 2.3 Database selection
# ------------------------------------------------------------
#
# With KDC_DIVISION set:
#   BOYS_DATABASE_URL / GIRLS_DATABASE_URL  (for example PostgreSQL)
#   otherwise a SQLite file: instance/kdc_boys.db or kdc_girls.db
#   (the folder can be changed with KDC_DB_DIR).
#
# The generic DATABASE_URL is deliberately IGNORED when a division is
# set, so a leftover value can never point both divisions at one
# database. Without KDC_DIVISION it is honoured exactly as before.

DB_DIR = os.environ.get("KDC_DB_DIR") or os.path.join(BASE_DIR, "instance")


def _normalize_db_url(url):
    # Some hosts still hand out postgres:// URLs, and newer SQLAlchemy
    # versions default plain postgresql:// to a different driver. Use the
    # psycopg2 driver (requirements-postgres.txt) explicitly.
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg2://" + url[len(prefix):]
    return url


def resolve_database_uri():
    if DIVISION is None:
        return os.getenv("DATABASE_URL", "sqlite:///kdc_scoreboard.db")

    explicit = os.environ.get(f"{DIVISION.upper()}_DATABASE_URL")
    if explicit:
        return _normalize_db_url(explicit)

    if os.environ.get("DATABASE_URL"):
        _log(
            "DATABASE_URL is set but ignored because KDC_DIVISION is set. "
            f"Use {DIVISION.upper()}_DATABASE_URL instead."
        )
    os.makedirs(DB_DIR, exist_ok=True)
    return "sqlite:///" + Path(
        os.path.join(DB_DIR, DIVISION_INFO["db_file"])
    ).resolve().as_posix()


DATABASE_URI = resolve_database_uri()


def sqlite_path_from_uri(uri):
    prefix = "sqlite:///"
    if uri.startswith(prefix) and uri != "sqlite://" and ":memory:" not in uri:
        return uri[len(prefix):]
    return None


def prepare_division_database():
    """First start of a division: copy the ORIGINAL database into it.

    Runs only for SQLite, only when the division database does not exist
    yet (or is empty), and only reads the original database (read-only).
    Disable with KDC_AUTO_MIGRATE=0.
    """
    if DIVISION is None:
        return
    dest = sqlite_path_from_uri(DATABASE_URI)
    if not dest or os.environ.get("KDC_AUTO_MIGRATE", "1") == "0":
        return
    if kdc_migrate.sqlite_file_has_tables(dest):
        return
    legacy = kdc_migrate.find_legacy_db(
        BASE_DIR, os.environ.get("LEGACY_DATABASE_PATH")
    )
    if not legacy:
        _log(f"No original database found; starting {DIVISION} with an empty database.")
        return
    kdc_migrate.copy_sqlite_database(legacy, dest)
    _log(f"Copied original database {legacy} -> {dest} (original left untouched).")


prepare_division_database()

# Secret key:
# Used to sign session cookies and protect Flask session data.
#
# Set FLASK_SECRET_KEY (or BOYS_FLASK_SECRET_KEY / GIRLS_FLASK_SECRET_KEY)
# as an environment variable. Use a DIFFERENT value for each division.
# Do not use the development fallback in production.
app.config["SECRET_KEY"] = div_env(
    "FLASK_SECRET_KEY",
    "dev-only-change-this-secret",
)

# Database configuration (see 2.3 above).
app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URI

# Disable unnecessary SQLAlchemy modification tracking.
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Prevent JavaScript from reading the session cookie.
app.config["SESSION_COOKIE_HTTPONLY"] = True

# Restrict cross-site cookie behavior.
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# Each division uses its own cookie name. Browsers share cookies between
# ports on the same host (127.0.0.1:5001 and :5002), so without this an
# admin login on one division would collide with the other.
if DIVISION:
    app.config["SESSION_COOKIE_NAME"] = f"kdc_{DIVISION}_session"

# Enable secure cookies over HTTPS when COOKIE_SECURE=1.
# Keep this disabled for local HTTP development.
app.config["SESSION_COOKIE_SECURE"] = (
    div_env("COOKIE_SECURE", "0") == "1"
)

# Initialize the database.
db = SQLAlchemy(app)

# Enable CSRF protection for Flask forms.
csrf = CSRFProtect(app)


# ============================================================
# SECTION 3: GAME CONFIGURATION
# ============================================================

# ------------------------------------------------------------
# 3.1 Game names
# ------------------------------------------------------------
#
# To rename a game, edit the corresponding item below.
#
# IMPORTANT:
# These names are used when games are initially created.
# Changing this list will NOT automatically rename games
# that already exist in the database.

GAME_NAMES = [
    "Balloon Hula Hoop Relay Race",
    "Diwali Dhamaka Glass Tower",
    "Diwali Hoopla Twirl Race",
    "Diwali Patakha Glass Stack",
    "Diwali Hula Hut Dash",
    "Diwali Balloon Catch Blast",
    "Diwali Balloon Cup Mahal",
    "Diwali Cup Tower Dhamaka",
    "Diwali balloon Chain",
]


# ------------------------------------------------------------
# 3.2 Scoring criteria
# ------------------------------------------------------------
#
# Each dictionary key represents a game number.
#
# Each item contains:
#   1. Description of the achievement.
#   2. Points awarded for that achievement.
#
# Example:
#     ("Successful delivery", 10)
#
# This means the host can award 10 main points for that result.
#
# IMPORTANT:
# The host submission form should display these options.
# The host submission route validates the selected point value
# against this dictionary.
#
# To change scoring rules, edit the relevant game's list.
#
# Example:
#     1: [
#         ("Excellent performance", 15),
#         ("Good performance", 10),
#         ("Participation", 5),
#     ]

DEFAULT_CRITERIA = {

    # GAME 1: Balloon Hula Hoop Relay Race
    1: [
        ("Successful delivery", 10),
        ("Reached bucket / retry needed", 6),
        ("Participation / effort", 4),
    ],

    # GAME 2: Diwali Dhamaka Glass Tower
    2: [
        ("Completed tower with balloon control", 15),
        ("Completed with 1–2 drops", 12),
        ("Partly completed", 8),
        ("Participation / effort", 5),
    ],

    # GAME 3: Diwali Hoopla Twirl Race
    3: [
        ("Smooth finish", 15),
        ("Finished with 1–2 drops", 12),
        ("Reached halfway / tried well", 6),
        ("Participation / effort", 5),
    ],

    # GAME 4: Diwali Patakha Glass Stack
    4: [
        ("Stopped at target color", 15),
        ("1 extra flip / close finish", 12),
        ("Tried well / close finish", 6),
        ("Participation / effort", 5),
    ],

    # GAME 5: Diwali Hula Hut Dash
    5: [
        ("Reached finish together", 15),
        ("Reached finish after rebuild", 12),
        ("Tried well / close finish", 6),
        ("Participation / effort", 5),
    ],

    # GAME 6: Diwali Balloon Catch Blast
    6: [
        ("Balloon caught inside hoop", 15),
        ("Close catch / partial success", 12),
        ("Good try / close catch", 6),
        ("Participation / effort", 5),
    ],

    # GAME 7: Diwali Balloon Cup Mahal
    7: [
        ("Full cup palace completed", 15),
        ("Completed with 1–2 drops", 12),
        ("Partial palace / close finish", 9),
        ("Participation / effort", 5),
    ],

    # GAME 8: Diwali Cup Tower Dhamaka
    8: [
        ("Completed tower smoothly", 15),
        ("Completed with 1–2 mistakes", 12),
        ("Partial tower / close finish", 9),
        ("Participation / effort", 5),
    ],

    # GAME 9: Diwali balloon Chain
    9: [
        ("Completed chain successfully", 15),
        ("Completed with 1–2 mistakes", 12),
        ("Partial chain / close finish", 9),
        ("Participation / effort", 5),
    ],
}


# ------------------------------------------------------------
# 3.3 Bonus points
# ------------------------------------------------------------
#
# Hosts can select bonus awards to recognize teams.
#
# Each bonus option awards 2 points.
#
# To change the available bonuses, edit this list.
#
# IMPORTANT:
# The host submission route currently accepts total bonus
# values of 0, 2, 4, or 6.
#
# The number of selectable bonuses in your HTML template
# should be consistent with that rule.

BONUS_OPTIONS = [
    ("Best teamwork", 2),
    ("Fastest team", 2),
    ("Best focus / control", 2),
    ("Biggest smile / fun spirit", 2),
    ("Best effort", 2),
]


# ============================================================
# SECTION 4: DATABASE MODELS
# ============================================================
#
# Database models define the information stored by the app.
#
# If you add a new column or change a relationship, you may
# need a database migration. db.create_all() does not update
# existing database tables to match modified models.


# ------------------------------------------------------------
# 4.1 Administrator model
# ------------------------------------------------------------
#
# Stores administrator login information.
#
# Security:
# Passwords are stored as hashes, not plain text.

class Admin(db.Model):

    # Unique database ID for each administrator.
    id = db.Column(db.Integer, primary_key=True)

    # Login username must be unique.
    username = db.Column(
        db.String(80),
        unique=True,
        nullable=False,
    )

    # Stores the hashed password.
    password_hash = db.Column(
        db.String(255),
        nullable=False,
    )


# ------------------------------------------------------------
# 4.2 Team model
# ------------------------------------------------------------
#
# Stores team details shown on the leaderboard.

class Team(db.Model):

    # Unique team ID.
    id = db.Column(db.Integer, primary_key=True)

    # Team name must be unique.
    name = db.Column(
        db.String(80),
        unique=True,
        nullable=False,
    )

    # Team color used for visual identification.
    color = db.Column(
        db.String(20),
        default="#2563eb",
        nullable=False,
    )

    # Age group associated with the team.
    age_group = db.Column(
        db.String(30),
        default="All ages",
        nullable=False,
    )

    # Inactive teams cannot receive new score submissions.
    # Their historical scores remain in the database.
    active = db.Column(
        db.Boolean,
        default=True,
        nullable=False,
    )


# ------------------------------------------------------------
# 4.3 Game model
# ------------------------------------------------------------
#
# Stores game information and controls whether a game
# accepts score submissions.

class Game(db.Model):

    # Unique database ID.
    id = db.Column(db.Integer, primary_key=True)

    # Public game number, such as Game 1 or Game 2.
    number = db.Column(
        db.Integer,
        unique=True,
        nullable=False,
    )

    # Name displayed to hosts and administrators.
    name = db.Column(
        db.String(120),
        nullable=False,
    )

    # Game states:
    # open      = hosts can submit scores
    # locked    = score submissions are blocked
    # completed = score submissions are blocked
    state = db.Column(
        db.String(20),
        default="open",
        nullable=False,
    )


# ------------------------------------------------------------
# 4.4 Host assignment model
# ------------------------------------------------------------
#
# Connects a host to a specific game.
#
# Each game can have Host 1 and Host 2.
#
# Each assignment receives a unique token that provides
# access to that game's host page.

class HostAssignment(db.Model):

    # Unique host assignment ID.
    id = db.Column(db.Integer, primary_key=True)

    # Reference to the assigned game.
    game_id = db.Column(
        db.Integer,
        db.ForeignKey("game.id"),
        nullable=False,
    )

    # Host's display name.
    host_name = db.Column(
        db.String(80),
        nullable=False,
    )

    # Host position: Host 1 or Host 2.
    host_slot = db.Column(
        db.String(20),
        nullable=False,
    )

    # Random access token used in the host URL.
    #
    # Anyone possessing an active token may be able to
    # submit scores for its assigned game.
    token = db.Column(
        db.String(64),
        unique=True,
        nullable=False,
        default=lambda: secrets.token_urlsafe(24),
    )

    # Setting active=False immediately invalidates this token.
    active = db.Column(
        db.Boolean,
        default=True,
        nullable=False,
    )

    # Allows host.game to access the assigned game.
    # Also creates game.hosts to access its host assignments.
    game = db.relationship(
        "Game",
        backref="hosts",
    )


# ------------------------------------------------------------
# 4.5 Score submission model
# ------------------------------------------------------------
#
# Stores scores submitted by hosts.
#
# Scores must be approved before they contribute to the
# public leaderboard.

class ScoreSubmission(db.Model):

    # Unique submission ID.
    id = db.Column(db.Integer, primary_key=True)

    # Game associated with the submission.
    game_id = db.Column(
        db.Integer,
        db.ForeignKey("game.id"),
        nullable=False,
    )

    # Team associated with the submission.
    team_id = db.Column(
        db.Integer,
        db.ForeignKey("team.id"),
        nullable=False,
    )

    # Main points earned by the team.
    main_points = db.Column(
        db.Integer,
        nullable=False,
    )

    # Additional bonus points.
    bonus_points = db.Column(
        db.Integer,
        default=0,
        nullable=False,
    )

    # Description of the bonus award.
    bonus_label = db.Column(
        db.String(120),
        default="",
        nullable=False,
    )

    # Optional note from the host.
    note = db.Column(
        db.String(300),
        default="",
        nullable=False,
    )

    # Submission workflow:
    # pending  = waiting for administrator review
    # approved = included in leaderboard totals
    # rejected = excluded from leaderboard totals
    status = db.Column(
        db.String(20),
        default="pending",
        nullable=False,
    )

    # Name of the person who submitted the score.
    entered_by = db.Column(
        db.String(80),
        nullable=False,
    )

    # Administrator who reviewed the submission.
    reviewed_by = db.Column(
        db.String(80),
        default="",
        nullable=False,
    )

    # Submission creation time.
    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    # Time when the administrator reviewed the score.
    reviewed_at = db.Column(
        db.DateTime,
        nullable=True,
    )

    # Relationships allow score.game and score.team access.
    game = db.relationship("Game")
    team = db.relationship("Team")


# ------------------------------------------------------------
# 4.6 Audit log model
# ------------------------------------------------------------
#
# Records important actions performed in the application.
#
# Examples:
# - Creating a team.
# - Assigning a host.
# - Submitting a score.
# - Approving or rejecting a score.
# - Changing a game's state.

class AuditLog(db.Model):

    # Unique audit record ID.
    id = db.Column(db.Integer, primary_key=True)

    # Person or account responsible for the action.
    actor = db.Column(
        db.String(80),
        nullable=False,
    )

    # Short description of the action.
    action = db.Column(
        db.String(120),
        nullable=False,
    )

    # Additional information about the action.
    details = db.Column(
        db.Text,
        default="",
        nullable=False,
    )

    # Time when the action was recorded.
    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False,
    )


# ------------------------------------------------------------
# 4.7 Participant model (individual children)
# ------------------------------------------------------------
#
# One row per child. Each division has its own database, so the
# Boys database only holds boys and the Girls database only girls.

class Participant(db.Model):

    id = db.Column(db.Integer, primary_key=True)

    # Name exactly as entered / imported.
    name = db.Column(
        db.String(120),
        nullable=False,
    )

    # Lower-case, single-spaced copy of the name. Unique, so the same
    # child can never be added twice (also across repeated imports).
    name_key = db.Column(
        db.String(120),
        unique=True,
        nullable=False,
    )

    # "Male" or "Female".
    gender = db.Column(
        db.String(10),
        nullable=False,
    )

    # Optional age.
    age = db.Column(
        db.Integer,
        nullable=True,
    )

    # Inactive children are hidden from scoring and the leaderboard.
    # Their scores stay in the database.
    active = db.Column(
        db.Boolean,
        default=True,
        nullable=False,
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False,
    )


# ------------------------------------------------------------
# 4.8 Individual score model
# ------------------------------------------------------------
#
# ONE score per child per game. The UNIQUE constraint is enforced by
# the database itself, so two hosts submitting at the same moment
# can never create a duplicate.

class IndividualScore(db.Model):

    __table_args__ = (
        db.UniqueConstraint(
            "participant_id",
            "game_id",
            name="uq_individual_participant_game",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)

    participant_id = db.Column(
        db.Integer,
        db.ForeignKey("participant.id"),
        nullable=False,
    )

    game_id = db.Column(
        db.Integer,
        db.ForeignKey("game.id"),
        nullable=False,
    )

    points = db.Column(
        db.Integer,
        nullable=False,
    )

    note = db.Column(
        db.String(300),
        default="",
        nullable=False,
    )

    entered_by = db.Column(
        db.String(80),
        nullable=False,
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    # Filled in when an administrator corrects the score.
    updated_by = db.Column(
        db.String(80),
        default="",
        nullable=False,
    )

    updated_at = db.Column(
        db.DateTime,
        nullable=True,
    )

    participant = db.relationship("Participant")
    game = db.relationship("Game")


# ------------------------------------------------------------
# 4.9 Application metadata
# ------------------------------------------------------------
#
# Stores which division a database belongs to. At start-up the app
# refuses to run if KDC_DIVISION does not match, which prevents the
# Boys and Girls deployments from ever sharing one database by mistake.

class AppMeta(db.Model):

    key = db.Column(
        db.String(50),
        primary_key=True,
    )

    value = db.Column(
        db.String(200),
        nullable=False,
    )


# ============================================================
# SECTION 5: HELPER FUNCTIONS
# ============================================================
#
# Helper functions contain reusable logic used by multiple
# routes. Keeping this logic separate reduces duplication.


# ------------------------------------------------------------
# 5.1 Record an audit log entry
# ------------------------------------------------------------
#
# Adds an audit record to the current database session.
#
# IMPORTANT:
# This function does not call db.session.commit().
# The calling route must commit the transaction.

def log_action(actor, action, details=""):

    db.session.add(
        AuditLog(
            actor=actor,
            action=action,
            details=details,
        )
    )


# ------------------------------------------------------------
# 5.2 Protect administrator-only routes
# ------------------------------------------------------------
#
# Add @admin_required above any route that requires
# administrator authentication.
#
# If the administrator is not logged in, redirect them
# to the login page.

def admin_required(fn):

    @wraps(fn)
    def wrapped(*args, **kwargs):

        # Check whether the administrator is authenticated.
        if not session.get("admin_id"):

            # Preserve the requested path as the next parameter.
            return redirect(
                url_for(
                    "admin_login",
                    next=request.path,
                )
            )

        # Continue to the original route.
        return fn(*args, **kwargs)

    return wrapped


# ------------------------------------------------------------
# 5.3 Validate a host's access token
# ------------------------------------------------------------
#
# Finds an active host assignment using its unique token.
#
# Returns:
#   HostAssignment object if the token is valid.
#
# Otherwise:
#   Returns a 404 response.

def host_from_token(token):

    host = HostAssignment.query.filter_by(
        token=token,
        active=True,
    ).first()

    if not host:
        abort(404)

    return host


# ------------------------------------------------------------
# 5.4 Determine the application's public URL
# ------------------------------------------------------------
#
# Used when generating QR codes.
#
# PUBLIC_BASE_URL should contain the externally accessible
# application URL when deployed.
#
# Example:
# https://your-scoreboard.example.com
#
# For local development, the request's URL root is used.

def current_base_url():

    # PUBLIC_BASE_URL (or BOYS_/GIRLS_PUBLIC_BASE_URL) is set per
    # deployment, so QR codes always point to THIS division's site.
    configured = div_env("PUBLIC_BASE_URL")

    if configured:
        return configured.rstrip("/")

    return request.url_root.rstrip("/")


# ------------------------------------------------------------
# 5.5 Calculate approved points for each team
# ------------------------------------------------------------
#
# Only approved submissions contribute to the leaderboard.
#
# Total points = main points + bonus points.
#
# Returns a dictionary:
# {
#     team_id: total_points
# }

def approved_totals():

    rows = db.session.query(
        ScoreSubmission.team_id,
        db.func.sum(
            ScoreSubmission.main_points
            + ScoreSubmission.bonus_points
        ),
    ).filter_by(
        status="approved"
    ).group_by(
        ScoreSubmission.team_id
    ).all()

    return {
        team_id: int(total or 0)
        for team_id, total in rows
    }


# ------------------------------------------------------------
# 5.6 Build the leaderboard
# ------------------------------------------------------------
#
# This function is used by:
# - Administrator dashboard.
# - Public scoreboard API.
# - CSV export.
#
# The leaderboard includes active teams only.
#
# Teams are sorted by:
# 1. Highest total points.
# 2. Team name alphabetically when points are equal.
#
# NOTE:
# The current implementation assigns sequential ranks.
# Teams tied on points will not share the same rank.

def leaderboard_data():

    # Retrieve teams currently marked as active.
    teams = Team.query.filter_by(
        active=True
    ).all()

    # Calculate total approved points for each team.
    totals = approved_totals()

    rows = []

    # Process each active team.
    for team in teams:

        # Store each game's approved points separately.
        game_points = {}

        # Iterate through games in numerical order.
        for game in Game.query.order_by(
            Game.number
        ).all():

            # Sum approved points for this team and game.
            points = db.session.query(
                db.func.sum(
                    ScoreSubmission.main_points
                    + ScoreSubmission.bonus_points
                )
            ).filter_by(
                team_id=team.id,
                game_id=game.id,
                status="approved",
            ).scalar() or 0

            # Use the game number as the dictionary key.
            game_points[str(game.number)] = int(points)

        # Prepare the team's leaderboard data.
        rows.append({
            "id": team.id,
            "name": team.name,
            "color": team.color,
            "age_group": team.age_group,
            "total": totals.get(team.id, 0),
            "games": game_points,
        })

    # Sort by descending score, then alphabetical team name.
    rows.sort(
        key=lambda x: (
            -x["total"],
            x["name"].lower(),
        )
    )

    # Assign sequential positions.
    for i, row in enumerate(rows, start=1):
        row["rank"] = i

    return rows


# ------------------------------------------------------------
# 5.7 Individual leaderboard
# ------------------------------------------------------------
#
# Active children, sorted by total points (highest first), then by
# name. Children with equal totals share the same rank (1, 2, 2, 4).

def individual_leaderboard_data():

    games = Game.query.order_by(
        Game.number
    ).all()

    game_numbers = {
        game.id: game.number
        for game in games
    }

    participants = Participant.query.filter_by(
        active=True
    ).all()

    per_game = {}

    for participant_id, game_id, points in db.session.query(
        IndividualScore.participant_id,
        IndividualScore.game_id,
        IndividualScore.points,
    ).all():

        per_game.setdefault(participant_id, {})[
            str(game_numbers.get(game_id, game_id))
        ] = int(points)

    rows = []

    for person in participants:

        scores = per_game.get(person.id, {})

        rows.append({
            "id": person.id,
            "name": person.name,
            "gender": person.gender,
            "age": person.age,
            "games": {
                str(game.number): scores.get(str(game.number), 0)
                for game in games
            },
            "scored_games": len(scores),
            "total": sum(scores.values()),
        })

    rows.sort(
        key=lambda x: (
            -x["total"],
            x["name"].lower(),
        )
    )

    previous_total = None
    previous_rank = 0

    for position, row in enumerate(rows, start=1):

        if row["total"] != previous_total:
            previous_rank = position
            previous_total = row["total"]

        row["rank"] = previous_rank

    return rows


def allowed_points_for_game(game):

    return [
        points
        for _, points in DEFAULT_CRITERIA.get(
            game.number,
            [],
        )
    ]


# ------------------------------------------------------------
# 5.8 Participant import from Excel
# ------------------------------------------------------------
#
# Reads the "Boys" / "Girls" sheet that matches this division.
# Columns: "Child Name" (or "Name"), "Gender", optional "Age".
# Safe to run any number of times: existing children are skipped.

def clean_name(raw):

    return " ".join(str(raw or "").split())


def normalize_gender(raw):

    value = str(raw or "").strip().lower()

    if value in ("m", "male", "boy", "boys"):
        return "Male"

    if value in ("f", "female", "girl", "girls"):
        return "Female"

    return ""


def parse_age(raw):

    if raw in (None, ""):
        return None

    try:
        age = int(float(str(raw).strip()))
    except ValueError:
        return None

    return age if 0 < age < 120 else None


def import_participants_from_xlsx(path):

    import openpyxl

    workbook = openpyxl.load_workbook(
        path,
        read_only=True,
        data_only=True,
    )

    if DIVISION:
        wanted = [DIVISION_INFO["sheet"]]
        division_gender = DIVISION_INFO["gender"]
    else:
        wanted = ["boys", "girls"]
        division_gender = None

    stats = {
        "added": 0,
        "existing": 0,
        "updated_age": 0,
        "skipped_wrong_gender": 0,
        "skipped_blank": 0,
        "sheets": [],
    }

    for sheet in workbook.worksheets:

        sheet_key = sheet.title.strip().lower()

        if sheet_key not in wanted:
            continue

        stats["sheets"].append(sheet.title)

        rows = list(sheet.iter_rows(values_only=True))

        if not rows:
            continue

        header = [
            str(cell or "").strip().lower()
            for cell in rows[0]
        ]

        def column(*names):
            for name in names:
                if name in header:
                    return header.index(name)
            return None

        name_col = column("child name", "name", "participant")
        gender_col = column("gender", "sex")
        age_col = column("age")

        if name_col is None:
            raise ValueError(
                f"Sheet '{sheet.title}' needs a 'Child Name' column."
            )

        sheet_gender = (
            "Male" if sheet_key == "boys" else "Female"
        )

        for row in rows[1:]:

            name = clean_name(
                row[name_col] if name_col < len(row) else ""
            )

            if not name:
                stats["skipped_blank"] += 1
                continue

            gender = normalize_gender(
                row[gender_col]
                if gender_col is not None and gender_col < len(row)
                else ""
            ) or sheet_gender

            # A boy listed on the Girls sheet (or vice versa) is never
            # imported into the wrong division.
            if division_gender and gender != division_gender:
                stats["skipped_wrong_gender"] += 1
                continue

            age = parse_age(
                row[age_col]
                if age_col is not None and age_col < len(row)
                else None
            )

            key = name.lower()

            existing = Participant.query.filter_by(
                name_key=key
            ).first()

            if existing:
                stats["existing"] += 1

                if age is not None and existing.age is None:
                    existing.age = age
                    stats["updated_age"] += 1

                continue

            db.session.add(
                Participant(
                    name=name,
                    name_key=key,
                    gender=gender,
                    age=age,
                )
            )

            # Flush now so a repeated name inside the same sheet is
            # seen as "existing" instead of violating the unique key.
            db.session.flush()

            stats["added"] += 1

    if not stats["sheets"]:
        raise ValueError(
            "No matching sheet found. Expected a sheet named "
            + " / ".join(w.title() for w in wanted)
            + "."
        )

    if stats["added"]:

        log_action(
            "system",
            "Imported participants",
            f"{os.path.basename(str(path))}: "
            f"{stats['added']} added, {stats['existing']} already present",
        )

    db.session.commit()

    return stats


# ============================================================
# SECTION 6: GLOBAL TEMPLATE VARIABLES
# ============================================================
#
# These variables are automatically available in Jinja
# templates rendered by Flask.
#
# Available variables:
#   event_name
#   is_admin

@app.context_processor
def inject_globals():

    return {
        "event_name": "KDC 2026",
        "is_admin": bool(session.get("admin_id")),
        "division": DIVISION,
        "division_label": DIVISION_LABEL,
    }


# ============================================================
# SECTION 7: PUBLIC HOME PAGE
# ============================================================
#
# URL: /
#
# Displays the main landing page.
#
# Template:
# templates/home.html

@app.route("/")
def home():

    return render_template("home.html")


# ============================================================
# SECTION 8: INITIAL ADMINISTRATOR SETUP
# ============================================================
#
# URL: /setup
#
# Methods:
#   GET  = Display the setup form.
#   POST = Create the administrator and initial games.
#
# This route should only be used during initial setup.
#
# Environment variables:
#   ADMIN_SETUP_CODE
#   FLASK_SECRET_KEY
#
# The first administrator is created with a hashed password.

@app.route("/setup", methods=["GET", "POST"])
def setup():

    # Prevent setup from running again after an administrator
    # already exists.
    if Admin.query.first():

        flash(
            "Administrator setup has already been completed.",
            "info",
        )

        return redirect(
            url_for("admin_login")
        )

    # Process the submitted setup form.
    if request.method == "POST":

        # Read the expected setup code from the environment.
        expected = div_env(
            "ADMIN_SETUP_CODE",
            "",
        )

        # Read the setup code entered by the user.
        provided = request.form.get(
            "setup_code",
            "",
        )

        # If a setup code is configured, validate it.
        if expected and not secrets.compare_digest(
            expected,
            provided,
        ):

            flash(
                "The setup code is incorrect.",
                "error",
            )

            return render_template("setup.html")

        # Do not permit insecure setup using the development
        # secret key when no setup code is configured.
        if (
            not expected
            and app.config["SECRET_KEY"]
            == "dev-only-change-this-secret"
        ):

            flash(
                "Setup configuration was not found. Copy "
                ".env.example to .env and replace the sample "
                "values, or set ADMIN_SETUP_CODE and "
                "FLASK_SECRET_KEY before starting the app. "
                "Restart the app after changing configuration.",
                "error",
            )

            return render_template("setup.html")

        # Read the administrator's credentials.
        username = request.form.get(
            "username",
            "",
        ).strip()

        password = request.form.get(
            "password",
            "",
        )

        # Enforce minimum username and password lengths.
        if len(username) < 3 or len(password) < 12:

            flash(
                "Use a username with at least 3 characters "
                "and a password with at least 12 characters.",
                "error",
            )

            return render_template("setup.html")

        # Create the administrator with a hashed password.
        admin = Admin(
            username=username,
            password_hash=generate_password_hash(password),
        )

        db.session.add(admin)

        # Create the initial games from GAME_NAMES.
        #
        # IMPORTANT:
        # This creates nine games because GAME_NAMES contains
        # nine entries.
        for number, name in enumerate(
            GAME_NAMES,
            start=1,
        ):

            db.session.add(
                Game(
                    number=number,
                    name=name,
                )
            )

        # Save the administrator and initial games.
        db.session.commit()

        # Record the setup action.
        log_action(
            username,
            "Initial setup",
            "Created administrator and nine games",
        )

        db.session.commit()

        flash(
            "Setup complete. Sign in to configure teams and hosts.",
            "success",
        )

        return redirect(
            url_for("admin_login")
        )

    # Display the setup form for GET requests.
    return render_template("setup.html")


# ============================================================
# SECTION 9: ADMINISTRATOR LOGIN
# ============================================================
#
# URL: /admin/login
#
# Methods:
#   GET  = Display the login form.
#   POST = Validate the submitted credentials.
#
# The session stores the administrator's ID and username
# after successful authentication.

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():

    if request.method == "POST":

        # Find the administrator by username.
        admin = Admin.query.filter_by(
            username=request.form.get(
                "username",
                "",
            ).strip()
        ).first()

        # Validate the password against its stored hash.
        if admin and check_password_hash(
            admin.password_hash,
            request.form.get("password", ""),
        ):

            # Remove old session data before login.
            session.clear()

            # Save authenticated administrator information.
            session["admin_id"] = admin.id
            session["admin_username"] = admin.username

            # Open the administrator dashboard.
            #
            # NOTE:
            # The current code ignores the optional "next"
            # parameter and always redirects to /admin.
            return redirect(
                url_for("admin_dashboard")
            )

        # Display an error for invalid credentials.
        flash(
            "Invalid username or password.",
            "error",
        )

    return render_template("login.html")


# ============================================================
# SECTION 10: ADMINISTRATOR LOGOUT
# ============================================================
#
# URL: /admin/logout
#
# Only POST requests are accepted.
#
# The logout form in the HTML template must include a valid
# CSRF token because CSRFProtect is enabled.

@app.route("/admin/logout", methods=["POST"])
def admin_logout():

    # Remove all session information.
    session.clear()

    flash(
        "You have been signed out.",
        "success",
    )

    return redirect(
        url_for("home")
    )


# ============================================================
# SECTION 11: ADMINISTRATOR DASHBOARD
# ============================================================
#
# URL: /admin
#
# Requires administrator authentication.
#
# The dashboard receives:
#   teams       = All teams, including inactive teams.
#   games       = All games.
#   pending     = Scores waiting for review.
#   submissions = The 30 most recent submissions.
#   leaderboard = Current active-team leaderboard.
#   hosts       = All host assignments.

@app.route("/admin")
@admin_required
def admin_dashboard():

    # Retrieve teams alphabetically.
    teams = Team.query.order_by(
        Team.name
    ).all()

    # Retrieve games in numerical order.
    games = Game.query.order_by(
        Game.number
    ).all()

    # Retrieve scores awaiting administrator review.
    pending = ScoreSubmission.query.filter_by(
        status="pending"
    ).order_by(
        ScoreSubmission.created_at.desc()
    ).all()

    # Retrieve the 30 most recent score submissions.
    submissions = ScoreSubmission.query.order_by(
        ScoreSubmission.created_at.desc()
    ).limit(30).all()

    # Render the dashboard with the required data.
    return render_template(
        "admin.html",
        teams=teams,
        games=games,
        pending=pending,
        submissions=submissions,
        leaderboard=leaderboard_data(),
        hosts=HostAssignment.query.order_by(
            HostAssignment.game_id,
            HostAssignment.host_slot,
        ).all(),

        # Individual scoring data.
        participants=Participant.query.order_by(
            db.func.lower(Participant.name)
        ).all(),
        individual_scores=IndividualScore.query.order_by(
            IndividualScore.created_at.desc()
        ).all(),
        individual_board=individual_leaderboard_data(),
        game_points={
            game.id: allowed_points_for_game(game)
            for game in games
        },

        # Host links shown next to each QR code, so the admin can
        # confirm they point to this division's website.
        base_url=current_base_url(),
    )


# ============================================================
# SECTION 12: TEAM MANAGEMENT
# ============================================================


# ------------------------------------------------------------
# 12.1 Create a new team
# ------------------------------------------------------------
#
# URL: POST /admin/teams
#
# Form fields:
#   name      = Team name.
#   color     = Team display color.
#   age_group = Team age group.
#
# Duplicate team names are rejected.

@app.route("/admin/teams", methods=["POST"])
@admin_required
def add_team():

    # Read and validate the submitted team information.
    name = request.form.get(
        "name",
        "",
    ).strip()

    color = request.form.get(
        "color",
        "#2563eb",
    )

    age_group = request.form.get(
        "age_group",
        "All ages",
    )

    # Reject an empty team name.
    if not name:

        flash(
            "Team name is required.",
            "error",
        )

    # Reject duplicate team names.
    elif Team.query.filter_by(
        name=name
    ).first():

        flash(
            "That team name already exists.",
            "error",
        )

    else:

        # Create and save the new team.
        team = Team(
            name=name,
            color=color,
            age_group=age_group,
        )

        db.session.add(team)

        # Record the action.
        log_action(
            session["admin_username"],
            "Created team",
            name,
        )

        db.session.commit()

        flash(
            f"Team {name} added.",
            "success",
        )

    return redirect(
        url_for("admin_dashboard")
    )


# ------------------------------------------------------------
# 12.2 Activate or deactivate a team
# ------------------------------------------------------------
#
# URL: POST /admin/teams/<team_id>/toggle
#
# Active teams appear on the public leaderboard and are
# available for new score submissions.
#
# Deactivating a team does not delete its historical scores.

@app.route(
    "/admin/teams/<int:team_id>/toggle",
    methods=["POST"],
)
@admin_required
def toggle_team(team_id):

    # Find the team or return a 404 response.
    team = db.get_or_404(
        Team,
        team_id,
    )

    # Reverse the team's current active state.
    team.active = not team.active

    # Record the change.
    log_action(
        session["admin_username"],
        "Toggled team",
        f"{team.name}: active={team.active}",
    )

    db.session.commit()

    return redirect(
        url_for("admin_dashboard")
    )


# ============================================================
# SECTION 13: GAME MANAGEMENT
# ============================================================
#
# Administrators can open, lock, or complete a game.
#
# URL: POST /admin/games/<game_id>/state
#
# Game states:
#   open      = Score submissions are permitted.
#   locked    = Score submissions are blocked.
#   completed = Score submissions are blocked.

@app.route(
    "/admin/games/<int:game_id>/state",
    methods=["POST"],
)
@admin_required
def game_state(game_id):

    # Find the selected game.
    game = db.get_or_404(
        Game,
        game_id,
    )

    # Read the requested state from the form.
    state = request.form.get("state")

    # Accept only the three supported states.
    if state not in (
        "open",
        "locked",
        "completed",
    ):

        abort(400)

    # Update the game state.
    game.state = state

    # Record the state change.
    log_action(
        session["admin_username"],
        "Changed game state",
        f"Game {game.number}: {state}",
    )

    db.session.commit()

    flash(
        f"Game {game.number} is now {state}.",
        "success",
    )

    return redirect(
        url_for("admin_dashboard")
    )


# ============================================================
# SECTION 14: HOST ASSIGNMENTS
# ============================================================


# ------------------------------------------------------------
# 14.1 Create or update a host assignment
# ------------------------------------------------------------
#
# URL: POST /admin/hosts
#
# Form fields:
#   game_id   = Game assigned to the host.
#   host_slot = Host 1 or Host 2.
#   host_name = Host's display name.
#
# If the game/slot already exists, the existing assignment
# is updated and receives a new access token.
#
# Otherwise, a new host assignment is created.

@app.route("/admin/hosts", methods=["POST"])
@admin_required
def add_host():

    # Read the selected game ID.
    game_id = request.form.get(
        "game_id",
        type=int,
    )

    # Read the selected host position.
    slot = request.form.get(
        "host_slot",
        "",
    )

    # Read the host's name.
    name = request.form.get(
        "host_name",
        "",
    ).strip()

    # Find the selected game.
    game = (
        db.session.get(Game, game_id)
        if game_id
        else None
    )

    # Validate the game, slot, and name.
    if (
        not game
        or slot not in ("Host 1", "Host 2")
        or not name
    ):

        flash(
            "Choose a game, host slot, and host name.",
            "error",
        )

        return redirect(
            url_for("admin_dashboard")
        )

    # Look for an existing assignment for this game and slot.
    host = HostAssignment.query.filter_by(
        game_id=game.id,
        host_slot=slot,
    ).first()

    if host:

        # Update the existing assignment.
        host.host_name = name

        # Rotate the token so the previous URL becomes invalid.
        host.token = secrets.token_urlsafe(24)

        # Reactivate the assignment.
        host.active = True

    else:

        # Create a new host assignment.
        host = HostAssignment(
            game_id=game.id,
            host_name=name,
            host_slot=slot,
        )

        db.session.add(host)

    # Record the assignment.
    log_action(
        session["admin_username"],
        "Configured host",
        f"Game {game.number}, {slot}, {name}",
    )

    db.session.commit()

    flash(
        "Host assignment saved. Its QR code is available below.",
        "success",
    )

    return redirect(
        url_for("admin_dashboard")
    )


# ------------------------------------------------------------
# 14.2 Revoke host access
# ------------------------------------------------------------
#
# URL: POST /admin/hosts/<host_id>/revoke
#
# Setting active=False invalidates the existing host token.
# The host cannot access the host page using that assignment.

@app.route(
    "/admin/hosts/<int:host_id>/revoke",
    methods=["POST"],
)
@admin_required
def revoke_host(host_id):

    # Find the host assignment.
    host = db.get_or_404(
        HostAssignment,
        host_id,
    )

    # Disable the assignment.
    host.active = False

    # Record the revocation.
    log_action(
        session["admin_username"],
        "Revoked host access",
        f"Game {host.game.number}: {host.host_name}",
    )

    db.session.commit()

    flash(
        "Host access revoked.",
        "success",
    )

    return redirect(
        url_for("admin_dashboard")
    )


# ------------------------------------------------------------
# 14.3 Generate a host QR code
# ------------------------------------------------------------
#
# URL: GET /admin/hosts/<host_id>/qr.png
#
# Creates a PNG image containing the host's access URL.
#
# PUBLIC_BASE_URL must be configured correctly when the
# application is deployed.
#
# IMPORTANT:
# A QR code is effectively an access credential.
# Share it only with the intended host.

@app.route(
    "/admin/hosts/<int:host_id>/qr.png"
)
@admin_required
def host_qr(host_id):

    # Find the host assignment.
    host = db.get_or_404(
        HostAssignment,
        host_id,
    )

    # Build the destination URL.
    target = (
        current_base_url()
        + url_for(
            "host_page",
            token=host.token,
        )
    )

    # Generate the QR code.
    img = qrcode.make(target)

    # Save the image to an in-memory buffer.
    buffer = BytesIO()

    img.save(
        buffer,
        format="PNG",
    )

    # Reset the buffer position before sending it.
    buffer.seek(0)

    # Return the QR code as a downloadable PNG.
    return send_file(
        buffer,
        mimetype="image/png",
        download_name=(
            f"kdc-game-{host.game.number}-"
            f"{host.host_slot.lower().replace(' ', '-')}.png"
        ),
    )


# ------------------------------------------------------------
# 14.4 Individual scoring helpers (used by the host page)
# ------------------------------------------------------------
#
# Both hosts of a game see exactly the same individual scores,
# because the data is read by game, not by host.

def individual_host_context(game):

    active_people = Participant.query.filter_by(
        active=True
    ).order_by(
        db.func.lower(Participant.name)
    ).all()

    recorded = IndividualScore.query.filter_by(
        game_id=game.id
    ).order_by(
        IndividualScore.created_at.desc()
    ).all()

    scored_ids = {
        score.participant_id
        for score in recorded
    }

    return {
        "unscored_participants": [
            person
            for person in active_people
            if person.id not in scored_ids
        ],
        "individual_scores": recorded,
        "participant_total": len(active_people),
    }


def submit_individual_score(host, game):

    """Validate and save one individual score.

    Returns True when saved. Otherwise it flashes the reason and
    returns False.
    """

    person_id = request.form.get(
        "participant_id",
        type=int,
    )

    person = (
        db.session.get(Participant, person_id)
        if person_id
        else None
    )

    points = request.form.get(
        "points",
        type=int,
    )

    note = request.form.get(
        "note",
        "",
    ).strip()[:300]

    if not person or not person.active:

        flash(
            "Select a valid child.",
            "error",
        )

        return False

    if points not in allowed_points_for_game(game):

        flash(
            "Choose one of the allowed scoring values "
            "for this game.",
            "error",
        )

        return False

    existing = IndividualScore.query.filter_by(
        participant_id=person.id,
        game_id=game.id,
    ).first()

    if existing:

        flash(
            f"{person.name} already has a score for this game "
            f"({existing.points} points, entered by "
            f"{existing.entered_by}). Ask the administrator "
            "to correct it.",
            "error",
        )

        return False

    db.session.add(
        IndividualScore(
            participant_id=person.id,
            game_id=game.id,
            points=points,
            note=note,
            entered_by=(
                f"{host.host_name} ({host.host_slot})"
            ),
        )
    )

    log_action(
        host.host_name,
        "Submitted individual score",
        (
            f"Game {game.number}, "
            f"child {person.name}, "
            f"{points}"
        ),
    )

    try:

        db.session.commit()

    except IntegrityError:

        # Another host saved this child's score at the same moment.
        db.session.rollback()

        flash(
            f"{person.name} already has a score for this game.",
            "error",
        )

        return False

    flash(
        f"Saved {points} points for {person.name}.",
        "success",
    )

    return True


# ============================================================
# SECTION 15: HOST SCORING PAGE
# ============================================================
#
# URL: /host/<token>
#
# This is the page used by game hosts.
#
# GET:
#   Displays the scoring form and recent submissions.
#
# POST:
#   Validates and saves a score submission.
#
# IMPORTANT:
# Hosts do not directly approve scores.
# Every new submission starts with status="pending".

@app.route(
    "/host/<token>",
    methods=["GET", "POST"],
)
def host_page(token):

    # Validate the token and retrieve the host assignment.
    host = host_from_token(token)

    # Get the game assigned to this host.
    game = host.game

    # Block submissions if the game is not open.
    if game.state != "open":

        return render_template(
            "host_closed.html",
            host=host,
            game=game,
        )

    # Retrieve active teams for the scoring form.
    teams = Team.query.filter_by(
        active=True
    ).order_by(
        Team.name
    ).all()

    # Individual (per-child) scores are posted by a second form on the
    # same page. They are handled separately from team scores.
    if (
        request.method == "POST"
        and request.form.get("kind") == "individual"
    ):

        if submit_individual_score(host, game):

            return redirect(
                url_for(
                    "host_page",
                    token=token,
                )
            )

    # Process team score submissions.
    elif request.method == "POST":

        # Read the selected team.
        team = db.session.get(
            Team,
            request.form.get(
                "team_id",
                type=int,
            ),
        )

        # Read the selected main score.
        main_points = request.form.get(
            "main_points",
            type=int,
        )

        # Read bonus points; default to zero.
        bonus_points = request.form.get(
            "bonus_points",
            default=0,
            type=int,
        )

        # Read the bonus description.
        bonus_label = request.form.get(
            "bonus_label",
            "",
        ).strip()

        # Limit notes to 300 characters.
        note = request.form.get(
            "note",
            "",
        ).strip()[:300]

        # Get the permitted scoring values for this game.
        allowed = [
            points
            for _, points in DEFAULT_CRITERIA.get(
                game.number,
                [],
            )
        ]

        # Validate that the selected team exists and is active.
        if not team or not team.active:

            flash(
                "Select a valid active team.",
                "error",
            )

        # Validate the main score.
        elif main_points not in allowed:

            flash(
                "Choose one of the allowed scoring values "
                "for this game.",
                "error",
            )

        # Validate the bonus score.
        elif bonus_points not in (
            0,
            2,
            4,
            6,
        ):

            flash(
                "Bonus points must be 0, 2, 4, or 6.",
                "error",
            )

        else:

            # Prevent multiple pending submissions for the
            # same team in the same game.
            #
            # NOTE:
            # This check does not prevent multiple approved
            # submissions for the same team and game.
            existing = ScoreSubmission.query.filter_by(
                game_id=game.id,
                team_id=team.id,
                status="pending",
            ).first()

            if existing:

                flash(
                    "A score for this team is already awaiting "
                    "review. Ask the co-host or administrator "
                    "to review it.",
                    "error",
                )

            else:

                # Create a new pending score submission.
                submission = ScoreSubmission(
                    game_id=game.id,
                    team_id=team.id,
                    main_points=main_points,
                    bonus_points=bonus_points,
                    bonus_label=bonus_label,
                    note=note,
                    entered_by=(
                        f"{host.host_name} ({host.host_slot})"
                    ),
                )

                db.session.add(submission)

                # Record the submission in the audit log.
                log_action(
                    host.host_name,
                    "Submitted score",
                    (
                        f"Game {game.number}, "
                        f"team {team.name}, "
                        f"{main_points}+{bonus_points}"
                    ),
                )

                # Save the submission and audit record.
                db.session.commit()

                flash(
                    "Score submitted and awaiting administrator "
                    "approval.",
                    "success",
                )

                # Redirect after POST to prevent accidental
                # duplicate form submissions on refresh.
                return redirect(
                    url_for(
                        "host_page",
                        token=token,
                    )
                )

    # Retrieve the 15 most recent submissions for this game.
    #
    # These include pending, approved, and rejected scores.
    recent = ScoreSubmission.query.filter_by(
        game_id=game.id
    ).order_by(
        ScoreSubmission.created_at.desc()
    ).limit(15).all()

    # Get the scoring criteria for the selected game.
    criteria = DEFAULT_CRITERIA.get(
        game.number,
        [],
    )

    # Render the host scoring page.
    return render_template(
        "host.html",
        host=host,
        game=game,
        teams=teams,
        criteria=criteria,
        bonuses=BONUS_OPTIONS,
        recent=recent,
        **individual_host_context(game),
    )


# ============================================================
# SECTION 16: REVIEW SCORE SUBMISSIONS
# ============================================================
#
# URL: POST /admin/scores/<score_id>/review
#
# Administrators can approve or reject a submitted score.
#
# Only approved scores contribute to leaderboard totals.

@app.route(
    "/admin/scores/<int:score_id>/review",
    methods=["POST"],
)
@admin_required
def review_score(score_id):

    # Find the selected score submission.
    score = db.get_or_404(
        ScoreSubmission,
        score_id,
    )

    # Read the administrator's decision.
    action = request.form.get("action")

    # Accept only approve or reject.
    if action not in (
        "approve",
        "reject",
    ):

        abort(400)

    # Update the submission status.
    score.status = (
        "approved"
        if action == "approve"
        else "rejected"
    )

    # Record who reviewed the submission.
    score.reviewed_by = session["admin_username"]

    # Record the review timestamp.
    score.reviewed_at = datetime.utcnow()

    # Record the decision in the audit log.
    log_action(
        session["admin_username"],
        f"{action.title()}d score",
        (
            f"Submission {score.id}, "
            f"team {score.team.name}, "
            f"game {score.game.number}"
        ),
    )

    db.session.commit()

    flash(
        f"Score {action}d.",
        "success",
    )

    return redirect(
        url_for("admin_dashboard")
    )


# ============================================================
# SECTION 17: EDIT AN EXISTING SCORE
# ============================================================
#
# URL: POST /admin/scores/<score_id>/edit
#
# Administrators can correct a score.
#
# The game must be open before editing.
#
# Every edited score is returned to pending status so that
# the administrator must review the corrected submission.
#
# Form fields:
#   main_points
#   bonus_points

@app.route(
    "/admin/scores/<int:score_id>/edit",
    methods=["POST"],
)
@admin_required
def edit_score(score_id):

    # Find the selected score.
    score = db.get_or_404(
        ScoreSubmission,
        score_id,
    )

    # Preserve the old values for audit logging.
    old = (
        f"{score.main_points}+"
        f"{score.bonus_points} "
        f"({score.status})"
    )

    # Read the proposed replacement values.
    main_points = request.form.get(
        "main_points",
        type=int,
    )

    bonus_points = request.form.get(
        "bonus_points",
        type=int,
    )

    # Prevent editing scores when the game is not open.
    if score.game.state != "open":

        flash(
            "Reopen the game before editing a score.",
            "error",
        )

    # Validate the replacement values.
    elif (
        main_points not in [
            points
            for _, points in DEFAULT_CRITERIA.get(
                score.game.number,
                [],
            )
        ]
        or bonus_points not in (
            0,
            2,
            4,
            6,
        )
    ):

        flash(
            "Invalid point values.",
            "error",
        )

    else:

        # Apply the corrected scores.
        score.main_points = main_points
        score.bonus_points = bonus_points

        # Require a fresh approval.
        score.status = "pending"

        # Clear the previous review information.
        score.reviewed_by = ""
        score.reviewed_at = None

        # Record the edit.
        log_action(
            session["admin_username"],
            "Edited score",
            (
                f"Submission {score.id}: "
                f"{old} -> "
                f"{main_points}+{bonus_points}; "
                "reset to pending"
            ),
        )

        db.session.commit()

        flash(
            "Score updated and returned to pending approval.",
            "success",
        )

    return redirect(
        url_for("admin_dashboard")
    )


# ============================================================
# SECTION 18: PUBLIC SCOREBOARD PAGE
# ============================================================
#
# URL: /scoreboard
#
# Displays the public scoreboard.
#
# Template:
# templates/scoreboard.html
#
# The template can retrieve live score data from /api/scoreboard.

@app.route("/scoreboard")
def scoreboard():

    return render_template(
        "scoreboard.html"
    )


# ============================================================
# SECTION 19: PUBLIC SCOREBOARD API
# ============================================================
#
# URL: GET /api/scoreboard
#
# Returns JSON data for the public scoreboard.
#
# The frontend can request this endpoint periodically
# to refresh the leaderboard without reloading the page.
#
# Example response structure:
#
# {
#     "event": "KDC 2026 — Kids Diwali Celebration",
#     "updated_at": "...",
#     "games": [...],
#     "teams": [...]
# }

@app.route("/api/scoreboard")
def scoreboard_api():

    # Retrieve all games in numerical order.
    games = Game.query.order_by(
        Game.number
    ).all()

    # Return the event information, games, and leaderboard.
    return jsonify({

        # Event title displayed by the scoreboard.
        "event": "KDC 2026 — Kids Diwali Celebration",

        # "boys", "girls", or null in the original single mode.
        "division": DIVISION,
        "division_label": DIVISION_LABEL,

        # Timestamp indicating when this response was generated.
        "updated_at": datetime.utcnow().isoformat() + "Z",

        # Public game information.
        "games": [
            {
                "id": game.id,
                "number": game.number,
                "name": game.name,
                "state": game.state,
            }
            for game in games
        ],

        # Current leaderboard data.
        "teams": leaderboard_data(),

        # Individual (per-child) leaderboard.
        "individuals": individual_leaderboard_data(),
    })


# ============================================================
# SECTION 20: EXPORT RESULTS TO CSV
# ============================================================
#
# URL: GET /results.csv
#
# Requires administrator authentication.
#
# Downloads a CSV containing:
# - Team rank.
# - Team name.
# - Age group.
# - Points for each game.
# - Total approved points.
#
# The CSV can be opened in Microsoft Excel or Google Sheets.

@app.route("/results.csv")
@admin_required
def export_csv():

    # Import CSV utilities.
    import csv
    import io

    from flask import make_response

    # Create an in-memory text buffer.
    text_buffer = io.StringIO()

    # Initialize the CSV writer.
    writer = csv.writer(text_buffer)

    # Retrieve games in numerical order.
    games = Game.query.order_by(
        Game.number
    ).all()

    # Write the CSV header.
    writer.writerow(
        ["Rank", "Team", "Age Group"]
        + [
            f"Game {game.number}"
            for game in games
        ]
        + ["Total"]
    )

    # Retrieve the leaderboard.
    leaderboard = leaderboard_data()

    # Write one row for each active team.
    for row in leaderboard:

        writer.writerow(
            [
                row["rank"],
                row["name"],
                row["age_group"],
            ]
            + [
                row["games"].get(
                    str(game.number),
                    0,
                )
                for game in games
            ]
            + [
                row["total"],
            ]
        )

    # Build the HTTP response.
    response = make_response(
        text_buffer.getvalue()
    )

    # Set the downloaded filename.
    response.headers["Content-Disposition"] = (
        "attachment; filename=kdc-2026-results.csv"
    )

    # Identify the response as UTF-8 CSV.
    response.headers["Content-Type"] = (
        "text/csv; charset=utf-8"
    )

    return response


# ============================================================
# SECTION 20B: PARTICIPANTS AND INDIVIDUAL SCORES (ADMIN)
# ============================================================


# ------------------------------------------------------------
# Add a participant manually
# ------------------------------------------------------------
#
# URL: POST /admin/participants
#
# In a division deployment the gender is fixed by the division.

@app.route("/admin/participants", methods=["POST"])
@admin_required
def add_participant():

    name = clean_name(
        request.form.get("name", "")
    )

    age = parse_age(
        request.form.get("age")
    )

    gender = (
        DIVISION_INFO["gender"]
        if DIVISION_INFO
        else normalize_gender(
            request.form.get("gender", "")
        )
    )

    if not name:

        flash("Child name is required.", "error")

    elif not gender:

        flash("Choose a gender.", "error")

    elif Participant.query.filter_by(
        name_key=name.lower()
    ).first():

        flash(
            "That child is already in the list.",
            "error",
        )

    else:

        db.session.add(
            Participant(
                name=name,
                name_key=name.lower(),
                gender=gender,
                age=age,
            )
        )

        log_action(
            session["admin_username"],
            "Added participant",
            name,
        )

        db.session.commit()

        flash(f"{name} added.", "success")

    return redirect(
        url_for("admin_dashboard") + "#participants"
    )


# ------------------------------------------------------------
# Activate or deactivate a participant
# ------------------------------------------------------------

@app.route(
    "/admin/participants/<int:participant_id>/toggle",
    methods=["POST"],
)
@admin_required
def toggle_participant(participant_id):

    person = db.get_or_404(
        Participant,
        participant_id,
    )

    person.active = not person.active

    log_action(
        session["admin_username"],
        "Toggled participant",
        f"{person.name}: active={person.active}",
    )

    db.session.commit()

    return redirect(
        url_for("admin_dashboard") + "#participants"
    )


# ------------------------------------------------------------
# Correct an individual score
# ------------------------------------------------------------

@app.route(
    "/admin/individual-scores/<int:score_id>/edit",
    methods=["POST"],
)
@admin_required
def edit_individual_score(score_id):

    score = db.get_or_404(
        IndividualScore,
        score_id,
    )

    points = request.form.get(
        "points",
        type=int,
    )

    if points not in allowed_points_for_game(score.game):

        flash("Invalid point value.", "error")

    else:

        old = score.points

        score.points = points
        score.updated_by = session["admin_username"]
        score.updated_at = datetime.utcnow()

        log_action(
            session["admin_username"],
            "Edited individual score",
            (
                f"Game {score.game.number}, "
                f"{score.participant.name}: "
                f"{old} -> {points}"
            ),
        )

        db.session.commit()

        flash("Individual score updated.", "success")

    return redirect(
        url_for("admin_dashboard") + "#individual-scores"
    )


# ------------------------------------------------------------
# Remove an individual score (so it can be entered again)
# ------------------------------------------------------------

@app.route(
    "/admin/individual-scores/<int:score_id>/delete",
    methods=["POST"],
)
@admin_required
def delete_individual_score(score_id):

    score = db.get_or_404(
        IndividualScore,
        score_id,
    )

    log_action(
        session["admin_username"],
        "Deleted individual score",
        (
            f"Game {score.game.number}, "
            f"{score.participant.name}: "
            f"{score.points} points "
            f"(entered by {score.entered_by})"
        ),
    )

    db.session.delete(score)

    db.session.commit()

    flash("Individual score removed.", "success")

    return redirect(
        url_for("admin_dashboard") + "#individual-scores"
    )


# ------------------------------------------------------------
# Export the individual leaderboard
# ------------------------------------------------------------
#
# URL: GET /individual-results.csv   (administrator only)

@app.route("/individual-results.csv")
@admin_required
def export_individual_csv():

    import csv
    import io

    from flask import make_response

    text_buffer = io.StringIO()

    writer = csv.writer(text_buffer)

    games = Game.query.order_by(
        Game.number
    ).all()

    writer.writerow(
        ["Rank", "Child", "Gender", "Age"]
        + [f"Game {game.number}" for game in games]
        + ["Total"]
    )

    for row in individual_leaderboard_data():

        writer.writerow(
            [
                row["rank"],
                row["name"],
                row["gender"],
                row["age"] if row["age"] is not None else "",
            ]
            + [
                row["games"].get(str(game.number), 0)
                for game in games
            ]
            + [row["total"]]
        )

    response = make_response(
        text_buffer.getvalue()
    )

    suffix = f"-{DIVISION}" if DIVISION else ""

    response.headers["Content-Disposition"] = (
        f"attachment; filename=kdc-2026{suffix}-individual-results.csv"
    )

    response.headers["Content-Type"] = (
        "text/csv; charset=utf-8"
    )

    return response


# ============================================================
# SECTION 21: HEALTH CHECK ENDPOINT
# ============================================================
#
# URL: GET /health
#
# Returns a small JSON response indicating that the
# application process can respond to HTTP requests.
#
# This is useful for basic uptime checks.
#
# NOTE:
# It does not verify database connectivity.

@app.route("/health")
def health():

    return jsonify({
        "status": "ok",
        "division": DIVISION,
    })


# ============================================================
# SECTION 22: DATABASE INITIALIZATION
# ============================================================
#
# Create database tables that do not already exist.
#
# This does not:
# - Create the initial administrator.
# - Populate the game list.
# - Update existing tables after model changes.
#
# The administrator and initial games are created through
# the /setup route.
#
# DEVELOPMENT NOTE:
# Running create_all() during module import is convenient
# for a small local application.
#
# PRODUCTION NOTE:
# Prefer explicit database migrations and a separate
# deployment initialization process for production systems.

def ensure_division_marker():
    """Tie this database to its division (see AppMeta)."""

    if DIVISION is None:
        return

    marker = db.session.get(AppMeta, "division")

    if marker is None:

        try:

            db.session.add(
                AppMeta(key="division", value=DIVISION)
            )

            db.session.commit()

            return

        except IntegrityError:

            # Another worker wrote it first; re-check below.
            db.session.rollback()

            marker = db.session.get(AppMeta, "division")

    if marker.value != DIVISION:

        raise RuntimeError(
            f"This database belongs to the '{marker.value}' division, "
            f"but KDC_DIVISION='{DIVISION}'. Refusing to start so the "
            "Boys and Girls data are never mixed. Check your "
            "database settings."
        )


def init_database():
    """Create missing tables, tag the division, optional participant import."""

    with app.app_context():

        # Adds only the tables that do not exist yet (participant,
        # individual_score, app_meta). Existing tables and rows are untouched.
        db.create_all()

        ensure_division_marker()

        # Optional: import children from the Excel file on start-up
        # (useful on hosting services without a shell). Set
        # KDC_AUTO_IMPORT=1 and optionally PARTICIPANTS_FILE.
        if os.environ.get("KDC_AUTO_IMPORT", "0") == "1":

            _file = os.environ.get(
                "PARTICIPANTS_FILE",
                os.path.join(BASE_DIR, "data", "KDC.xlsx"),
            )

            if os.path.isfile(_file):

                try:

                    _log(
                        "Auto-import: "
                        + str(import_participants_from_xlsx(_file))
                    )

                except Exception as exc:  # keep the site up

                    db.session.rollback()

                    _log(f"Auto-import failed: {exc}")



# Tooling (migrate_legacy.py) sets KDC_SKIP_INIT=1 so it can copy the
# original database into a brand-new file before tables are created.
if os.environ.get("KDC_SKIP_INIT", "0") != "1":

    init_database()


# ============================================================
# SECTION 23: START THE APPLICATION
# ============================================================
#
# This block runs only when this file is executed directly.
#
# Environment variables:
#
# FLASK_DEBUG=1
#     Enables Flask's development debug mode.
#
# PORT=5000
#     Selects the HTTP port.
#
# IMPORTANT:
# Never expose Flask's development server or enable debug
# mode in a production deployment.

if __name__ == "__main__":

    app.run(

        # Enable debug mode only when explicitly requested.
        debug=(
            os.getenv("FLASK_DEBUG", "0") == "1"
        ),

        # Listen on all network interfaces.
        # Appropriate for local network testing, but restrict
        # access through network/firewall settings as needed.
        host="0.0.0.0",

        # Use the configured port, defaulting to 5000.
        port=int(
            os.getenv("PORT", "5000")
        ),
    )