"""
Flask Backend — AI Task Planner
Multi-user, PostgreSQL (Render) + SQLite (local fallback)
PWA push notifications via Web Push API
"""

from flask import Flask, request, jsonify, render_template, g
from datetime import datetime, date, timedelta
import json, os, sys, threading

sys.path.insert(0, os.path.dirname(__file__))
from database import get_db, init_db, close_db
from engine.scheduler import SchedulerEngine

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-in-prod")

# ── DB init on first request ──────────────────
_db_initialized = False
@app.before_request
def _ensure_db():
    global _db_initialized
    if not _db_initialized:
        init_db()
        _db_initialized = True

@app.teardown_appcontext
def _close_db(e=None):
    close_db()

# ── Helper: get user_id from header or default 1 ──
def current_user_id():
    return int(request.headers.get("X-User-Id", 1))

def rows_to_list(rows):
    if rows is None:
        return []
    return [dict(r) for r in rows]

# ─────────────────────────────────────────────
# PAGES
# ─────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/ping")
def ping():
    return "pong", 200

@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "time": datetime.utcnow().isoformat()})

# ─────────────────────────────────────────────
# PUSH SUBSCRIPTION (PWA)
# ─────────────────────────────────────────────

@app.route("/api/push/subscribe", methods=["POST"])
def push_subscribe():
    data = request.json
    db = get_db()
    uid = current_user_id()
    subscription_json = json.dumps(data["subscription"])
    db.execute(
        """INSERT INTO push_subscriptions (user_id, subscription, user_agent)
           VALUES (?, ?, ?)
           ON CONFLICT(user_id) DO UPDATE SET subscription=excluded.subscription, updated_at=datetime('now')""",
        (uid, subscription_json, request.headers.get("User-Agent", ""))
    )
    db.commit()
    return jsonify({"message": "Subscribed"})

@app.route("/api/push/vapid-public-key")
def vapid_public_key():
    return jsonify({"key": os.environ.get("VAPID_PUBLIC_KEY", "")})

# ─────────────────────────────────────────────
# AUTH (simple PIN-based, no passwords)
# ─────────────────────────────────────────────

@app.route("/api/auth/register", methods=["POST"])
def register():
    data = request.json
    db = get_db()
    try:
        cur = db.execute(
            "INSERT INTO users (name, email, pin) VALUES (?, ?, ?)",
            (data["name"], data.get("email", ""), data.get("pin", "0000"))
        )
        db.commit()
        uid = cur.lastrowid
        _seed_user_defaults(db, uid)
        return jsonify({"user_id": uid, "name": data["name"]}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.json
    db = get_db()
    user = db.execute(
        "SELECT * FROM users WHERE name=? AND pin=?",
        (data["name"], data.get("pin", "0000"))
    ).fetchone()
    if not user:
        return jsonify({"error": "Invalid name or PIN"}), 401
    return jsonify({"user_id": user["id"], "name": user["name"]})

def _seed_user_defaults(db, uid):
    db.execute("INSERT OR IGNORE INTO categories (user_id,name,color,icon) VALUES (?,?,?,?)", (uid,'study','#3b82f6','📚'))
    db.execute("INSERT OR IGNORE INTO categories (user_id,name,color,icon) VALUES (?,?,?,?)", (uid,'work','#ef4444','💼'))
    db.execute("INSERT OR IGNORE INTO categories (user_id,name,color,icon) VALUES (?,?,?,?)", (uid,'health','#22c55e','🏃'))
    db.execute("INSERT OR IGNORE INTO categories (user_id,name,color,icon) VALUES (?,?,?,?)", (uid,'personal','#f59e0b','🌟'))
    db.execute("INSERT OR IGNORE INTO categories (user_id,name,color,icon) VALUES (?,?,?,?)", (uid,'college','#8b5cf6','🎓'))
    db.execute("INSERT OR IGNORE INTO routines (user_id,title,start_time,duration_min,repeat_days,on_holiday) VALUES (?,?,?,?,?,?)",
               (uid,'🌅 Morning Routine','06:00',30,'monday,tuesday,wednesday,thursday,friday,saturday,sunday',1))
    db.execute("INSERT OR IGNORE INTO routines (user_id,title,start_time,duration_min,repeat_days,on_holiday) VALUES (?,?,?,?,?,?)",
               (uid,'🌙 Wind Down','22:30',30,'monday,tuesday,wednesday,thursday,friday,saturday,sunday',1))
    db.execute("INSERT OR IGNORE INTO fixed_schedule (user_id,title,start_time,end_time,is_editable) VALUES (?,?,?,?,?)",
               (uid,'🏫 College','10:00','17:00',1))
    db.commit()

# ─────────────────────────────────────────────
# TASKS
# ─────────────────────────────────────────────

@app.route("/api/tasks", methods=["GET"])
def get_tasks():
    db = get_db()
    uid = current_user_id()
    status = request.args.get("status")
    q = """SELECT t.*, c.name as cat_name, c.color as cat_color, c.icon as cat_icon
           FROM tasks t LEFT JOIN categories c ON t.category_id=c.id
           WHERE t.user_id=?"""
    params = [uid]
    if status:
        q += " AND t.status=?"
        params.append(status)
    q += " ORDER BY t.deadline ASC NULLS LAST, t.priority DESC"
    return jsonify(rows_to_list(db.execute(q, params).fetchall()))

@app.route("/api/tasks", methods=["POST"])
def create_task():
    data = request.json
    db = get_db()
    uid = current_user_id()
    cur = db.execute(
        """INSERT INTO tasks (user_id,category_id,title,description,duration_min,
           remaining_duration,deadline,priority,preferred_time,notes)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (uid, data.get("category_id"), data["title"], data.get("description"),
         data.get("duration_min", 60), data.get("duration_min", 60),
         data.get("deadline"), data.get("priority", 2),
         data.get("preferred_time"), data.get("notes"))
    )
    db.commit()
    task_id = cur.lastrowid
    if data.get("deadline"):
        try:
            dl = datetime.fromisoformat(data["deadline"] + "T09:00:00")
            reminder_at = (dl - timedelta(hours=24)).isoformat()
            db.execute(
                "INSERT INTO notifications (user_id,type,title,message,scheduled_at) VALUES (?,?,?,?,?)",
                (uid, "reminder", f"⏰ Deadline Tomorrow: {data['title']}",
                 f"'{data['title']}' is due tomorrow!", reminder_at)
            )
            db.commit()
        except Exception:
            pass
    return jsonify({"id": task_id, "message": "Task created"}), 201

@app.route("/api/tasks/<int:task_id>", methods=["PUT"])
def update_task(task_id):
    data = request.json
    db = get_db()
    fields, params = [], []
    for key in ["title","description","duration_min","remaining_duration",
                "deadline","priority","status","notes","category_id","preferred_time"]:
        if key in data:
            fields.append(f"{key}=?")
            params.append(data[key])
            if key == "status" and data[key] == "done":
                fields.append("completed_at=?")
                params.append(datetime.now().isoformat())
    params.append(task_id)
    db.execute(f"UPDATE tasks SET {', '.join(fields)} WHERE id=?", params)
    db.commit()
    return jsonify({"message": "Updated"})

@app.route("/api/tasks/<int:task_id>", methods=["DELETE"])
def delete_task(task_id):
    db = get_db()
    db.execute("DELETE FROM tasks WHERE id=? AND user_id=?", (task_id, current_user_id()))
    db.commit()
    return jsonify({"message": "Deleted"})

# ─────────────────────────────────────────────
# SCHEDULER
# ─────────────────────────────────────────────

@app.route("/api/schedule/generate", methods=["POST"])
def generate_schedule():
    from database import DB_PATH
    data = request.json or {}
    uid = current_user_id()
    target_date_str = data.get("date", date.today().isoformat())
    target_date = date.fromisoformat(target_date_str)

    engine = SchedulerEngine(DB_PATH)
    result = engine.generate(uid, target_date)
    serialized = engine.serialize(result)

    db = get_db()
    db.execute("DELETE FROM schedule WHERE user_id=? AND date=?", (uid, target_date_str))
    for b in result.blocks:
        db.execute(
            """INSERT INTO schedule (user_id,task_id,date,title,start_time,end_time,
               block_type,category,color,is_split,split_part,split_total,notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (uid, b.task_id, target_date_str, b.title,
             b.start.strftime("%H:%M"), b.end.strftime("%H:%M"),
             b.block_type, b.category, b.color,
             1 if b.is_split else 0, b.split_part, b.split_total, b.notes)
        )
    for notif in result.notifications:
        if notif["type"] in ("recommendation", "similar_slots"):
            db.execute(
                "INSERT INTO notifications (user_id,type,title,message,scheduled_at,data) VALUES (?,?,?,?,?,?)",
                (uid, notif["type"],
                 "💡 AI Recommendation" if notif["type"] == "recommendation" else "⚡ Smart Slot Detected",
                 notif["message"], datetime.now().isoformat(), json.dumps(notif))
            )
    db.commit()
    return jsonify(serialized)

@app.route("/api/schedule", methods=["GET"])
def get_schedule():
    db = get_db()
    rows = db.execute(
        "SELECT * FROM schedule WHERE user_id=? AND date=? ORDER BY start_time",
        (current_user_id(), request.args.get("date", date.today().isoformat()))
    ).fetchall()
    return jsonify(rows_to_list(rows))

@app.route("/api/schedule/<int:block_id>/status", methods=["PUT"])
def update_block_status(block_id):
    db = get_db()
    db.execute("UPDATE schedule SET status=? WHERE id=?", (request.json["status"], block_id))
    db.commit()
    return jsonify({"message": "Updated"})

# ─────────────────────────────────────────────
# TIME TRACKING
# ─────────────────────────────────────────────

@app.route("/api/track/start", methods=["POST"])
def start_task():
    data = request.json
    db = get_db()
    uid = current_user_id()
    log_id = db.execute(
        "INSERT INTO activity_logs (user_id,task_id,schedule_id,start_time,action) VALUES (?,?,?,?,?)",
        (uid, data.get("task_id"), data.get("schedule_id"), datetime.now().isoformat(), "started")
    ).lastrowid
    if data.get("schedule_id"):
        db.execute("UPDATE schedule SET status='started' WHERE id=?", (data["schedule_id"],))
    db.commit()
    return jsonify({"log_id": log_id})

@app.route("/api/track/stop", methods=["POST"])
def stop_task():
    data = request.json
    db = get_db()
    log = db.execute("SELECT * FROM activity_logs WHERE id=?", (data["log_id"],)).fetchone()
    actual = 0
    if log:
        end = datetime.now()
        actual = int((end - datetime.fromisoformat(log["start_time"])).total_seconds() / 60)
        db.execute(
            "UPDATE activity_logs SET end_time=?,actual_duration=?,action=? WHERE id=?",
            (end.isoformat(), actual, data.get("action","completed"), data["log_id"])
        )
        if data.get("schedule_id"):
            db.execute("UPDATE schedule SET status=? WHERE id=?",
                      ("done" if data.get("action")=="completed" else "pending", data["schedule_id"]))
        if data.get("task_id") and data.get("action") == "completed":
            db.execute("UPDATE tasks SET status='done',completed_at=? WHERE id=?",
                      (end.isoformat(), data["task_id"]))
        db.commit()
    return jsonify({"actual_duration": actual})

# ─────────────────────────────────────────────
# FIXED / ROUTINES / HOLIDAYS / CATEGORIES
# ─────────────────────────────────────────────

@app.route("/api/fixed", methods=["GET"])
def get_fixed():
    db = get_db()
    return jsonify(rows_to_list(db.execute("SELECT * FROM fixed_schedule WHERE user_id=?", (current_user_id(),)).fetchall()))

@app.route("/api/fixed", methods=["POST"])
def add_fixed():
    data = request.json
    db = get_db()
    db.execute("INSERT INTO fixed_schedule (user_id,title,start_time,end_time,repeat_days,is_editable) VALUES (?,?,?,?,?,?)",
               (current_user_id(), data["title"], data["start_time"], data["end_time"],
                data.get("repeat_days","monday,tuesday,wednesday,thursday,friday"), data.get("is_editable",1)))
    db.commit()
    return jsonify({"message": "Added"})

@app.route("/api/fixed/<int:fixed_id>/override", methods=["POST"])
def add_override(fixed_id):
    data = request.json
    db = get_db()
    db.execute("INSERT INTO slot_overrides (fixed_id,date,free_start,free_end,label) VALUES (?,?,?,?,?)",
               (fixed_id, data["date"], data["free_start"], data["free_end"], data.get("label","Free Period")))
    db.commit()
    return jsonify({"message": "Override added"})

@app.route("/api/holidays", methods=["GET"])
def get_holidays():
    db = get_db()
    return jsonify(rows_to_list(db.execute("SELECT * FROM holidays WHERE user_id=?", (current_user_id(),)).fetchall()))

@app.route("/api/holidays", methods=["POST"])
def add_holiday():
    data = request.json
    db = get_db()
    db.execute("INSERT OR REPLACE INTO holidays (user_id,date,label) VALUES (?,?,?)",
               (current_user_id(), data["date"], data.get("label","Holiday")))
    db.commit()
    return jsonify({"message": "Marked"})

@app.route("/api/holidays/<string:d>", methods=["DELETE"])
def remove_holiday(d):
    db = get_db()
    db.execute("DELETE FROM holidays WHERE user_id=? AND date=?", (current_user_id(), d))
    db.commit()
    return jsonify({"message": "Removed"})

@app.route("/api/routines", methods=["GET"])
def get_routines():
    db = get_db()
    return jsonify(rows_to_list(db.execute("SELECT * FROM routines WHERE user_id=?", (current_user_id(),)).fetchall()))

@app.route("/api/routines", methods=["POST"])
def add_routine():
    data = request.json
    db = get_db()
    db.execute("INSERT INTO routines (user_id,title,start_time,duration_min,repeat_days,on_holiday) VALUES (?,?,?,?,?,?)",
               (current_user_id(), data["title"], data["start_time"], data["duration_min"],
                data.get("repeat_days",""), data.get("on_holiday",0)))
    db.commit()
    return jsonify({"message": "Added"})

@app.route("/api/categories", methods=["GET"])
def get_categories():
    db = get_db()
    return jsonify(rows_to_list(db.execute("SELECT * FROM categories WHERE user_id=?", (current_user_id(),)).fetchall()))

# ─────────────────────────────────────────────
# NOTIFICATIONS (polling endpoint for PWA)
# ─────────────────────────────────────────────

@app.route("/api/notifications", methods=["GET"])
def get_notifications():
    db = get_db()
    uid = current_user_id()
    since = request.args.get("since")   # ISO datetime — only return newer
    q = "SELECT * FROM notifications WHERE user_id=?"
    params = [uid]
    if since:
        q += " AND scheduled_at > ?"
        params.append(since)
    q += " ORDER BY scheduled_at DESC LIMIT 50"
    return jsonify(rows_to_list(db.execute(q, params).fetchall()))

@app.route("/api/notifications/pending", methods=["GET"])
def get_pending_notifications():
    """Called by service worker to get undelivered notifications."""
    db = get_db()
    uid = current_user_id()
    now = datetime.utcnow().isoformat()
    rows = db.execute(
        "SELECT * FROM notifications WHERE user_id=? AND sent=0 AND scheduled_at <= ? ORDER BY scheduled_at ASC LIMIT 10",
        (uid, now)
    ).fetchall()
    # Mark as sent
    for row in rows:
        db.execute("UPDATE notifications SET sent=1, sent_at=? WHERE id=?", (now, row["id"]))
    db.commit()
    return jsonify(rows_to_list(rows))

@app.route("/api/notifications/<int:nid>/read", methods=["PUT"])
def mark_read(nid):
    db = get_db()
    db.execute("UPDATE notifications SET sent=1 WHERE id=?", (nid,))
    db.commit()
    return jsonify({"message": "Read"})

# ─────────────────────────────────────────────
# ANALYTICS
# ─────────────────────────────────────────────

@app.route("/api/analytics/daily")
def analytics_daily():
    uid = current_user_id()
    target = request.args.get("date", date.today().isoformat())
    db = get_db()
    planned = db.execute(
        "SELECT SUM((strftime('%s',end_time)-strftime('%s',start_time))/60) as t FROM schedule WHERE user_id=? AND date=? AND block_type='task'",
        (uid, target)
    ).fetchone()["t"] or 0
    actual = db.execute(
        "SELECT SUM(actual_duration) as t FROM activity_logs WHERE user_id=? AND start_time LIKE ?",
        (uid, target+"%")
    ).fetchone()["t"] or 0
    done  = db.execute("SELECT COUNT(*) as c FROM schedule WHERE user_id=? AND date=? AND status='done'", (uid,target)).fetchone()["c"]
    total = db.execute("SELECT COUNT(*) as c FROM schedule WHERE user_id=? AND date=? AND block_type='task'", (uid,target)).fetchone()["c"]
    return jsonify({"planned_min":planned,"actual_min":actual,"done":done,"total":total,
                    "completion_pct":round(done/total*100) if total else 0})

@app.route("/api/analytics/weekly")
def analytics_weekly():
    uid = current_user_id()
    today = date.today()
    week_start = (today - timedelta(days=today.weekday())).isoformat()
    db = get_db()
    rows = db.execute(
        """SELECT date, SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) as done, COUNT(*) as total
           FROM schedule WHERE user_id=? AND date>=? AND block_type='task'
           GROUP BY date ORDER BY date""",
        (uid, week_start)
    ).fetchall()
    return jsonify(rows_to_list(rows))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    init_db()
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_ENV") != "production")
