import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

from flask import Flask, request, jsonify, session, send_from_directory
from functools import wraps
from datetime import date, datetime
from database import get_db, init_db
from auth import register_user, login_user
from scheduler import generate_schedule, schedule_multi_day
from analytics import daily_report, weekly_report, monthly_report

BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # project root
TMPL_DIR   = os.path.join(BASE_DIR, "frontend", "templates")
STATIC_DIR = os.path.join(BASE_DIR, "frontend", "static")

app = Flask(__name__, template_folder=TMPL_DIR, static_folder=STATIC_DIR)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-in-prod")

# ── Production config (Render runs behind an HTTPS proxy) ─────────────────────
is_production = os.environ.get("RENDER") == "true"
app.config.update(
    SESSION_COOKIE_SECURE=is_production,      # HTTPS only in prod
    SESSION_COOKIE_HTTPONLY=True,             # No JS access to cookie
    SESSION_COOKIE_SAMESITE="Lax",            # CSRF protection
    SESSION_COOKIE_NAME="taskmind_session",
    PERMANENT_SESSION_LIFETIME=86400 * 30,    # 30 days
)
if is_production:
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# ── DB init on startup ────────────────────────────────────────────────────────
with app.app_context():
    init_db()

# ── Auth decorator ────────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return wrapper

# ── Serve frontend ────────────────────────────────────────────────────────────
@app.route("/")
def index_root():
    return send_from_directory(TMPL_DIR, "index.html")

@app.route("/sw.js")
def service_worker():
    resp = send_from_directory(STATIC_DIR, "sw.js")
    resp.headers["Service-Worker-Allowed"] = "/"
    resp.headers["Cache-Control"] = "no-cache"
    return resp

@app.route("/manifest.json")
def manifest():
    return send_from_directory(STATIC_DIR, "manifest.json")

# ══════════════════════════════════════════════════════════════════════════════
# AUTH ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/auth/register", methods=["POST"])
def api_register():
    data = request.json or {}
    email    = (data.get("email")    or "").strip()
    password = (data.get("password") or "").strip()
    name     = (data.get("name")     or "").strip()
    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400
    result = register_user(email, password, name)
    if "error" in result:
        return jsonify(result), 409
    session["user_id"] = result["id"]
    session["user_name"] = result["name"]
    return jsonify(result), 201

@app.route("/api/auth/login", methods=["POST"])
def api_login():
    data = request.json or {}
    result = login_user(data.get("email", ""), data.get("password", ""))
    if "error" in result:
        return jsonify(result), 401
    session["user_id"] = result["id"]
    session["user_name"] = result["name"]
    return jsonify(result)

@app.route("/api/auth/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"ok": True})

@app.route("/api/auth/me")
@login_required
def api_me():
    db = get_db()
    user = db.execute("SELECT id, email, name, wake_time, sleep_time FROM users WHERE id = ?",
                       (session["user_id"],)).fetchone()
    db.close()
    return jsonify(dict(user))

# ══════════════════════════════════════════════════════════════════════════════
# CATEGORIES
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/categories", methods=["GET"])
@login_required
def get_categories():
    db = get_db()
    cats = db.execute("SELECT * FROM categories WHERE user_id = ?",
                       (session["user_id"],)).fetchall()
    db.close()
    return jsonify([dict(c) for c in cats])

@app.route("/api/categories", methods=["POST"])
@login_required
def create_category():
    data = request.json or {}
    name  = data.get("name", "").strip()
    color = data.get("color", "#6366f1")
    if not name:
        return jsonify({"error": "Name required"}), 400
    db = get_db()
    db.execute("INSERT INTO categories (user_id, name, color) VALUES (?,?,?)",
               (session["user_id"], name, color))
    db.commit()
    cat = db.execute("SELECT * FROM categories WHERE user_id = ? ORDER BY id DESC LIMIT 1",
                      (session["user_id"],)).fetchone()
    db.close()
    return jsonify(dict(cat)), 201

@app.route("/api/categories/<int:cat_id>", methods=["DELETE"])
@login_required
def delete_category(cat_id):
    db = get_db()
    db.execute("DELETE FROM categories WHERE id = ? AND user_id = ?",
               (cat_id, session["user_id"]))
    db.commit()
    db.close()
    return jsonify({"ok": True})

# ══════════════════════════════════════════════════════════════════════════════
# TASKS
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/tasks", methods=["GET"])
@login_required
def get_tasks():
    db = get_db()
    rows = db.execute(
        """SELECT t.*, c.name as category_name, c.color as category_color
           FROM tasks t LEFT JOIN categories c ON t.category_id = c.id
           WHERE t.user_id = ? ORDER BY t.created_at DESC""",
        (session["user_id"],)
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/tasks", methods=["POST"])
@login_required
def create_task():
    data = request.json or {}
    title    = data.get("title", "").strip()
    duration = float(data.get("duration", 1))
    if not title:
        return jsonify({"error": "Title required"}), 400
    db = get_db()
    db.execute(
        """INSERT INTO tasks (user_id, title, duration, remaining_duration,
           deadline, preferred_time, category_id, status)
           VALUES (?,?,?,?,?,?,?,?)""",
        (session["user_id"], title, duration, duration,
         data.get("deadline"), data.get("preferred_time", "any"),
         data.get("category_id"), "pending")
    )
    db.commit()
    task = db.execute(
        """SELECT t.*, c.name as category_name, c.color as category_color
           FROM tasks t LEFT JOIN categories c ON t.category_id = c.id
           WHERE t.user_id = ? ORDER BY t.id DESC LIMIT 1""",
        (session["user_id"],)
    ).fetchone()
    db.close()
    return jsonify(dict(task)), 201

@app.route("/api/tasks/<int:task_id>", methods=["PUT"])
@login_required
def update_task(task_id):
    data = request.json or {}
    db = get_db()
    task = db.execute("SELECT * FROM tasks WHERE id = ? AND user_id = ?",
                       (task_id, session["user_id"])).fetchone()
    if not task:
        db.close()
        return jsonify({"error": "Not found"}), 404

    fields = {}
    for key in ["title", "duration", "remaining_duration", "deadline",
                "preferred_time", "category_id", "status", "notes"]:
        if key in data:
            fields[key] = data[key]

    if fields:
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        db.execute(f"UPDATE tasks SET {set_clause} WHERE id = ? AND user_id = ?",
                   list(fields.values()) + [task_id, session["user_id"]])
        db.commit()

    task = db.execute(
        """SELECT t.*, c.name as category_name, c.color as category_color
           FROM tasks t LEFT JOIN categories c ON t.category_id = c.id
           WHERE t.id = ?""", (task_id,)
    ).fetchone()
    db.close()
    return jsonify(dict(task))

@app.route("/api/tasks/<int:task_id>", methods=["DELETE"])
@login_required
def delete_task(task_id):
    db = get_db()
    db.execute("DELETE FROM tasks WHERE id = ? AND user_id = ?",
               (task_id, session["user_id"]))
    db.commit()
    db.close()
    return jsonify({"ok": True})

@app.route("/api/tasks/<int:task_id>/complete", methods=["POST"])
@login_required
def complete_task(task_id):
    db = get_db()
    db.execute(
        "UPDATE tasks SET status = 'completed', remaining_duration = 0 WHERE id = ? AND user_id = ?",
        (task_id, session["user_id"])
    )
    db.commit()
    db.close()
    return jsonify({"ok": True})

# ══════════════════════════════════════════════════════════════════════════════
# TIME TRACKING
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/tasks/<int:task_id>/start", methods=["POST"])
@login_required
def start_task(task_id):
    db = get_db()
    db.execute("UPDATE tasks SET status = 'in_progress' WHERE id = ? AND user_id = ?",
               (task_id, session["user_id"]))
    db.execute(
        "INSERT INTO activity_logs (user_id, task_id, start_time) VALUES (?,?,?)",
        (session["user_id"], task_id, datetime.now().isoformat())
    )
    db.commit()
    log = db.execute(
        "SELECT * FROM activity_logs WHERE user_id = ? AND task_id = ? ORDER BY id DESC LIMIT 1",
        (session["user_id"], task_id)
    ).fetchone()
    db.close()
    return jsonify(dict(log))

@app.route("/api/tasks/<int:task_id>/stop", methods=["POST"])
@login_required
def stop_task(task_id):
    db = get_db()
    log = db.execute(
        "SELECT * FROM activity_logs WHERE user_id = ? AND task_id = ? AND end_time IS NULL ORDER BY id DESC LIMIT 1",
        (session["user_id"], task_id)
    ).fetchone()
    if not log:
        db.close()
        return jsonify({"error": "No active session"}), 400

    start = datetime.fromisoformat(log["start_time"])
    end   = datetime.now()
    dur   = round((end - start).total_seconds() / 3600, 4)

    db.execute(
        "UPDATE activity_logs SET end_time = ?, actual_duration = ? WHERE id = ?",
        (end.isoformat(), dur, log["id"])
    )
    # Update remaining duration
    task = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    new_remaining = max(0, (task["remaining_duration"] or 0) - dur)
    db.execute("UPDATE tasks SET remaining_duration = ? WHERE id = ?", (new_remaining, task_id))
    db.commit()
    db.close()
    return jsonify({"actual_duration": dur, "remaining_duration": new_remaining})

# ══════════════════════════════════════════════════════════════════════════════
# ROUTINES
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/routines", methods=["GET"])
@login_required
def get_routines():
    db = get_db()
    rows = db.execute("SELECT * FROM routines WHERE user_id = ? ORDER BY preferred_time",
                       (session["user_id"],)).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/routines", methods=["POST"])
@login_required
def create_routine():
    data = request.json or {}
    title = data.get("title", "").strip()
    if not title:
        return jsonify({"error": "Title required"}), 400
    db = get_db()
    db.execute(
        "INSERT INTO routines (user_id, title, duration, preferred_time) VALUES (?,?,?,?)",
        (session["user_id"], title, float(data.get("duration", 0.5)), data.get("preferred_time", "morning"))
    )
    db.commit()
    row = db.execute("SELECT * FROM routines WHERE user_id = ? ORDER BY id DESC LIMIT 1",
                      (session["user_id"],)).fetchone()
    db.close()
    return jsonify(dict(row)), 201

@app.route("/api/routines/<int:r_id>", methods=["PUT"])
@login_required
def update_routine(r_id):
    data = request.json or {}
    db = get_db()
    fields = {k: v for k, v in data.items() if k in ["title", "duration", "preferred_time", "enabled"]}
    if fields:
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        db.execute(f"UPDATE routines SET {set_clause} WHERE id = ? AND user_id = ?",
                   list(fields.values()) + [r_id, session["user_id"]])
        db.commit()
    row = db.execute("SELECT * FROM routines WHERE id = ?", (r_id,)).fetchone()
    db.close()
    return jsonify(dict(row))

@app.route("/api/routines/<int:r_id>", methods=["DELETE"])
@login_required
def delete_routine(r_id):
    db = get_db()
    db.execute("DELETE FROM routines WHERE id = ? AND user_id = ?", (r_id, session["user_id"]))
    db.commit()
    db.close()
    return jsonify({"ok": True})

# ══════════════════════════════════════════════════════════════════════════════
# SCHEDULE
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/schedule")
@login_required
def get_schedule():
    target = request.args.get("date", date.today().isoformat())
    items = generate_schedule(session["user_id"], date.fromisoformat(target))
    return jsonify(items)

@app.route("/api/schedule/recalculate", methods=["POST"])
@login_required
def recalculate():
    data = request.json or {}
    target_str = data.get("date", date.today().isoformat())
    items = generate_schedule(session["user_id"], date.fromisoformat(target_str))
    return jsonify(items)

@app.route("/api/schedule/<int:item_id>/lock", methods=["POST"])
@login_required
def lock_schedule_item(item_id):
    data = request.json or {}
    start = data.get("start_time")
    end   = data.get("end_time")
    db = get_db()
    db.execute(
        "UPDATE schedule SET locked = 1, start_time = ?, end_time = ? WHERE id = ? AND user_id = ?",
        (start, end, item_id, session["user_id"])
    )
    db.commit()
    db.close()
    return jsonify({"ok": True})

# ══════════════════════════════════════════════════════════════════════════════
# ANALYTICS
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/reports/daily")
@login_required
def report_daily():
    d = request.args.get("date", date.today().isoformat())
    return jsonify(daily_report(session["user_id"], d))

@app.route("/api/reports/weekly")
@login_required
def report_weekly():
    return jsonify(weekly_report(session["user_id"]))

@app.route("/api/reports/monthly")
@login_required
def report_monthly():
    return jsonify(monthly_report(session["user_id"]))

# ══════════════════════════════════════════════════════════════════════════════
# USER SETTINGS
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/settings", methods=["PUT"])
@login_required
def update_settings():
    data = request.json or {}
    db = get_db()
    fields = {k: v for k, v in data.items() if k in ["name", "wake_time", "sleep_time"]}
    if fields:
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        db.execute(f"UPDATE users SET {set_clause} WHERE id = ?",
                   list(fields.values()) + [session["user_id"]])
        db.commit()
    db.close()
    return jsonify({"ok": True})

if __name__ == "__main__":
    app.run(debug=True, port=5000)
