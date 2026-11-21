from contextlib import contextmanager
from datetime import date, datetime, timedelta
from functools import wraps
import os
from pathlib import Path
import secrets
import sqlite3
import string
import base64
import binascii

from flask import Flask, jsonify, render_template, request, send_from_directory, session
from werkzeug.security import check_password_hash, generate_password_hash


ROOT = Path(__file__).resolve().parent
DATABASE = ROOT / "data" / "civic_track.db"
SESSION_SECRET_FILE = ROOT / "data" / "session_secret.key"
SESSION_LIFETIME = timedelta(days=14)


def load_secret_key():
    configured_secret = os.environ.get("CIVIC_TRACK_SECRET")
    if configured_secret is not None:
        if not configured_secret:
            raise RuntimeError("CIVIC_TRACK_SECRET must not be empty.")
        return configured_secret

    SESSION_SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        with SESSION_SECRET_FILE.open("x", encoding="ascii") as secret_file:
            secret_file.write(secrets.token_hex(32))
    except FileExistsError:
        pass

    secret = SESSION_SECRET_FILE.read_text(encoding="ascii").strip()
    if not secret:
        raise RuntimeError(f"The session signing key file is empty: {SESSION_SECRET_FILE}")
    return secret


app = Flask(__name__)
app.secret_key = load_secret_key()
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=SESSION_LIFETIME,
    SESSION_REFRESH_EACH_REQUEST=True,
)


@contextmanager
def connect_db():
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def add_column(db, table, column, declaration):
    columns = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")


def initialize_db():
    with connect_db() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS profiles (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                full_name TEXT NOT NULL DEFAULT '',
                birthdate TEXT NOT NULL DEFAULT '',
                email TEXT NOT NULL DEFAULT '',
                phone TEXT NOT NULL DEFAULT '',
                username TEXT NOT NULL DEFAULT '',
                password_hash TEXT NOT NULL DEFAULT '',
                photo TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_login TEXT
            );
            INSERT OR IGNORE INTO profiles (id) VALUES (1);
            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                theme TEXT NOT NULL DEFAULT '#20b9b2',
                font_scale REAL NOT NULL DEFAULT 1,
                notifications INTEGER NOT NULL DEFAULT 0,
                reminder_time TEXT NOT NULL DEFAULT '18:00',
                period TEXT NOT NULL DEFAULT 'all',
                impact_rate REAL NOT NULL DEFAULT 20
            );
            INSERT OR IGNORE INTO settings (id) VALUES (1);
            CREATE TABLE IF NOT EXISTS volunteer_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                activity TEXT NOT NULL,
                location TEXT NOT NULL,
                hours REAL NOT NULL CHECK (hours > 0 AND hours <= 24),
                advisor TEXT NOT NULL DEFAULT '',
                proof_photo TEXT NOT NULL DEFAULT '',
                organization TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_hours REAL NOT NULL CHECK (target_hours > 0),
                starts_on TEXT NOT NULL,
                ends_on TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                subject TEXT NOT NULL,
                due_date TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                completed_at TEXT,
                reminder_at TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS badges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                earned_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                pinned INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS organizations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'Organization'
            );
            CREATE TABLE IF NOT EXISTS signatures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                image TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        add_column(db, "volunteer_logs", "proof_photo", "TEXT NOT NULL DEFAULT ''")
        add_column(db, "volunteer_logs", "organization", "TEXT NOT NULL DEFAULT ''")
        add_column(db, "assignments", "reminder_at", "TEXT NOT NULL DEFAULT ''")
        add_column(db, "badges", "pinned", "INTEGER NOT NULL DEFAULT 0")
        # Migrate the original single-user demo data to its default local profile.
        db.execute(
            "UPDATE profiles SET full_name = 'Civic Track Demo', username = 'demo' "
            "WHERE full_name = '' AND EXISTS (SELECT 1 FROM volunteer_logs)"
        )


def error(message, status=400):
    return jsonify({"error": message}), status


def authenticated(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with connect_db() as db:
            profile = db.execute("SELECT password_hash FROM profiles WHERE id = 1").fetchone()
        if not profile or not profile["password_hash"] or not session.get("authenticated"):
            return error("Please sign in to continue.", 401)
        return function(*args, **kwargs)
    return wrapped


def parse_date(value, field):
    if not isinstance(value, str):
        raise ValueError(f"{field} is required.")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be a valid date.") from exc


def total_hours(db, start=None, end=None):
    conditions, values = [], []
    if start:
        conditions.append("date >= ?")
        values.append(start.isoformat())
    if end:
        conditions.append("date <= ?")
        values.append(end.isoformat())
    where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    row = db.execute(
        f"SELECT COALESCE(SUM(hours), 0) AS hours FROM volunteer_logs{where}",
        values,
    ).fetchone()
    return round(row["hours"], 2)


def current_goal(db):
    today = date.today().isoformat()
    return db.execute(
        "SELECT * FROM goals WHERE starts_on <= ? AND ends_on >= ? ORDER BY id DESC LIMIT 1",
        (today, today),
    ).fetchone()


def award_badges(db):
    hours = total_hours(db)
    milestones = [10, 25, 50] + list(range(100, int(hours // 50) * 50 + 1, 50))
    for milestone in milestones:
        if hours >= milestone:
            db.execute(
                "INSERT OR IGNORE INTO badges (name) VALUES (?)",
                (f"{milestone}-hour milestone",),
            )
    goal = current_goal(db)
    if goal and total_hours(
        db, date.fromisoformat(goal["starts_on"]), date.fromisoformat(goal["ends_on"])
    ) >= goal["target_hours"]:
        db.execute(
            "INSERT OR IGNORE INTO badges (name) VALUES (?)",
            (f"Personal goal #{goal['id']}: {goal['target_hours']:g} hours",),
        )


def serialize_rows(rows):
    return [dict(row) for row in rows]


def make_code():
    return "".join(secrets.choice(string.digits) for _ in range(6))


def valid_image_data(value, max_size=2_000_000):
    if not isinstance(value, str) or len(value) > max_size:
        return False
    try:
        header, encoded = value.split(",", 1)
        image = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        return False
    if len(image) > 1_500_000:
        return False
    if header == "data:image/png;base64":
        return image.startswith(b"\x89PNG\r\n\x1a\n")
    if header == "data:image/jpeg;base64":
        return image.startswith(b"\xff\xd8\xff")
    if header == "data:image/webp;base64":
        return image.startswith(b"RIFF") and image[8:12] == b"WEBP"
    return False


@app.get("/")
def home():
    return render_template("index.html")


@app.get("/sw.js")
def service_worker():
    response = send_from_directory(app.static_folder, "sw.js")
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/api/auth/status")
def auth_status():
    with connect_db() as db:
        profile = db.execute("SELECT * FROM profiles WHERE id = 1").fetchone()
    has_account = bool(profile["password_hash"])
    last_login = profile["last_login"]
    recent = False
    if last_login:
        try:
            recent = datetime.fromisoformat(last_login) > datetime.now() - timedelta(days=30)
        except ValueError:
            recent = False
    signed_in = bool(session.get("authenticated") and has_account)
    return jsonify({
        "has_account": has_account,
        "signed_in": signed_in,
        "recent_login": recent,
        "profile": {
            "full_name": profile["full_name"], "username": profile["username"],
            "photo": profile["photo"],
        } if signed_in else None,
    })


@app.post("/api/auth/signup")
def signup():
    data = request.get_json(silent=True) or {}
    full_name = str(data.get("full_name", "")).strip()
    username = str(data.get("username", "")).strip()
    email = str(data.get("email", "")).strip()
    phone = str(data.get("phone", "")).strip()
    birthdate = data.get("birthdate", "")
    password = data.get("password", "")
    photo = data.get("photo", "")
    try:
        birthday = parse_date(birthdate, "Birthdate")
    except ValueError as exc:
        return error(str(exc))
    if not full_name or not username or not password or not (email or phone):
        return error("Name, username, password, and email or phone are required.")
    if birthday > date.today():
        return error("Birthdate cannot be in the future.")
    if len(password) < 8:
        return error("Use a password with at least 8 characters.")
    if photo and not valid_image_data(photo):
        return error("Choose a PNG, JPEG, or WebP image smaller than 1.5 MB.")
    if len(username) > 60 or len(full_name) > 120 or len(email) > 254 or len(phone) > 40:
        return error("One of the fields is too long.")
    with connect_db() as db:
        profile = db.execute("SELECT password_hash FROM profiles WHERE id = 1").fetchone()
        if profile["password_hash"]:
            return error("An account already exists here. Use Log In instead.", 409)
        db.execute(
            "UPDATE profiles SET full_name=?, birthdate=?, email=?, phone=?, username=?, "
            "password_hash=?, photo=?, last_login=? WHERE id=1",
            (full_name, birthday.isoformat(), email, phone, username,
             generate_password_hash(password), photo,
             datetime.now().isoformat(timespec="seconds")),
        )
    session["authenticated"] = True
    session.permanent = True
    return jsonify({"message": "Account created."}), 201


@app.post("/api/auth/login")
def login():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    password = data.get("password", "")
    with connect_db() as db:
        profile = db.execute("SELECT * FROM profiles WHERE id = 1").fetchone()
        if not profile["password_hash"]:
            return error("Create your account first.")
        if username.casefold() != profile["username"].casefold() or not check_password_hash(
            profile["password_hash"], password
        ):
            return error("Username or password is incorrect.", 401)
        db.execute(
            "UPDATE profiles SET last_login=? WHERE id=1",
            (datetime.now().isoformat(timespec="seconds"),),
        )
    session["authenticated"] = True
    session.permanent = True
    return jsonify({"message": "Signed in."})


@app.post("/api/auth/logout")
def logout():
    session.clear()
    return jsonify({"message": "Signed out."})


@app.post("/api/auth/code")
def request_code():
    data = request.get_json(silent=True) or {}
    purpose = data.get("purpose")
    if purpose not in {"reset", "change"}:
        return error("Choose a supported verification purpose.")
    with connect_db() as db:
        profile = db.execute("SELECT email, phone, password_hash FROM profiles WHERE id=1").fetchone()
    if not profile["password_hash"]:
        return error("No account exists here.")
    if purpose == "change" and not session.get("authenticated"):
        return error("Sign in before changing your password.", 401)
    contact = profile["email"] or profile["phone"]
    if not contact:
        return error("Add an email address or phone number to your profile first.")
    code = make_code()
    session["verification"] = {
        "code": code, "purpose": purpose,
        "expires": (datetime.now() + timedelta(minutes=2)).isoformat(),
    }
    # Return the code here instead of implying it was delivered to the contact.
    return jsonify({
        "message": f"Verification code for {contact} (not sent):",
        "demo_code": code,
        "expires_in_seconds": 120,
    })


@app.post("/api/auth/reset")
def reset_password():
    data = request.get_json(silent=True) or {}
    verification = session.get("verification", {})
    try:
        expired = datetime.now() >= datetime.fromisoformat(verification.get("expires", ""))
    except ValueError:
        expired = True
    if verification.get("purpose") != "reset" or expired or data.get("code") != verification.get("code"):
        return error("The code is invalid or expired. Request a new code.")
    password = data.get("password", "")
    if not isinstance(password, str) or len(password) < 8:
        return error("Use a password with at least 8 characters.")
    with connect_db() as db:
        db.execute("UPDATE profiles SET password_hash=? WHERE id=1", (generate_password_hash(password),))
    session.pop("verification", None)
    session["authenticated"] = True
    session.permanent = True
    return jsonify({"message": "Password reset. You are signed in."})


@app.post("/api/auth/change-password")
@authenticated
def change_password():
    data = request.get_json(silent=True) or {}
    verification = session.get("verification", {})
    try:
        expired = datetime.now() >= datetime.fromisoformat(verification.get("expires", ""))
    except ValueError:
        expired = True
    if verification.get("purpose") != "change" or expired or data.get("code") != verification.get("code"):
        return error("The code is invalid or expired. Request a new code.")
    new_password = data.get("new_password", "")
    with connect_db() as db:
        profile = db.execute("SELECT password_hash FROM profiles WHERE id=1").fetchone()
        if not check_password_hash(profile["password_hash"], data.get("current_password", "")):
            return error("Current password is incorrect.")
        if not isinstance(new_password, str) or len(new_password) < 8:
            return error("Use a new password with at least 8 characters.")
        db.execute("UPDATE profiles SET password_hash=? WHERE id=1", (generate_password_hash(new_password),))
    session.pop("verification", None)
    return jsonify({"message": "Password changed."})


@app.get("/api/dashboard")
@authenticated
def dashboard():
    period = request.args.get("period", "all")
    today = date.today()
    starts = {
        "week": today - timedelta(days=today.weekday()),
        "month": today.replace(day=1),
        "year": today.replace(month=1, day=1),
        "all": None,
    }
    if period not in starts:
        return error("Choose week, month, year, or all.")
    with connect_db() as db:
        start = starts[period]
        hours = total_hours(db, start)
        overall_hours = total_hours(db)
        completed = db.execute(
            "SELECT COUNT(*) AS count FROM assignments WHERE completed_at IS NOT NULL"
        ).fetchone()["count"]
        on_time = db.execute(
            "SELECT COUNT(*) AS count FROM assignments "
            "WHERE completed_at IS NOT NULL AND date(completed_at) <= due_date"
        ).fetchone()["count"]
        assignment_count = db.execute("SELECT COUNT(*) AS count FROM assignments").fetchone()["count"]
        upcoming = db.execute(
            "SELECT * FROM assignments WHERE completed_at IS NULL ORDER BY due_date LIMIT 6"
        ).fetchall()
        goal = current_goal(db)
        goal_data = None
        if goal:
            progress = total_hours(db, date.fromisoformat(goal["starts_on"]), date.fromisoformat(goal["ends_on"]))
            goal_data = {
                "target": goal["target_hours"], "progress": progress,
                "starts_on": goal["starts_on"], "ends_on": goal["ends_on"],
                "percent": min(100, round(progress / goal["target_hours"] * 100)),
            }
        badges = db.execute("SELECT * FROM badges ORDER BY earned_at DESC LIMIT 6").fetchall()
        badge_count = db.execute("SELECT COUNT(*) AS count FROM badges").fetchone()["count"]
        setting = db.execute("SELECT * FROM settings WHERE id=1").fetchone()
        next_badge = 10 if overall_hours < 10 else 25 if overall_hours < 25 else 50 if overall_hours < 50 else (int(overall_hours // 50) + 1) * 50
        previous_badge = 0 if overall_hours < 10 else 10 if overall_hours < 25 else 25 if overall_hours < 50 else int(overall_hours // 50) * 50
    next_milestone = next_badge
    return jsonify({
        "period": period, "hours": hours, "overall_hours": overall_hours,
        "completed_assignments": completed, "on_time_assignments": on_time,
        "assignment_count": assignment_count,
        "assignment_percent": round(completed / assignment_count * 100) if assignment_count else 0,
        "badge_count": badge_count, "upcoming": serialize_rows(upcoming),
        "goal": goal_data, "badges": serialize_rows(badges),
        "next_milestone": next_milestone, "hours_to_milestone": round(max(0, next_milestone - overall_hours), 2),
        "milestone_progress": min(100, round((overall_hours - previous_badge) / (next_milestone - previous_badge) * 100)),
        "impact_value": round(overall_hours * setting["impact_rate"], 2),
        "impact_rate": setting["impact_rate"],
    })


@app.route("/api/volunteer", methods=["GET", "POST"])
@authenticated
def volunteer():
    if request.method == "GET":
        with connect_db() as db:
            rows = db.execute("SELECT * FROM volunteer_logs ORDER BY date DESC, id DESC LIMIT 200").fetchall()
            goal = current_goal(db)
        return jsonify({"entries": serialize_rows(rows), "goal": dict(goal) if goal else None})
    data = request.get_json(silent=True) or {}
    try:
        entry_date = parse_date(data.get("date"), "Date")
        activity, location = str(data.get("activity", "")).strip(), str(data.get("location", "")).strip()
        hours, advisor = float(data.get("hours", "")), str(data.get("advisor", "")).strip()
        organization = str(data.get("organization", "")).strip()
        photo = data.get("proof_photo", "")
        if not activity or not location:
            return error("Activity and location are required.")
        if entry_date > date.today():
            return error("Volunteer hours cannot be logged for a future date.")
        if not 0 < hours <= 24:
            return error("Hours must be greater than 0 and no more than 24.")
        if organization and len(organization) > 120:
            return error("Organization name is too long.")
        if photo and not valid_image_data(photo):
            return error("Photo must be a PNG, JPEG, or WebP image smaller than 1.5 MB.")
    except (ValueError, TypeError):
        return error("Enter a valid date and number of hours.")
    with connect_db() as db:
        if organization and not db.execute(
            "SELECT 1 FROM organizations WHERE name=?", (organization,)
        ).fetchone():
            return error("Choose an organization from your saved affiliations.")
        cursor = db.execute(
            "INSERT INTO volunteer_logs (date, activity, location, hours, advisor, proof_photo, organization) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (entry_date.isoformat(), activity, location, hours, advisor, photo, organization),
        )
        award_badges(db)
        row = db.execute("SELECT * FROM volunteer_logs WHERE id=?", (cursor.lastrowid,)).fetchone()
    return jsonify(dict(row)), 201


@app.post("/api/goals")
@authenticated
def set_goal():
    data = request.get_json(silent=True) or {}
    try:
        target = float(data.get("target", ""))
        start, end = parse_date(data.get("starts_on"), "Start date"), parse_date(data.get("ends_on"), "End date")
        if target <= 0 or end < start:
            return error("Set a positive goal and an end date on or after the start date.")
    except (ValueError, TypeError):
        return error("Enter a valid goal and date range.")
    with connect_db() as db:
        db.execute("INSERT INTO goals (target_hours, starts_on, ends_on) VALUES (?, ?, ?)", (target, start.isoformat(), end.isoformat()))
        award_badges(db)
    return jsonify({"message": "Goal saved."}), 201


@app.route("/api/assignments", methods=["GET", "POST"])
@authenticated
def assignments():
    if request.method == "GET":
        with connect_db() as db:
            rows = db.execute("SELECT * FROM assignments ORDER BY completed_at IS NOT NULL, due_date, id").fetchall()
        return jsonify({"assignments": serialize_rows(rows)})
    data = request.get_json(silent=True) or {}
    title, subject = str(data.get("title", "")).strip(), str(data.get("subject", "")).strip()
    description, reminder_at = str(data.get("description", "")).strip(), str(data.get("reminder_at", "")).strip()
    try:
        due_date = parse_date(data.get("due_date"), "Due date")
        if reminder_at:
            datetime.fromisoformat(reminder_at)
    except ValueError as exc:
        return error(str(exc) if "Due date" in str(exc) else "Reminder must be a valid date and time.")
    if not title or not subject:
        return error("Assignment name and subject are required.")
    with connect_db() as db:
        cursor = db.execute(
            "INSERT INTO assignments (title, subject, due_date, description, reminder_at) VALUES (?, ?, ?, ?, ?)",
            (title, subject, due_date.isoformat(), description, reminder_at),
        )
        row = db.execute("SELECT * FROM assignments WHERE id=?", (cursor.lastrowid,)).fetchone()
    return jsonify(dict(row)), 201


@app.patch("/api/assignments/<int:assignment_id>")
@authenticated
def complete_assignment(assignment_id):
    data = request.get_json(silent=True) or {}
    if data.get("completed") is not True:
        return error("Only marking an assignment complete is supported.")
    with connect_db() as db:
        cursor = db.execute(
            "UPDATE assignments SET completed_at=? WHERE id=? AND completed_at IS NULL",
            (datetime.now().isoformat(timespec="seconds"), assignment_id),
        )
        row = db.execute("SELECT * FROM assignments WHERE id=?", (assignment_id,)).fetchone()
        if not row:
            return error("Assignment not found.", 404)
    return jsonify(dict(row))


@app.get("/api/badges")
@authenticated
def badges():
    with connect_db() as db:
        rows = db.execute("SELECT * FROM badges ORDER BY earned_at DESC").fetchall()
    return jsonify({"badges": serialize_rows(rows)})


@app.patch("/api/badges/<int:badge_id>")
@authenticated
def pin_badge(badge_id):
    data = request.get_json(silent=True) or {}
    pinned = bool(data.get("pinned"))
    with connect_db() as db:
        badge = db.execute("SELECT id, pinned FROM badges WHERE id=?", (badge_id,)).fetchone()
        if not badge:
            return error("Badge not found.", 404)
        pinned_count = db.execute("SELECT COUNT(*) AS count FROM badges WHERE pinned=1").fetchone()["count"]
        if pinned and not badge["pinned"] and pinned_count >= 3:
            return error("Unpin a badge before choosing a different favorite.")
        db.execute("UPDATE badges SET pinned=? WHERE id=?", (int(pinned), badge_id))
    return jsonify({"message": "Badge showcase updated."})


@app.get("/api/profile")
@authenticated
def get_profile():
    with connect_db() as db:
        row = db.execute("SELECT full_name, birthdate, email, phone, username, photo FROM profiles WHERE id=1").fetchone()
        organizations = db.execute("SELECT * FROM organizations ORDER BY name").fetchall()
        signatures = db.execute("SELECT id, name, image, created_at FROM signatures ORDER BY created_at DESC").fetchall()
        pinned = db.execute("SELECT * FROM badges WHERE pinned=1 ORDER BY earned_at DESC").fetchall()
    return jsonify({
        "profile": dict(row), "organizations": serialize_rows(organizations),
        "signatures": serialize_rows(signatures), "pinned_badges": serialize_rows(pinned),
    })


@app.put("/api/profile")
@authenticated
def update_profile():
    data = request.get_json(silent=True) or {}
    full_name, username = str(data.get("full_name", "")).strip(), str(data.get("username", "")).strip()
    email, phone, birthdate = str(data.get("email", "")).strip(), str(data.get("phone", "")).strip(), data.get("birthdate", "")
    photo = data.get("photo", "")
    if not full_name or not username or not (email or phone):
        return error("Name, username, and email or phone are required.")
    try:
        birthday = parse_date(birthdate, "Birthdate")
    except ValueError as exc:
        return error(str(exc))
    if birthday > date.today():
        return error("Birthdate cannot be in the future.")
    if photo and not valid_image_data(photo):
        return error("Choose a PNG, JPEG, or WebP image smaller than 1.5 MB.")
    with connect_db() as db:
        db.execute(
            "UPDATE profiles SET full_name=?, username=?, email=?, phone=?, birthdate=?, "
            "photo=CASE WHEN ? THEN '' WHEN ?!='' THEN ? ELSE photo END WHERE id=1",
            (full_name, username, email, phone, birthday.isoformat(),
             int(bool(data.get("remove_photo"))), photo, photo),
        )
    return jsonify({"message": "Profile updated."})


@app.route("/api/organizations", methods=["GET", "POST", "DELETE"])
@authenticated
def organizations():
    data = request.get_json(silent=True) or {}
    with connect_db() as db:
        if request.method == "GET":
            rows = db.execute("SELECT * FROM organizations ORDER BY name").fetchall()
            return jsonify({"organizations": serialize_rows(rows)})
        if request.method == "POST":
            name, kind = str(data.get("name", "")).strip(), str(data.get("kind", "Organization")).strip()
            if not name:
                return error("Enter an organization or school name.")
            db.execute("INSERT INTO organizations (name, kind) VALUES (?, ?)", (name[:120], kind[:60]))
        else:
            db.execute("DELETE FROM organizations WHERE id=?", (data.get("id"),))
    return jsonify({"message": "Organizations updated."})


@app.route("/api/signatures", methods=["POST", "DELETE"])
@authenticated
def signatures():
    data = request.get_json(silent=True) or {}
    with connect_db() as db:
        if request.method == "POST":
            name, image = str(data.get("name", "")).strip(), data.get("image", "")
            if not name or not valid_image_data(image):
                return error("Provide a label and a PNG, JPEG, or WebP image smaller than 1.5 MB.")
            db.execute("INSERT INTO signatures (name, image) VALUES (?, ?)", (name[:100], image))
        else:
            db.execute("DELETE FROM signatures WHERE id=?", (data.get("id"),))
    return jsonify({"message": "Signature vault updated."})


@app.get("/api/settings")
@authenticated
def get_settings():
    with connect_db() as db:
        return jsonify(dict(db.execute("SELECT * FROM settings WHERE id=1").fetchone()))


@app.put("/api/settings")
@authenticated
def update_settings():
    data = request.get_json(silent=True) or {}
    theme = str(data.get("theme", "#20b9b2"))
    if len(theme) != 7 or not theme.startswith("#") or any(ch not in "0123456789abcdefABCDEF" for ch in theme[1:]):
        return error("Choose a valid theme color.")
    try:
        scale, impact_rate = float(data.get("font_scale", 1)), float(data.get("impact_rate", 20))
        reminder_time = datetime.strptime(data.get("reminder_time", "18:00"), "%H:%M").strftime("%H:%M")
    except (ValueError, TypeError):
        return error("Enter a valid font size, impact estimate, and reminder time.")
    period = data.get("period", "all")
    if not 0.85 <= scale <= 1.3 or not 0 <= impact_rate <= 1000 or period not in {"all", "week", "month", "year"}:
        return error("A setting is outside its allowed range.")
    with connect_db() as db:
        db.execute(
            "UPDATE settings SET theme=?, font_scale=?, notifications=?, reminder_time=?, period=?, impact_rate=? WHERE id=1",
            (theme, scale, int(bool(data.get("notifications"))), reminder_time, period, impact_rate),
        )
    return jsonify({"message": "Settings saved."})


@app.get("/api/reports")
@authenticated
def reports():
    period = request.args.get("period", "all")
    today = date.today()
    starts = {
        "week": today - timedelta(days=today.weekday()),
        "month": today.replace(day=1),
        "year": today.replace(month=1, day=1),
        "all": None,
    }
    if period not in starts:
        return error("Choose week, month, year, or all.")
    start = starts[period]
    with connect_db() as db:
        profile = db.execute("SELECT full_name FROM profiles WHERE id=1").fetchone()
        hours = total_hours(db, start)
        entries = db.execute(
            "SELECT * FROM volunteer_logs WHERE (? IS NULL OR date >= ?) ORDER BY date",
            (start.isoformat() if start else None, start.isoformat() if start else None),
        ).fetchall()
        assignments = db.execute(
            "SELECT *, CASE WHEN completed_at IS NOT NULL AND date(completed_at) <= due_date THEN 1 ELSE 0 END AS on_time "
            "FROM assignments WHERE (? IS NULL OR date(created_at) >= ? OR date(completed_at) >= ?) ORDER BY due_date",
            (start.isoformat() if start else None, start.isoformat() if start else None, start.isoformat() if start else None),
        ).fetchall()
        completed = sum(bool(item["completed_at"]) for item in assignments)
        on_time = sum(bool(item["on_time"]) for item in assignments)
        organizations = db.execute("SELECT name, kind FROM organizations ORDER BY name").fetchall()
    return jsonify({
        "name": profile["full_name"], "hours": hours, "period": period,
        "assignments_total": len(assignments), "assignments_completed": completed,
        "assignments_on_time": on_time, "entries": serialize_rows(entries),
        "assignments": serialize_rows(assignments), "organizations": serialize_rows(organizations),
    })


@app.delete("/api/account")
@authenticated
def delete_account():
    data = request.get_json(silent=True) or {}
    with connect_db() as db:
        profile = db.execute("SELECT password_hash FROM profiles WHERE id=1").fetchone()
        if not check_password_hash(profile["password_hash"], data.get("password", "")):
            return error("Password is incorrect; account data was not deleted.")
        for table in ("volunteer_logs", "goals", "assignments", "badges", "organizations", "signatures"):
            db.execute(f"DELETE FROM {table}")
        db.execute("UPDATE profiles SET full_name='', birthdate='', email='', phone='', username='', password_hash='', photo='', last_login=NULL WHERE id=1")
        db.execute("UPDATE settings SET theme='#20b9b2', font_scale=1, notifications=0, reminder_time='18:00', period='all', impact_rate=20 WHERE id=1")
    session.clear()
    return jsonify({"message": "Account and saved data were deleted."})


initialize_db()


if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=False)
