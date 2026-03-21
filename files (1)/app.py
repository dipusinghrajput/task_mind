"""
Flask Backend — AI Task Planner API
All routes for tasks, schedule, fixed slots, holidays, analytics, time tracking.
"""

from flask import Flask, request, jsonify, render_template, send_from_directory
from datetime import datetime, date, timedelta
import sqlite3
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from database import init_db, DB_PATH
from engine.scheduler import SchedulerEngine

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-in-prod")
USER_ID = 1

_db_initialized = False
_notifier_started = False

@app.before_request
def _ensure_db():
    global _db_initialized, _notifier_started
    if not _db_initialized:
        init_db(os.environ.get("PLANNER_DB", DB_PATH))
        _db_initialized = True
    if not _notifier_started:
        try:
            from notifier import start_daemon_thread
            start_daemon_thread()
        except Exception as e:
            app.logger.warning(f"Notifier start failed: {e}")
        _notifier_started = True


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def rows_to_list(rows):
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────
# PAGES
# ─────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


# ─────────────────────────────────────────────
# TASKS
# ─────────────────────────────────────────────

@app.route("/api/tasks", methods=["GET"])
def get_tasks():
    conn = get_db()
    status = request.args.get("status")
    q = "SELECT t.*, c.name as cat_name, c.color as cat_color, c.icon as cat_icon FROM tasks t LEFT JOIN categories c ON t.category_id=c.id WHERE t.user_id=?"
    params = [USER_ID]
    if status:
        q += " AND t.status=?"
        params.append(status)
    q += " ORDER BY t.deadline ASC NULLS LAST, t.priority DESC"
    tasks = rows_to_list(conn.execute(q, params).fetchall())
    conn.close()
    return jsonify(tasks)


@app.route("/api/tasks", methods=["POST"])
def create_task():
    data = request.json
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO tasks (user_id, category_id, title, description, duration_min,
           remaining_duration, deadline, priority, preferred_time, notes)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (USER_ID, data.get("category_id"), data["title"], data.get("description"),
         data.get("duration_min", 60), data.get("duration_min", 60),
         data.get("deadline"), data.get("priority", 2),
         data.get("preferred_time"), data.get("notes"))
    )
    conn.commit()
    task_id = cur.lastrowid

    # Queue reminder notification
    if data.get("deadline"):
        deadline_dt = datetime.fromisoformat(data["deadline"] + "T09:00:00")
        reminder_at = (deadline_dt - timedelta(hours=24)).isoformat()
        conn.execute(
            "INSERT INTO notifications (user_id, type, title, message, scheduled_at) VALUES (?,?,?,?,?)",
            (USER_ID, "reminder", f"⏰ Deadline Tomorrow: {data['title']}",
             f"'{data['title']}' is due tomorrow. Get it done!", reminder_at)
        )
        conn.commit()

    conn.close()
    return jsonify({"id": task_id, "message": "Task created"}), 201


@app.route("/api/tasks/<int:task_id>", methods=["PUT"])
def update_task(task_id):
    data = request.json
    conn = get_db()
    fields = []
    params = []
    for key in ["title", "description", "duration_min", "remaining_duration",
                "deadline", "priority", "status", "notes", "category_id", "preferred_time"]:
        if key in data:
            fields.append(f"{key}=?")
            params.append(data[key])
            if key == "status" and data[key] == "done":
                fields.append("completed_at=?")
                params.append(datetime.now().isoformat())
    params.append(task_id)
    conn.execute(f"UPDATE tasks SET {', '.join(fields)} WHERE id=?", params)
    conn.commit()
    conn.close()
    return jsonify({"message": "Updated"})


@app.route("/api/tasks/<int:task_id>", methods=["DELETE"])
def delete_task(task_id):
    conn = get_db()
    conn.execute("DELETE FROM tasks WHERE id=? AND user_id=?", (task_id, USER_ID))
    conn.commit()
    conn.close()
    return jsonify({"message": "Deleted"})


# ─────────────────────────────────────────────
# SCHEDULER
# ─────────────────────────────────────────────

@app.route("/api/schedule/generate", methods=["POST"])
def generate_schedule():
    data = request.json or {}
    target_date_str = data.get("date", date.today().isoformat())
    target_date = date.fromisoformat(target_date_str)

    engine = SchedulerEngine(DB_PATH)
    result = engine.generate(USER_ID, target_date)
    serialized = engine.serialize(result)

    # Persist blocks to schedule table
    conn = get_db()
    conn.execute("DELETE FROM schedule WHERE user_id=? AND date=?", (USER_ID, target_date_str))
    for b in result.blocks:
        conn.execute(
            """INSERT INTO schedule (user_id, task_id, date, title, start_time, end_time,
               block_type, category, color, is_split, split_part, split_total, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (USER_ID, b.task_id, target_date_str, b.title,
             b.start.strftime("%H:%M"), b.end.strftime("%H:%M"),
             b.block_type, b.category, b.color,
             1 if b.is_split else 0, b.split_part, b.split_total, b.notes)
        )

    # Persist smart notifications
    for notif in result.notifications:
        if notif["type"] in ("recommendation", "similar_slots"):
            conn.execute(
                "INSERT INTO notifications (user_id, type, title, message, scheduled_at, data) VALUES (?,?,?,?,?,?)",
                (USER_ID, notif["type"],
                 "AI Planner" if notif["type"] == "recommendation" else "⚡ Smart Slot Detected",
                 notif["message"],
                 datetime.now().isoformat(),
                 json.dumps(notif))
            )
    conn.commit()
    conn.close()

    return jsonify(serialized)


@app.route("/api/schedule", methods=["GET"])
def get_schedule():
    target_date = request.args.get("date", date.today().isoformat())
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM schedule WHERE user_id=? AND date=? ORDER BY start_time",
        (USER_ID, target_date)
    ).fetchall()
    conn.close()
    return jsonify(rows_to_list(rows))


@app.route("/api/schedule/<int:block_id>/status", methods=["PUT"])
def update_block_status(block_id):
    data = request.json
    conn = get_db()
    conn.execute("UPDATE schedule SET status=? WHERE id=?", (data["status"], block_id))
    conn.commit()
    conn.close()
    return jsonify({"message": "Updated"})


# ─────────────────────────────────────────────
# TIME TRACKING
# ─────────────────────────────────────────────

@app.route("/api/track/start", methods=["POST"])
def start_task():
    data = request.json
    conn = get_db()
    log_id = conn.execute(
        "INSERT INTO activity_logs (user_id, task_id, schedule_id, start_time, action) VALUES (?,?,?,?,?)",
        (USER_ID, data.get("task_id"), data.get("schedule_id"), datetime.now().isoformat(), "started")
    ).lastrowid
    if data.get("schedule_id"):
        conn.execute("UPDATE schedule SET status='started' WHERE id=?", (data["schedule_id"],))
    conn.commit()
    conn.close()
    return jsonify({"log_id": log_id})


@app.route("/api/track/stop", methods=["POST"])
def stop_task():
    data = request.json
    conn = get_db()
    log = conn.execute("SELECT * FROM activity_logs WHERE id=?", (data["log_id"],)).fetchone()
    if log:
        start = datetime.fromisoformat(log["start_time"])
        end = datetime.now()
        actual = int((end - start).total_seconds() / 60)
        conn.execute(
            "UPDATE activity_logs SET end_time=?, actual_duration=?, action=? WHERE id=?",
            (end.isoformat(), actual, data.get("action", "completed"), data["log_id"])
        )
        if data.get("schedule_id"):
            status = "done" if data.get("action") == "completed" else "pending"
            conn.execute("UPDATE schedule SET status=? WHERE id=?", (status, data["schedule_id"]))
        if data.get("task_id") and data.get("action") == "completed":
            conn.execute("UPDATE tasks SET status='done', completed_at=? WHERE id=?",
                        (end.isoformat(), data["task_id"]))
    conn.commit()
    conn.close()
    return jsonify({"actual_duration": actual if log else 0})


# ─────────────────────────────────────────────
# FIXED SCHEDULE & OVERRIDES
# ─────────────────────────────────────────────

@app.route("/api/fixed", methods=["GET"])
def get_fixed():
    conn = get_db()
    rows = conn.execute("SELECT * FROM fixed_schedule WHERE user_id=?", (USER_ID,)).fetchall()
    conn.close()
    return jsonify(rows_to_list(rows))


@app.route("/api/fixed", methods=["POST"])
def add_fixed():
    data = request.json
    conn = get_db()
    conn.execute(
        "INSERT INTO fixed_schedule (user_id, title, start_time, end_time, repeat_days, is_editable) VALUES (?,?,?,?,?,?)",
        (USER_ID, data["title"], data["start_time"], data["end_time"],
         data.get("repeat_days", "monday,tuesday,wednesday,thursday,friday"),
         data.get("is_editable", 1))
    )
    conn.commit()
    conn.close()
    return jsonify({"message": "Added"})


@app.route("/api/fixed/<int:fixed_id>/override", methods=["POST"])
def add_override(fixed_id):
    """Add a sub-free-slot inside a fixed block (e.g., free period inside college)."""
    data = request.json
    conn = get_db()
    conn.execute(
        "INSERT INTO slot_overrides (fixed_id, date, free_start, free_end, label) VALUES (?,?,?,?,?)",
        (fixed_id, data["date"], data["free_start"], data["free_end"], data.get("label", "Free Period"))
    )
    conn.commit()
    conn.close()
    return jsonify({"message": "Override added"})


# ─────────────────────────────────────────────
# HOLIDAYS
# ─────────────────────────────────────────────

@app.route("/api/holidays", methods=["GET"])
def get_holidays():
    conn = get_db()
    rows = conn.execute("SELECT * FROM holidays WHERE user_id=?", (USER_ID,)).fetchall()
    conn.close()
    return jsonify(rows_to_list(rows))


@app.route("/api/holidays", methods=["POST"])
def add_holiday():
    data = request.json
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO holidays (user_id, date, label) VALUES (?,?,?)",
        (USER_ID, data["date"], data.get("label", "Holiday"))
    )
    conn.commit()
    conn.close()
    return jsonify({"message": "Holiday marked"})


@app.route("/api/holidays/<string:holiday_date>", methods=["DELETE"])
def remove_holiday(holiday_date):
    conn = get_db()
    conn.execute("DELETE FROM holidays WHERE user_id=? AND date=?", (USER_ID, holiday_date))
    conn.commit()
    conn.close()
    return jsonify({"message": "Removed"})


# ─────────────────────────────────────────────
# ROUTINES
# ─────────────────────────────────────────────

@app.route("/api/routines", methods=["GET"])
def get_routines():
    conn = get_db()
    rows = conn.execute("SELECT * FROM routines WHERE user_id=?", (USER_ID,)).fetchall()
    conn.close()
    return jsonify(rows_to_list(rows))


@app.route("/api/routines", methods=["POST"])
def add_routine():
    data = request.json
    conn = get_db()
    conn.execute(
        "INSERT INTO routines (user_id, title, start_time, duration_min, repeat_days, on_holiday) VALUES (?,?,?,?,?,?)",
        (USER_ID, data["title"], data["start_time"], data["duration_min"],
         data.get("repeat_days", ""), data.get("on_holiday", 0))
    )
    conn.commit()
    conn.close()
    return jsonify({"message": "Routine added"})


# ─────────────────────────────────────────────
# CATEGORIES
# ─────────────────────────────────────────────

@app.route("/api/categories", methods=["GET"])
def get_categories():
    conn = get_db()
    rows = conn.execute("SELECT * FROM categories WHERE user_id=?", (USER_ID,)).fetchall()
    conn.close()
    return jsonify(rows_to_list(rows))


# ─────────────────────────────────────────────
# NOTIFICATIONS
# ─────────────────────────────────────────────

@app.route("/api/notifications", methods=["GET"])
def get_notifications():
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM notifications WHERE user_id=? ORDER BY scheduled_at DESC LIMIT 50",
        (USER_ID,)
    ).fetchall()
    conn.close()
    return jsonify(rows_to_list(rows))


@app.route("/api/notifications/<int:notif_id>/read", methods=["PUT"])
def mark_read(notif_id):
    conn = get_db()
    conn.execute("UPDATE notifications SET sent=1 WHERE id=?", (notif_id,))
    conn.commit()
    conn.close()
    return jsonify({"message": "Marked read"})


# ─────────────────────────────────────────────
# ANALYTICS
# ─────────────────────────────────────────────

@app.route("/api/analytics/daily", methods=["GET"])
def analytics_daily():
    target = request.args.get("date", date.today().isoformat())
    conn = get_db()
    planned = conn.execute(
        "SELECT SUM((strftime('%s',end_time) - strftime('%s',start_time))/60) as total FROM schedule WHERE user_id=? AND date=? AND block_type='task'",
        (USER_ID, target)
    ).fetchone()["total"] or 0
    actual = conn.execute(
        "SELECT SUM(actual_duration) as total FROM activity_logs WHERE user_id=? AND start_time LIKE ?",
        (USER_ID, target + "%")
    ).fetchone()["total"] or 0
    done = conn.execute(
        "SELECT COUNT(*) as cnt FROM schedule WHERE user_id=? AND date=? AND status='done'",
        (USER_ID, target)
    ).fetchone()["cnt"]
    total = conn.execute(
        "SELECT COUNT(*) as cnt FROM schedule WHERE user_id=? AND date=? AND block_type='task'",
        (USER_ID, target)
    ).fetchone()["cnt"]
    conn.close()
    return jsonify({
        "planned_min": planned, "actual_min": actual,
        "done": done, "total": total,
        "completion_pct": round(done / total * 100) if total else 0
    })


@app.route("/api/analytics/weekly", methods=["GET"])
def analytics_weekly():
    today = date.today()
    week_start = (today - timedelta(days=today.weekday())).isoformat()
    conn = get_db()
    rows = conn.execute(
        """SELECT date,
             SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) as done,
             COUNT(*) as total
           FROM schedule WHERE user_id=? AND date >= ? AND block_type='task'
           GROUP BY date ORDER BY date""",
        (USER_ID, week_start)
    ).fetchall()
    conn.close()
    return jsonify(rows_to_list(rows))


# ─────────────────────────────────────────────
# HEALTH CHECK (required by Render)
# ─────────────────────────────────────────────

@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "time": datetime.utcnow().isoformat()})


# ─────────────────────────────────────────────
# KEEP-ALIVE (prevents Render free tier sleep)
# UptimeRobot pings /ping every 5 min for free
# ─────────────────────────────────────────────

@app.route("/ping")
def ping():
    return "pong", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV") != "production"
    init_db(os.environ.get("PLANNER_DB", DB_PATH))
    app.run(host="0.0.0.0", port=port, debug=debug)
