"""
B.L.A.S.T. Analytics — Web app entrypoint.
Render-ready; cron/webhook trigger; health check; dashboard (calendar, tasks, notes, AI).
"""

import json
import os
import sys
import uuid
from pathlib import Path

# Ensure project root on path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from flask import Flask, request, jsonify, render_template, redirect, url_for

app = Flask(__name__, template_folder="templates", static_folder="static")

# Ensure .tmp exists
TMP_DIR = ROOT / ".tmp"
TMP_DIR.mkdir(parents=True, exist_ok=True)

TASKS_FILE = TMP_DIR / "dashboard_tasks.json"
NOTES_FILE = TMP_DIR / "dashboard_notes.json"
EVENTS_FILE = TMP_DIR / "dashboard_events.json"


def _load_json(path, default):
    if not path.is_file():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return default


def _save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _tasks():
    return _load_json(TASKS_FILE, {"tasks": []})["tasks"]


def _save_tasks(tasks):
    _save_json(TASKS_FILE, {"tasks": tasks})


def _notes():
    return _load_json(NOTES_FILE, {"notes": []})["notes"]


def _save_notes(notes):
    _save_json(NOTES_FILE, {"notes": notes})


def _events():
    return _load_json(EVENTS_FILE, {"events": []})["events"]


def _save_events(events):
    _save_json(EVENTS_FILE, {"events": events})


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


@app.route("/", methods=["GET"])
def index():
    return redirect(url_for("dashboard"))


@app.route("/dashboard", methods=["GET"])
def dashboard():
    return render_template("dashboard.html")


@app.route("/calendar", methods=["GET"])
def calendar_page():
    return render_template("calendar.html")


@app.route("/tasks", methods=["GET"])
def tasks_page():
    return render_template("tasks.html")


@app.route("/notes", methods=["GET"])
def notes_page():
    return render_template("notes.html")


@app.route("/ai", methods=["GET"])
def ai_page():
    return render_template("ai.html")


# — API: tasks
@app.route("/api/tasks", methods=["GET"])
def api_tasks_list():
    return jsonify({"tasks": _tasks()})


@app.route("/api/tasks", methods=["POST"])
def api_tasks_create():
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "text required"}), 400
    tasks = _tasks()
    task = {"id": str(uuid.uuid4()), "text": text, "done": False}
    tasks.append(task)
    _save_tasks(tasks)
    return jsonify(task), 201


@app.route("/api/tasks/<tid>", methods=["PATCH"])
def api_tasks_update(tid):
    data = request.get_json(silent=True) or {}
    tasks = _tasks()
    for t in tasks:
        if str(t.get("id")) == str(tid):
            if "done" in data:
                t["done"] = bool(data["done"])
            if "text" in data:
                t["text"] = str(data["text"]).strip() or t["text"]
            _save_tasks(tasks)
            return jsonify(t)
    return jsonify({"error": "not found"}), 404


@app.route("/api/tasks/<tid>", methods=["DELETE"])
def api_tasks_delete(tid):
    tasks = [t for t in _tasks() if str(t.get("id")) != str(tid)]
    _save_tasks(tasks)
    return jsonify({"ok": True}), 200


# — API: notes
@app.route("/api/notes", methods=["GET"])
def api_notes_list():
    return jsonify({"notes": _notes()})


@app.route("/api/notes", methods=["POST"])
def api_notes_create():
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"error": "title required"}), 400
    notes = _notes()
    note = {"id": str(uuid.uuid4()), "title": title, "body": (data.get("body") or "").strip()}
    notes.append(note)
    _save_notes(notes)
    return jsonify(note), 201


@app.route("/api/notes/<nid>", methods=["DELETE"])
def api_notes_delete(nid):
    notes = [n for n in _notes() if str(n.get("id")) != str(nid)]
    _save_notes(notes)
    return jsonify({"ok": True}), 200


# — API: events (calendar)
@app.route("/api/events", methods=["GET"])
def api_events_list():
    return jsonify({"events": _events()})


@app.route("/api/events", methods=["POST"])
def api_events_create():
    data = request.get_json(silent=True) or {}
    date = (data.get("date") or "").strip()
    title = (data.get("title") or "").strip()
    if not date or not title:
        return jsonify({"error": "date and title required"}), 400
    events = _events()
    ev = {"id": str(uuid.uuid4()), "date": date, "title": title}
    events.append(ev)
    _save_events(events)
    return jsonify(ev), 201


@app.route("/api/events/<eid>", methods=["DELETE"])
def api_events_delete(eid):
    events = [e for e in _events() if str(e.get("id")) != str(eid)]
    _save_events(events)
    return jsonify({"ok": True}), 200


# — API: AI query (routing/formatting only)
@app.route("/api/ai/query", methods=["POST"])
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
