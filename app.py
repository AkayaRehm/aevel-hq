"""
B.L.A.S.T. Analytics — Web app entrypoint.
Render-ready; cron/webhook trigger; health check; dashboard (calendar, tasks, notes, AI).
Email/password authentication with SQLite database.
Zoho Mail (hello.aevel@zohomail.com) for notifications; admin area to control what emails go to whom.
"""

import json
import os
import sys
import uuid
import sqlite3
from pathlib import Path
from functools import wraps

# Ensure project root on path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from flask import Flask, request, jsonify, render_template, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production-" + str(uuid.uuid4()))

# Zoho Mail (free zohomail.com) — emails sent from hello.aevel@zohomail.com
ZOHO_EMAIL = os.environ.get("ZOHO_EMAIL", "hello.aevel@zohomail.com")
ZOHO_PASSWORD = os.environ.get("ZOHO_PASSWORD", "")
app.config["MAIL_SERVER"] = "smtp.zoho.com"
app.config["MAIL_PORT"] = 465
app.config["MAIL_USE_SSL"] = True
app.config["MAIL_USERNAME"] = ZOHO_EMAIL
app.config["MAIL_PASSWORD"] = ZOHO_PASSWORD
app.config["MAIL_DEFAULT_SENDER"] = ("Aevel", ZOHO_EMAIL)

try:
    from flask_mail import Mail
    mail = Mail(app)
except Exception:
    mail = None

# Ensure .tmp exists
TMP_DIR = ROOT / ".tmp"
TMP_DIR.mkdir(parents=True, exist_ok=True)

DB_FILE = TMP_DIR / "app.db"


def get_db():
    """Get database connection."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialize database tables."""
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            text TEXT NOT NULL,
            done INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notes (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            body TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            title TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_preferences (
            user_id INTEGER PRIMARY KEY,
            prefs_json TEXT DEFAULT '{}',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    conn.commit()
    conn.close()


def migrate_db():
    """Add new columns and tables (tasks assignee/urgency, workspace_pages, flowcharts, email_settings)."""
    conn = get_db()
    for col, ctype in [("assigned_to", "TEXT"), ("due_date", "TEXT"), ("urgency", "TEXT")]:
        try:
            conn.execute(f"ALTER TABLE tasks ADD COLUMN {col} {ctype}")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # column exists
    conn.execute("""
        CREATE TABLE IF NOT EXISTS workspace_pages (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            body TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS flowcharts (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            mermaid_text TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS email_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email_type TEXT UNIQUE NOT NULL,
            enabled INTEGER DEFAULT 0,
            recipients TEXT DEFAULT '',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    # Seed email types if missing
    for etype in ("task_assigned", "due_soon", "digest"):
        try:
            conn.execute(
                "INSERT INTO email_settings (email_type, enabled, recipients) VALUES (?, 0, '')",
                (etype,),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            pass
    conn.close()


init_db()
migrate_db()


def login_required(f):
    """Decorator to require login."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function


ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")


def admin_required(f):
    """Decorator to require admin session (password-protected admin box)."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("admin"):
            return jsonify({"error": "Admin access required"}), 403
        return f(*args, **kwargs)
    return decorated_function


def get_user_id():
    """Get current user ID from session."""
    return session.get("user_id")


def get_email_settings():
    """Return dict of email_type -> {enabled: bool, recipients: list of emails}."""
    conn = get_db()
    rows = conn.execute("SELECT email_type, enabled, recipients FROM email_settings").fetchall()
    conn.close()
    return {
        r["email_type"]: {
            "enabled": bool(r["enabled"]),
            "recipients": [e.strip() for e in (r["recipients"] or "").split(",") if e.strip()],
        }
        for r in rows
    }


def send_app_email(email_type, subject, body_html_or_text, to_emails=None):
    """Send email via Zoho if this type is enabled and recipients exist. Uses admin list; if to_emails given (e.g. assignee), merges with admin list."""
    if not mail or not ZOHO_PASSWORD:
        return False
    settings = get_email_settings()
    conf = settings.get(email_type, {})
    if not conf.get("enabled"):
        return False
    admin_list = conf.get("recipients") or []
    if isinstance(admin_list, str):
        admin_list = [e.strip() for e in admin_list.split(",") if e.strip()]
    if to_emails is not None:
        extra = to_emails if isinstance(to_emails, list) else [to_emails]
        recipients = list(dict.fromkeys([e.strip() for e in extra if e and str(e).strip()] + admin_list))
    else:
        recipients = admin_list
    if not recipients:
        return False
    try:
        from flask_mail import Message
        msg = Message(subject=subject, recipients=recipients, body=body_html_or_text)
        if "<" in body_html_or_text and ">" in body_html_or_text:
            msg.html = body_html_or_text
            msg.body = body_html_or_text.replace("<br>", "\n").replace("</p>", "\n")
        mail.send(msg)
        return True
    except Exception:
        return False


def run_pipeline():
    """Run full pipeline: ingest → clean → analyze → report → send_payload."""
    from tools import ingest_data, clean_data, analyze, generate_report, send_payload
    steps = [ingest_data.ingest, clean_data.clean, analyze.analyze, lambda: generate_report.generate_report(), send_payload.send_payload]
    for step in steps:
        code = step()
        if code != 0:
            return code
    return 0


@app.route("/health", methods=["GET"])
def health():
    """Health check: env and integrations. Fail fast if unreachable."""
    from tools import health_check
    code = health_check.health_check()
    if code != 0:
        return jsonify({"status": "error", "message": "Health check failed"}), 503
    return jsonify({
        "status": "ok",
        "tmp_dir": str(TMP_DIR),
        "data_source": "path" if os.environ.get("DATA_SOURCE_PATH") else ("url" if os.environ.get("DATA_SOURCE_URL") else "none"),
    }), 200


@app.route("/trigger", methods=["POST", "GET"])
def trigger():
    """Cron/webhook: route request then run pipeline or single tool."""
    from navigation.router import route
    body = request.get_json(silent=True) or {}
    req = {"action": body.get("action", "full_pipeline"), "payload": body.get("payload", {}), "options": body.get("options", {})}
    result = route(req)
    tool_name = result.get("tool", "full_pipeline")
    if tool_name == "health_check":
        from tools import health_check
        code = health_check.health_check()
        return jsonify({"route": result, "health_exit": code}), 200 if code == 0 else 503
    if tool_name == "full_pipeline":
        code = run_pipeline()
        return jsonify({"route": result, "pipeline_exit": code}), 200 if code == 0 else 500
    # Single-tool dispatch
    if tool_name == "ingest_data":
        from tools import ingest_data
        code = ingest_data.ingest()
    elif tool_name == "clean_data":
        from tools import clean_data
        code = clean_data.clean()
    elif tool_name == "analyze":
        from tools import analyze
        code = analyze.analyze()
    elif tool_name == "generate_report":
        from tools import generate_report
        code = generate_report.generate_report()
    elif tool_name == "send_payload":
        from tools import send_payload
        code = send_payload.send_payload()
    else:
        code = run_pipeline()
    return jsonify({"route": result, "tool_exit": code}), 200 if code == 0 else 500


# — Auth routes
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        if not email or not password:
            flash("Email and password required", "error")
            return render_template("login.html")
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        conn.close()
        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["user_email"] = user["email"]
            return redirect(url_for("dashboard"))
        flash("Invalid email or password", "error")
    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm") or ""
        if not email or not password:
            flash("Email and password required", "error")
            return render_template("register.html")
        if password != confirm:
            flash("Passwords do not match", "error")
            return render_template("register.html")
        if len(password) < 6:
            flash("Password must be at least 6 characters", "error")
            return render_template("register.html")
        conn = get_db()
        try:
            conn.execute(
                "INSERT INTO users (email, password_hash) VALUES (?, ?)",
                (email, generate_password_hash(password))
            )
            conn.commit()
            user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            conn.close()
            session["user_id"] = user["id"]
            session["user_email"] = user["email"]
            return redirect(url_for("dashboard"))
        except sqlite3.IntegrityError:
            conn.close()
            flash("Email already registered", "error")
    return render_template("register.html")


@app.route("/logout", methods=["POST", "GET"])
def logout():
    session.clear()
    return redirect(url_for("login"))


# — Admin (password-protected; control what emails get sent and to whom)
@app.route("/admin", methods=["GET", "POST"])
def admin_page():
    if request.method == "POST":
        password = request.form.get("password") or ""
        if ADMIN_PASSWORD and password == ADMIN_PASSWORD:
            session["admin"] = True
            return redirect(url_for("admin_page"))
        flash("Invalid admin password", "error")
    if session.get("admin"):
        return render_template("admin.html", zoho_email=ZOHO_EMAIL)
    return render_template("admin_login.html")


@app.route("/admin/logout", methods=["GET", "POST"])
def admin_logout():
    session.pop("admin", None)
    return redirect(url_for("admin_page"))


@app.route("/api/admin/email-settings", methods=["GET"])
@admin_required
def api_admin_email_settings_get():
    return jsonify(get_email_settings())


@app.route("/api/admin/email-settings", methods=["PATCH"])
@admin_required
def api_admin_email_settings_update():
    data = request.get_json(silent=True) or {}
    email_type = (data.get("email_type") or "").strip()
    if not email_type:
        return jsonify({"error": "email_type required"}), 400
    conn = get_db()
    row = conn.execute("SELECT 1 FROM email_settings WHERE email_type = ?", (email_type,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "unknown email_type"}), 400
    if "enabled" in data:
        conn.execute(
            "UPDATE email_settings SET enabled = ?, updated_at = CURRENT_TIMESTAMP WHERE email_type = ?",
            (1 if data["enabled"] else 0, email_type),
        )
    if "recipients" in data:
        rec = data["recipients"]
        if isinstance(rec, list):
            rec = ",".join(str(e).strip() for e in rec if str(e).strip())
        conn.execute(
            "UPDATE email_settings SET recipients = ?, updated_at = CURRENT_TIMESTAMP WHERE email_type = ?",
            (rec or "", email_type),
        )
    conn.commit()
    conn.close()
    return jsonify(get_email_settings())


@app.route("/", methods=["GET"])
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/dashboard", methods=["GET"])
@login_required
def dashboard():
    return render_template("dashboard.html")


@app.route("/calendar", methods=["GET"])
@login_required
def calendar_page():
    return render_template("calendar.html")


@app.route("/tasks", methods=["GET"])
@login_required
def tasks_page():
    return render_template("tasks.html")


@app.route("/notes", methods=["GET"])
@login_required
def notes_page():
    return render_template("notes.html")


@app.route("/ai", methods=["GET"])
@login_required
def ai_page():
    return redirect(url_for("integrations_page"))


@app.route("/analytics", methods=["GET"])
@login_required
def analytics_page():
    return render_template("analytics.html")


@app.route("/reports", methods=["GET"])
@login_required
def reports_page():
    return render_template("reports.html")


@app.route("/automations", methods=["GET"])
@login_required
def automations_page():
    return render_template("automations.html")


@app.route("/integrations", methods=["GET"])
@login_required
def integrations_page():
    return render_template("integrations.html")


@app.route("/settings", methods=["GET"])
@login_required
def settings_page():
    return render_template("settings.html")


# — API: user preferences (customization)
DEFAULT_PREFS = {
    "dashboard_kpis": True,
    "dashboard_chart": True,
    "dashboard_recent": True,
    "dashboard_widgets": True,
    "compact": False,
}


def get_prefs(user_id):
    conn = get_db()
    row = conn.execute("SELECT prefs_json FROM user_preferences WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    if not row:
        return DEFAULT_PREFS.copy()
    try:
        data = json.loads(row["prefs_json"] or "{}")
        return {**DEFAULT_PREFS, **data}
    except (TypeError, json.JSONDecodeError):
        return DEFAULT_PREFS.copy()


@app.route("/api/preferences", methods=["GET"])
@login_required
def api_preferences_get():
    return jsonify(get_prefs(get_user_id()))


@app.route("/api/preferences", methods=["PATCH"])
@login_required
def api_preferences_update():
    user_id = get_user_id()
    data = request.get_json(silent=True) or {}
    prefs = get_prefs(user_id)
    for k in DEFAULT_PREFS:
        if k in data:
            if k == "compact":
                prefs[k] = bool(data[k])
            elif k.startswith("dashboard_"):
                prefs[k] = bool(data[k])
    conn = get_db()
    conn.execute(
        "INSERT INTO user_preferences (user_id, prefs_json, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) ON CONFLICT(user_id) DO UPDATE SET prefs_json = excluded.prefs_json, updated_at = CURRENT_TIMESTAMP",
        (user_id, json.dumps(prefs)),
    )
    conn.commit()
    conn.close()
    return jsonify(prefs)


# — API: dashboard stats
@app.route("/api/dashboard/stats", methods=["GET"])
@login_required
def api_dashboard_stats():
    user_id = get_user_id()
    conn = get_db()
    tasks = conn.execute("SELECT COUNT(*) as c FROM tasks WHERE user_id = ?", (user_id,)).fetchone()["c"]
    tasks_done = conn.execute("SELECT COUNT(*) as c FROM tasks WHERE user_id = ? AND done = 1", (user_id,)).fetchone()["c"]
    notes = conn.execute("SELECT COUNT(*) as c FROM notes WHERE user_id = ?", (user_id,)).fetchone()["c"]
    events = conn.execute("SELECT COUNT(*) as c FROM events WHERE user_id = ?", (user_id,)).fetchone()["c"]
    conn.close()
    return jsonify({
        "tasks_total": tasks,
        "tasks_done": tasks_done,
        "notes_count": notes,
        "events_count": events,
    })


# — API: tasks (with assignee, due_date, urgency; task_assigned email when assigned_to set)
def _task_row_to_json(r):
    return {
        "id": r["id"],
        "text": r["text"],
        "done": bool(r["done"]),
        "assigned_to": (r["assigned_to"] or "").strip() if "assigned_to" in r.keys() else "",
        "due_date": (r["due_date"] or "").strip() if "due_date" in r.keys() else "",
        "urgency": (r["urgency"] or "normal").strip() if "urgency" in r.keys() else "normal",
    }


@app.route("/api/tasks", methods=["GET"])
@login_required
def api_tasks_list():
    user_id = get_user_id()
    conn = get_db()
    rows = conn.execute(
        "SELECT id, text, done, assigned_to, due_date, urgency FROM tasks WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,),
    ).fetchall()
    conn.close()
    try:
        tasks = [_task_row_to_json(dict(r)) for r in rows]
    except Exception:
        tasks = [{"id": r["id"], "text": r["text"], "done": bool(r["done"]), "assigned_to": "", "due_date": "", "urgency": "normal"} for r in rows]
    return jsonify({"tasks": tasks})


@app.route("/api/tasks", methods=["POST"])
@login_required
def api_tasks_create():
    user_id = get_user_id()
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "text required"}), 400
    task_id = str(uuid.uuid4())
    assigned_to = (data.get("assigned_to") or "").strip()
    due_date = (data.get("due_date") or "").strip()
    urgency = (data.get("urgency") or "normal").strip() or "normal"
    conn = get_db()
    conn.execute(
        "INSERT INTO tasks (id, user_id, text, assigned_to, due_date, urgency) VALUES (?, ?, ?, ?, ?, ?)",
        (task_id, user_id, text, assigned_to, due_date, urgency),
    )
    conn.commit()
    conn.close()
    if assigned_to:
        send_app_email(
            "task_assigned",
            "Task assigned: " + text[:50],
            f"<p>You were assigned a task:</p><p><strong>{text}</strong></p><p>Urgency: {urgency}</p><p>Due: {due_date or 'Not set'}</p>",
            to_emails=[assigned_to],
        )
    return jsonify({"id": task_id, "text": text, "done": False, "assigned_to": assigned_to, "due_date": due_date, "urgency": urgency}), 201


@app.route("/api/tasks/<tid>", methods=["PATCH"])
@login_required
def api_tasks_update(tid):
    user_id = get_user_id()
    data = request.get_json(silent=True) or {}
    conn = get_db()
    row = conn.execute("SELECT id, text, done, assigned_to, due_date, urgency FROM tasks WHERE id = ? AND user_id = ?", (tid, user_id)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "not found"}), 404
    row = dict(row)
    prev_assigned = (row.get("assigned_to") or "").strip()
    if "done" in data:
        conn.execute("UPDATE tasks SET done = ? WHERE id = ? AND user_id = ?", (1 if data["done"] else 0, tid, user_id))
    if "text" in data:
        text = str(data["text"]).strip()
        if text:
            conn.execute("UPDATE tasks SET text = ? WHERE id = ? AND user_id = ?", (text, tid, user_id))
            row["text"] = text
    if "assigned_to" in data:
        assigned_to = (data.get("assigned_to") or "").strip()
        conn.execute("UPDATE tasks SET assigned_to = ? WHERE id = ? AND user_id = ?", (assigned_to, tid, user_id))
        row["assigned_to"] = assigned_to
        if assigned_to and assigned_to != prev_assigned:
            send_app_email(
                "task_assigned",
                "Task assigned: " + (row.get("text") or "")[:50],
                f"<p>You were assigned a task:</p><p><strong>{row.get('text', '')}</strong></p><p>Urgency: {row.get('urgency') or 'normal'}</p><p>Due: {row.get('due_date') or 'Not set'}</p>",
                to_emails=[assigned_to],
            )
    if "due_date" in data:
        due_date = (str(data["due_date"]) or "").strip()
        conn.execute("UPDATE tasks SET due_date = ? WHERE id = ? AND user_id = ?", (due_date, tid, user_id))
        row["due_date"] = due_date
    if "urgency" in data:
        urgency = (str(data["urgency"]) or "normal").strip() or "normal"
        conn.execute("UPDATE tasks SET urgency = ? WHERE id = ? AND user_id = ?", (urgency, tid, user_id))
        row["urgency"] = urgency
    conn.commit()
    row = conn.execute("SELECT id, text, done, assigned_to, due_date, urgency FROM tasks WHERE id = ? AND user_id = ?", (tid, user_id)).fetchone()
    conn.close()
    return jsonify(_task_row_to_json(dict(row)))


@app.route("/api/tasks/<tid>", methods=["DELETE"])
@login_required
def api_tasks_delete(tid):
    user_id = get_user_id()
    conn = get_db()
    conn.execute("DELETE FROM tasks WHERE id = ? AND user_id = ?", (tid, user_id))
    conn.commit()
    conn.close()
    return jsonify({"ok": True}), 200


# — API: notes
@app.route("/api/notes", methods=["GET"])
@login_required
def api_notes_list():
    user_id = get_user_id()
    conn = get_db()
    rows = conn.execute("SELECT id, title, body FROM notes WHERE user_id = ? ORDER BY created_at DESC", (user_id,)).fetchall()
    conn.close()
    notes = [{"id": r["id"], "title": r["title"], "body": r["body"] or ""} for r in rows]
    return jsonify({"notes": notes})


@app.route("/api/notes", methods=["POST"])
@login_required
def api_notes_create():
    user_id = get_user_id()
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"error": "title required"}), 400
    note_id = str(uuid.uuid4())
    body = (data.get("body") or "").strip()
    conn = get_db()
    conn.execute("INSERT INTO notes (id, user_id, title, body) VALUES (?, ?, ?, ?)", (note_id, user_id, title, body))
    conn.commit()
    conn.close()
    return jsonify({"id": note_id, "title": title, "body": body}), 201


@app.route("/api/notes/<nid>", methods=["DELETE"])
@login_required
def api_notes_delete(nid):
    user_id = get_user_id()
    conn = get_db()
    conn.execute("DELETE FROM notes WHERE id = ? AND user_id = ?", (nid, user_id))
    conn.commit()
    conn.close()
    return jsonify({"ok": True}), 200


# — API: events (calendar)
@app.route("/api/events", methods=["GET"])
@login_required
def api_events_list():
    user_id = get_user_id()
    conn = get_db()
    rows = conn.execute("SELECT id, date, title FROM events WHERE user_id = ? ORDER BY date", (user_id,)).fetchall()
    conn.close()
    events = [{"id": r["id"], "date": r["date"], "title": r["title"]} for r in rows]
    return jsonify({"events": events})


@app.route("/api/events", methods=["POST"])
@login_required
def api_events_create():
    user_id = get_user_id()
    data = request.get_json(silent=True) or {}
    date = (data.get("date") or "").strip()
    title = (data.get("title") or "").strip()
    if not date or not title:
        return jsonify({"error": "date and title required"}), 400
    event_id = str(uuid.uuid4())
    conn = get_db()
    conn.execute("INSERT INTO events (id, user_id, date, title) VALUES (?, ?, ?, ?)", (event_id, user_id, date, title))
    conn.commit()
    conn.close()
    return jsonify({"id": event_id, "date": date, "title": title}), 201


@app.route("/api/events/<eid>", methods=["DELETE"])
@login_required
def api_events_delete(eid):
    user_id = get_user_id()
    conn = get_db()
    conn.execute("DELETE FROM events WHERE id = ? AND user_id = ?", (eid, user_id))
    conn.commit()
    conn.close()
    return jsonify({"ok": True}), 200


# — API: AI query (routing/formatting only)
@app.route("/api/ai/query", methods=["POST"])
@login_required
def api_ai_query():
    data = request.get_json(silent=True) or {}
    query = (data.get("query") or "").strip()
    if not query:
        return jsonify({"error": "query required"}), 400
    from navigation.router import route
    req = {"action": "full_pipeline", "payload": {"query": query}, "options": {}}
    result = route(req)
    return jsonify({
        "route": result.get("route"),
        "tool": result.get("tool"),
        "message": result.get("message"),
        "formatted_payload": result.get("formatted_payload"),
    }), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
