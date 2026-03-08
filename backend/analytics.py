from datetime import date, timedelta
from database import get_db

def daily_report(user_id: int, target_date: str = None) -> dict:
    if not target_date:
        target_date = date.today().isoformat()
    db = get_db()

    tasks = db.execute(
        """SELECT t.*, c.name as category_name
           FROM tasks t LEFT JOIN categories c ON t.category_id = c.id
           WHERE t.user_id = ? AND DATE(t.created_at) <= ?""",
        (user_id, target_date)
    ).fetchall()

    completed = [t for t in tasks if t["status"] == "completed"]

    logs = db.execute(
        """SELECT * FROM activity_logs
           WHERE user_id = ? AND DATE(start_time) = ?""",
        (user_id, target_date)
    ).fetchall()

    hours_worked = sum(l["actual_duration"] or 0 for l in logs)

    scheduled = db.execute(
        "SELECT * FROM schedule WHERE user_id = ? AND date = ?",
        (user_id, target_date)
    ).fetchall()

    scheduled_count = len([s for s in scheduled if s["item_type"] == "task"])
    completed_today = len([
        s for s in scheduled
        if s["item_type"] == "task" and s["task_id"] in
        [t["id"] for t in completed]
    ])
    completion_pct = round(completed_today / scheduled_count * 100, 1) if scheduled_count else 0

    db.close()
    return {
        "date": target_date,
        "scheduled_tasks": scheduled_count,
        "completed_tasks": completed_today,
        "completion_pct": completion_pct,
        "hours_worked": round(hours_worked, 2),
    }

def weekly_report(user_id: int) -> dict:
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    days = [(week_start + timedelta(days=i)).isoformat() for i in range(7)]

    db = get_db()
    logs = db.execute(
        """SELECT DATE(start_time) as log_date, SUM(actual_duration) as hours
           FROM activity_logs
           WHERE user_id = ? AND DATE(start_time) >= ?
           GROUP BY DATE(start_time)""",
        (user_id, week_start.isoformat())
    ).fetchall()

    daily_hours = {l["log_date"]: round(l["hours"] or 0, 2) for l in logs}
    day_reports = [{"date": d, "hours": daily_hours.get(d, 0)} for d in days]

    most_productive = max(day_reports, key=lambda x: x["hours"], default={"date": "-", "hours": 0})

    tasks_completed = db.execute(
        """SELECT COUNT(*) as cnt FROM tasks
           WHERE user_id = ? AND status = 'completed'""",
        (user_id,)
    ).fetchone()

    total_hours = sum(r["hours"] for r in day_reports)
    db.close()

    return {
        "week_start": week_start.isoformat(),
        "daily_breakdown": day_reports,
        "total_hours": round(total_hours, 2),
        "tasks_completed": tasks_completed["cnt"],
        "most_productive_day": most_productive,
    }

def monthly_report(user_id: int) -> dict:
    today = date.today()
    month_start = today.replace(day=1).isoformat()

    db = get_db()

    cat_data = db.execute(
        """SELECT c.name, c.color, COUNT(t.id) as task_count,
                  SUM(t.duration) as total_hours
           FROM tasks t
           JOIN categories c ON t.category_id = c.id
           WHERE t.user_id = ? AND t.status = 'completed'
             AND DATE(t.created_at) >= ?
           GROUP BY c.id""",
        (user_id, month_start)
    ).fetchall()

    logs = db.execute(
        """SELECT DATE(start_time) as log_date, SUM(actual_duration) as hours
           FROM activity_logs
           WHERE user_id = ? AND DATE(start_time) >= ?
           GROUP BY DATE(start_time)
           ORDER BY log_date""",
        (user_id, month_start)
    ).fetchall()

    db.close()

    return {
        "month": today.strftime("%B %Y"),
        "category_breakdown": [dict(c) for c in cat_data],
        "daily_trend": [{"date": l["log_date"], "hours": round(l["hours"] or 0, 2)} for l in logs],
        "total_hours": round(sum(l["hours"] or 0 for l in logs), 2),
    }
