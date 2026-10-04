
import os
import re
import secrets
import sqlite3
from datetime import date, datetime, timedelta
from functools import wraps

from flask import (Flask, abort, flash, g, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

# --------------------------------------------------------------------------
# App setup
# --------------------------------------------------------------------------
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)
# IMPORTANT: set NEONMIND_SECRET in the environment for real deployments.
app.config["SECRET_KEY"] = os.environ.get("NEONMIND_SECRET", "dev-only-change-me")
app.config["DATABASE"] = os.path.join(BASE_DIR, "neonmind.db")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# Mood options: key -> (emoji, label, score used for averages)
MOODS = {
    "happy":    ("😊", "Happy", 5),
    "calm":     ("😌", "Calm", 4),
    "okay":     ("😐", "Okay", 3),
    "sad":      ("😔", "Sad", 2),
    "stressed": ("😰", "Stressed", 1),
}
PRIORITIES = ("low", "medium", "high")
THEMES = {"lime": "Neon lime", "cyan": "Ice cyan",
          "magenta": "Hot magenta", "amber": "Solar amber"}
# Sort high priority first in SQL
PRIORITY_ORDER = "CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# --------------------------------------------------------------------------
# Database helpers
# --------------------------------------------------------------------------
def get_db():
    """One SQLite connection per request, stored on Flask's `g` object."""
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row          # rows behave like dicts
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_error):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """Create the four tables if they do not exist yet."""
    db = sqlite3.connect(app.config["DATABASE"])
    db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            name          TEXT NOT NULL,
            email         TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            theme         TEXT NOT NULL DEFAULT 'lime',
            mode          TEXT NOT NULL DEFAULT 'dark',
            created_at    TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tasks (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title        TEXT NOT NULL,
            priority     TEXT NOT NULL DEFAULT 'medium',
            due_date     TEXT,
            completed    INTEGER NOT NULL DEFAULT 0,
            created_at   TEXT NOT NULL,
            completed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS diary (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title      TEXT NOT NULL,
            content    TEXT NOT NULL,
            mood       TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS moods (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            mood       TEXT NOT NULL,
            note       TEXT,
            created_at TEXT NOT NULL
        );
    """)
    db.commit()
    db.close()


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# --------------------------------------------------------------------------
# Auth, CSRF and template helpers
# --------------------------------------------------------------------------
@app.before_request
def load_user():
    """Attach the logged-in user (or None) to `g.user` for every request."""
    g.user = None
    user_id = session.get("user_id")
    if user_id:
        g.user = get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if g.user is None:
            session.clear()


@app.before_request
def csrf_protect():
    """Reject POST requests that do not carry our secret form token."""
    if request.method == "POST":
        token = session.get("csrf_token")
        if not token or token != request.form.get("csrf_token"):
            abort(400)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            flash("Please log in to continue.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


@app.context_processor
def inject_globals():
    def csrf_token():
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_hex(16)
        return session["csrf_token"]

    mood_list = [{"key": k, "emoji": v[0], "label": v[1]} for k, v in MOODS.items()]
    return {"user": g.get("user"), "csrf_token": csrf_token, "moods": mood_list,
            "mood_map": {k: {"emoji": v[0], "label": v[1]} for k, v in MOODS.items()},
            "themes": THEMES}


@app.template_filter("pretty_dt")
def pretty_dt(value):
    """'2026-10-04 18:30:00' -> '04 Oct 2026, 06:30 PM'"""
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").strftime("%d %b %Y, %I:%M %p")
    except (TypeError, ValueError):
        return value or ""


@app.template_filter("pretty_date")
def pretty_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%d %b %Y")
    except (TypeError, ValueError):
        return value or ""


@app.errorhandler(400)
def bad_request(_e):
    flash("Your session expired. Please try again.", "error")
    return redirect(url_for("dashboard") if g.get("user") else url_for("login"))


@app.errorhandler(404)
def not_found(_e):
    flash("That page does not exist.", "error")
    return redirect(url_for("dashboard") if g.get("user") else url_for("login"))


# --------------------------------------------------------------------------
# Data helpers (stats, charts, insights)
# --------------------------------------------------------------------------
def get_stats(user_id):
    db = get_db()
    total = db.execute("SELECT COUNT(*) FROM tasks WHERE user_id=?", (user_id,)).fetchone()[0]
    done = db.execute("SELECT COUNT(*) FROM tasks WHERE user_id=? AND completed=1", (user_id,)).fetchone()[0]
    entries = db.execute("SELECT COUNT(*) FROM diary WHERE user_id=?", (user_id,)).fetchone()[0]
    last = db.execute("SELECT mood FROM moods WHERE user_id=? ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()
    return {
        "total": total, "done": done, "pending": total - done,
        "productivity": round(done / total * 100) if total else 0,
        "entries": entries,
        "current_mood": last["mood"] if last else None,
    }


def week_data(user_id):
    """Tasks added vs completed for each of the last 7 days (for the chart)."""
    db = get_db()
    days = [date.today() - timedelta(days=i) for i in range(6, -1, -1)]
    start = days[0].isoformat()
    completed = dict(db.execute(
        "SELECT substr(completed_at,1,10), COUNT(*) FROM tasks "
        "WHERE user_id=? AND completed=1 AND completed_at>=? GROUP BY 1", (user_id, start)).fetchall())
    added = dict(db.execute(
        "SELECT substr(created_at,1,10), COUNT(*) FROM tasks "
        "WHERE user_id=? AND created_at>=? GROUP BY 1", (user_id, start)).fetchall())
    return [{"label": d.strftime("%a"), "date": d.isoformat(),
             "completed": completed.get(d.isoformat(), 0),
             "added": added.get(d.isoformat(), 0)} for d in days]


def mood_rows(user_id, days=None, limit=None):
    sql = "SELECT * FROM moods WHERE user_id=?"
    params = [user_id]
    if days:
        sql += " AND created_at >= ?"
        params.append((datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S"))
    sql += " ORDER BY id DESC"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return get_db().execute(sql, params).fetchall()


def mood_average(rows):
    """Return (average score, mood key nearest to that average) or (None, None)."""
    if not rows:
        return None, None
    avg = sum(MOODS[r["mood"]][2] for r in rows) / len(rows)
    nearest = min(MOODS, key=lambda k: abs(MOODS[k][2] - avg))
    return round(avg, 1), nearest


def mood_frequency(rows):
    counts = {k: 0 for k in MOODS}
    for r in rows:
        counts[r["mood"]] += 1
    total = len(rows)
    return [{"key": k, "emoji": MOODS[k][0], "label": MOODS[k][1], "count": c,
             "percent": round(c / total * 100) if total else 0} for k, c in counts.items()]


REFLECTION_PROMPTS = {
    "happy": "Good energy. What helped today go well? Write it down so you can repeat it.",
    "calm": "A steady mind is great for focused work. What is one meaningful task you could do now?",
    "okay": "A neutral day is still a fair day. What is one small win you could add to it?",
    "sad": "Heavy days happen. A short diary entry can help you sort your thoughts, and one gentle task may help tomorrow feel lighter.",
    "stressed": "Your mind is carrying a lot. Pick the one task that matters most and shrink it to a 10-minute first step.",
}


def reflection_insight(user_id, stats):
    """Personal Reflection Insight - simple rules, NOT a medical assessment."""
    recent = mood_rows(user_id, days=7)
    if not recent and stats["total"] == 0:
        return "Welcome to NeonMind. Log a mood and add a task to unlock your first Personal Reflection Insight."
    parts = []
    if recent:
        counts = mood_frequency(recent)
        top = max(counts, key=lambda c: c["count"])
        avg, _ = mood_average(recent)
        parts.append(f"Your most frequent mood this week is {top['label'].lower()} {top['emoji']} "
                     f"(average {avg}/5).")
        stressed = next(c for c in counts if c["key"] == "stressed")["count"]
        if stressed >= 2:
            parts.append("Stress showed up more than once. Try splitting big tasks into smaller steps.")
        elif avg >= 4 and stats["productivity"] >= 50:
            parts.append("Positive mood and steady progress: you seem to be in a good rhythm.")
        elif avg >= 4:
            parts.append("Your mood is good. It could be a great time to start your top-priority task.")
        elif avg < 3:
            parts.append("It looks like a tougher week. Be kind to yourself and keep today's plan small. "
                         "Talking with someone you trust can also help.")
    if stats["total"]:
        if stats["productivity"] >= 70:
            parts.append(f"You have completed {stats['productivity']}% of your tasks. Strong momentum!")
        elif stats["pending"]:
            parts.append(f"You have {stats['pending']} open task(s). Choosing just one to finish next is enough.")
    return " ".join(parts) or "Keep logging your moods and tasks to see patterns here."


def fetch_tasks(user_id, flt="all"):
    sql = "SELECT * FROM tasks WHERE user_id=?"
    params = [user_id]
    today = date.today().isoformat()
    if flt == "active":
        sql += " AND completed=0"
    elif flt == "completed":
        sql += " AND completed=1"
    elif flt == "high":
        sql += " AND completed=0 AND priority='high'"
    elif flt == "overdue":
        sql += " AND completed=0 AND due_date IS NOT NULL AND due_date < ?"
        params.append(today)
    sql += f" ORDER BY completed ASC, {PRIORITY_ORDER}, due_date IS NULL, due_date, id DESC"
    tasks = []
    for row in get_db().execute(sql, params).fetchall():
        t = dict(row)
        t["overdue"] = bool(not t["completed"] and t["due_date"] and t["due_date"] < today)
        tasks.append(t)
    return tasks


def valid_date(text):
    try:
        datetime.strptime(text, "%Y-%m-%d")
        return True
    except ValueError:
        return False


# --------------------------------------------------------------------------
# Auth routes
# --------------------------------------------------------------------------
@app.route("/")
def index():
    return redirect(url_for("dashboard" if g.user else "login"))


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if g.user:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        error = None
        if not name or len(name) > 60:
            error = "Enter your name (up to 60 characters)."
        elif not EMAIL_RE.match(email):
            error = "Enter a valid email address."
        elif len(password) < 8:
            error = "Password must be at least 8 characters."
        elif password != confirm:
            error = "Passwords do not match."
        elif get_db().execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            error = "An account with this email already exists. Try logging in."
        if error:
            flash(error, "error")
            return render_template("signup.html", form={"name": name, "email": email})
        db = get_db()
        cur = db.execute(
            "INSERT INTO users (name, email, password_hash, created_at) VALUES (?,?,?,?)",
            (name, email, generate_password_hash(password), now_str()))
        db.commit()
        session.clear()
        session["user_id"] = cur.lastrowid
        flash(f"Welcome to NeonMind, {name.split()[0]}!", "success")
        return redirect(url_for("dashboard"))
    return render_template("signup.html", form={})


@app.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        row = get_db().execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if row and check_password_hash(row["password_hash"], password):
            session.clear()
            session["user_id"] = row["id"]
            return redirect(url_for("dashboard"))
        flash("Email or password is incorrect.", "error")
        return render_template("login.html", form={"email": email})
    return render_template("login.html", form={})


@app.route("/logout", methods=["GET", "POST"])
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------
@app.route("/dashboard")
@login_required
def dashboard():
    uid = g.user["id"]
    hour = datetime.now().hour
    greeting = "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening"
    stats = get_stats(uid)
    focus = [t for t in fetch_tasks(uid, "active")][:4]    # top open tasks
    return render_template(
        "dashboard.html", greeting=greeting, first_name=g.user["name"].split()[0],
        today=datetime.now().strftime("%A, %d %B %Y"), stats=stats, focus=focus,
        insight=reflection_insight(uid, stats))


# --------------------------------------------------------------------------
# Tasks
# --------------------------------------------------------------------------
@app.route("/tasks", methods=["GET", "POST"])
@login_required
def tasks():
    uid = g.user["id"]
    db = get_db()
    if request.method == "POST":
        action = request.form.get("action")
        flt = request.form.get("filter", "all")
        back = request.form.get("next")
        target = url_for("dashboard") if back == "dashboard" else url_for("tasks", filter=flt)
        task_id = request.form.get("id", type=int)

        if action in ("add", "edit"):
            title = request.form.get("title", "").strip()
            priority = request.form.get("priority", "medium")
            due = request.form.get("due_date", "").strip() or None
            if not title or len(title) > 120:
                flash("Task title is required (up to 120 characters).", "error")
                return redirect(target)
            if priority not in PRIORITIES:
                priority = "medium"
            if due and not valid_date(due):
                flash("That due date is not valid.", "error")
                return redirect(target)
            if action == "add":
                db.execute("INSERT INTO tasks (user_id,title,priority,due_date,created_at) VALUES (?,?,?,?,?)",
                           (uid, title, priority, due, now_str()))
                flash("Task added.", "success")
            else:
                db.execute("UPDATE tasks SET title=?, priority=?, due_date=? WHERE id=? AND user_id=?",
                           (title, priority, due, task_id, uid))
                flash("Task updated.", "success")
        elif action == "toggle":
            row = db.execute("SELECT completed FROM tasks WHERE id=? AND user_id=?", (task_id, uid)).fetchone()
            if row:
                now_done = 0 if row["completed"] else 1
                db.execute("UPDATE tasks SET completed=?, completed_at=? WHERE id=? AND user_id=?",
                           (now_done, now_str() if now_done else None, task_id, uid))
        elif action == "delete":
            db.execute("DELETE FROM tasks WHERE id=? AND user_id=?", (task_id, uid))
            flash("Task deleted.", "success")
        db.commit()
        return redirect(target)

    flt = request.args.get("filter", "all")
    if flt not in ("all", "active", "completed", "high", "overdue"):
        flt = "all"
    counts = {f: len(fetch_tasks(uid, f)) for f in ("all", "active", "completed", "high", "overdue")}
    return render_template("tasks.html", items=fetch_tasks(uid, flt), flt=flt, counts=counts,
                           stats=get_stats(uid), today=date.today().isoformat())


# --------------------------------------------------------------------------
# Diary
# --------------------------------------------------------------------------
@app.route("/diary", methods=["GET", "POST"])
@login_required
def diary():
    uid = g.user["id"]
    db = get_db()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add":
            title = request.form.get("title", "").strip()
            content = request.form.get("content", "").strip()
            mood = request.form.get("mood") or None
            if mood not in MOODS:
                mood = None
            if not title or not content:
                flash("Add a title and some text before saving.", "error")
            elif len(title) > 100 or len(content) > 10000:
                flash("Entry is too long (title 100, text 10,000 characters).", "error")
            else:
                db.execute("INSERT INTO diary (user_id,title,content,mood,created_at) VALUES (?,?,?,?,?)",
                           (uid, title, content, mood, now_str()))
                db.commit()
                flash("Diary entry saved.", "success")
        elif action == "delete":
            db.execute("DELETE FROM diary WHERE id=? AND user_id=?", (request.form.get("id", type=int), uid))
            db.commit()
            flash("Entry deleted.", "success")
        return redirect(url_for("diary"))
    entries = db.execute("SELECT * FROM diary WHERE user_id=? ORDER BY id DESC", (uid,)).fetchall()
    return render_template("diary.html", entries=entries)


# --------------------------------------------------------------------------
# Mood tracker
# --------------------------------------------------------------------------
@app.route("/mood", methods=["GET", "POST"])
@login_required
def mood():
    uid = g.user["id"]
    db = get_db()
    if request.method == "POST":
        action = request.form.get("action", "save")
        if action == "delete":
            db.execute("DELETE FROM moods WHERE id=? AND user_id=?", (request.form.get("id", type=int), uid))
            db.commit()
            flash("Mood entry removed.", "success")
            return redirect(url_for("mood"))
        chosen = request.form.get("mood")
        if chosen not in MOODS:
            flash("Pick a mood first.", "error")
        else:
            note = request.form.get("note", "").strip()[:200] or None
            db.execute("INSERT INTO moods (user_id,mood,note,created_at) VALUES (?,?,?,?)",
                       (uid, chosen, note, now_str()))
            db.commit()
            flash(f"Mood saved: {MOODS[chosen][1]}.", "success")
        return redirect(request.form.get("next") == "dashboard" and url_for("dashboard") or url_for("mood"))

    month = mood_rows(uid, days=30)
    avg, nearest = mood_average(month)
    freq = mood_frequency(month)
    top = max(freq, key=lambda f: f["count"]) if month else None
    latest = mood_rows(uid, limit=1)
    latest_key = latest[0]["mood"] if latest else None
    return render_template(
        "mood.html", history=mood_rows(uid, limit=30), freq=freq, avg=avg, nearest=nearest,
        top=top if top and top["count"] else None, month_count=len(month),
        reflection=REFLECTION_PROMPTS.get(latest_key), latest_key=latest_key)


# --------------------------------------------------------------------------
# Analytics
# --------------------------------------------------------------------------
@app.route("/analytics")
@login_required
def analytics():
    uid = g.user["id"]
    db = get_db()
    stats = get_stats(uid)
    month = mood_rows(uid, days=30)
    avg, nearest = mood_average(month)

    high_total = db.execute("SELECT COUNT(*) FROM tasks WHERE user_id=? AND priority='high'", (uid,)).fetchone()[0]
    high_done = db.execute("SELECT COUNT(*) FROM tasks WHERE user_id=? AND priority='high' AND completed=1", (uid,)).fetchone()[0]
    diary_days = db.execute(
        "SELECT COUNT(DISTINCT substr(created_at,1,10)) FROM diary WHERE user_id=? AND created_at>=?",
        (uid, (date.today() - timedelta(days=6)).isoformat())).fetchone()[0]
    positive = sum(1 for r in month if r["mood"] in ("happy", "calm"))
    bars = [
        {"label": "Overall completion", "value": stats["productivity"]},
        {"label": "High-priority tasks done", "value": round(high_done / high_total * 100) if high_total else 0},
        {"label": "Diary days this week", "value": round(diary_days / 7 * 100)},
        {"label": "Calm or happy moods (30 days)", "value": round(positive / len(month) * 100) if month else 0},
    ]
    mood_points = [{"label": datetime.strptime(r["created_at"], "%Y-%m-%d %H:%M:%S").strftime("%d %b"),
                    "emoji": MOODS[r["mood"]][0], "name": MOODS[r["mood"]][1], "score": MOODS[r["mood"]][2]}
                   for r in reversed(mood_rows(uid, limit=14))]
    return render_template("analytics.html", stats=stats, avg=avg, nearest=nearest,
                           week=week_data(uid), bars=bars, mood_points=mood_points,
                           week_done=sum(d["completed"] for d in week_data(uid)))


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------
@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    uid = g.user["id"]
    db = get_db()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "profile":
            name = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip().lower()
            taken = db.execute("SELECT 1 FROM users WHERE email=? AND id<>?", (email, uid)).fetchone()
            if not name or len(name) > 60:
                flash("Enter your name (up to 60 characters).", "error")
            elif not EMAIL_RE.match(email):
                flash("Enter a valid email address.", "error")
            elif taken:
                flash("That email is already used by another account.", "error")
            else:
                db.execute("UPDATE users SET name=?, email=? WHERE id=?", (name, email, uid))
                db.commit()
                flash("Profile saved.", "success")
        elif action == "appearance":
            theme = request.form.get("theme", "lime")
            mode = request.form.get("mode", "dark")
            if theme in THEMES and mode in ("dark", "light"):
                db.execute("UPDATE users SET theme=?, mode=? WHERE id=?", (theme, mode, uid))
                db.commit()
                flash("Appearance saved.", "success")
        elif action == "password":
            current = request.form.get("current", "")
            new = request.form.get("new", "")
            confirm = request.form.get("confirm", "")
            if not check_password_hash(g.user["password_hash"], current):
                flash("Current password is incorrect.", "error")
            elif len(new) < 8:
                flash("New password must be at least 8 characters.", "error")
            elif new != confirm:
                flash("New passwords do not match.", "error")
            else:
                db.execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(new), uid))
                db.commit()
                flash("Password changed.", "success")
        return redirect(url_for("settings"))
    return render_template("settings.html")


# Create tables on startup (works for `python app.py` and `flask run`)
init_db()

if __name__ == "__main__":
    app.run(debug=True)