"""
B.L.A.S.T. Analytics — Web app entrypoint.
Render-ready; cron/webhook trigger; health check; dashboard (calendar, tasks, notes, AI).
Email/password authentication with SQLite database.
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
    conn.commit()
    conn.close()


init_db()


def login_required(f):
    """Decorator to require login."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function


def get_user_id():
    """Get current user ID from session."""
    return session.get("user_id")


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


# — API: tasks
@app.route("/api/tasks", methods=["GET"])
@login_required
def api_tasks_list():
    user_id = get_user_id()
    conn = get_db()
    rows = conn.execute("SELECT id, text, done FROM tasks WHERE user_id = ? ORDER BY created_at DESC", (user_id,)).fetchall()
    conn.close()
    tasks = [{"id": r["id"], "text": r["text"], "done": bool(r["done"])} for r in rows]
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
    conn = get_db()
    conn.execute("INSERT INTO tasks (id, user_id, text) VALUES (?, ?, ?)", (task_id, user_id, text))
    conn.commit()
    conn.close()
    return jsonify({"id": task_id, "text": text, "done": False}), 201


@app.route("/api/tasks/<tid>", methods=["PATCH"])
@login_required
def api_tasks_update(tid):
    user_id = get_user_id()
    data = request.get_json(silent=True) or {}
    conn = get_db()
    if "done" in data:
        conn.execute("UPDATE tasks SET done = ? WHERE id = ? AND user_id = ?", (1 if data["done"] else 0, tid, user_id))
    if "text" in data:
        text = str(data["text"]).strip()
        if text:
            conn.execute("UPDATE tasks SET text = ? WHERE id = ? AND user_id = ?", (text, tid, user_id))
    conn.commit()
    row = conn.execute("SELECT id, text, done FROM tasks WHERE id = ? AND user_id = ?", (tid, user_id)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "not found"}), 404
    return jsonify({"id": row["id"], "text": row["text"], "done": bool(row["done"])})


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
