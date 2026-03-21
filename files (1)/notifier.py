#!/usr/bin/env python3
"""
Notification Daemon — Telegram edition
Runs as a background thread inside Flask on Render.
"""

import sqlite3, time, json, os, logging, threading, urllib.request, urllib.error
from datetime import datetime, timedelta, date

log = logging.getLogger("notifier")

DB_PATH    = os.environ.get("PLANNER_DB", "planner.db")
TG_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TG_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
POLL_INTERVAL = 60
USER_ID = 1

_last_overdue_check    = None
_last_free_slot_check  = None
_last_weekly_check     = None


def send_telegram(title: str, message: str, urgent: bool = False) -> bool:
    if not TG_TOKEN or not TG_CHAT_ID:
        log.warning("Telegram not configured")
        return False
    icon = "🚨" if urgent else "📋"
    text = f"{icon} *{title}*\n{message}"
    payload = json.dumps({
        "chat_id": TG_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_notification": not urgent,
    }).encode()
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            if result.get("ok"):
                log.info(f"[Telegram] Sent: {title}")
                return True
            log.error(f"[Telegram] API error: {result}")
            return False
    except Exception as e:
        log.error(f"[Telegram] Error: {e}")
        return False


def test_telegram():
    return send_telegram("AI Task Planner Connected ✅",
        "Notifications are live! You'll receive reminders here.", urgent=True)


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def mark_sent(conn, notif_id):
    conn.execute("UPDATE notifications SET sent=1, sent_at=? WHERE id=?",
                 (datetime.utcnow().isoformat(), notif_id))
    conn.commit()


def ist_now():
    return datetime.utcnow() + timedelta(hours=5, minutes=30)


def check_task_reminders(conn):
    now = ist_now()
    today = now.date().isoformat()
    rows = conn.execute(
        "SELECT title, start_time FROM schedule WHERE user_id=? AND date=? AND status='pending' AND block_type='task'",
        (USER_ID, today)
    ).fetchall()
    for row in rows:
        try:
            h, m = map(int, row["start_time"].split(":"))
            task_start = now.replace(hour=h, minute=m, second=0, microsecond=0)
            delta = (task_start - now).total_seconds() / 60
            if 55 <= delta <= 65:
                send_telegram(f"⏰ Starting soon: {row['title']}",
                    f"Scheduled at *{row['start_time']}* (~1 hour away)\nOpen planner to start tracking.", urgent=True)
        except Exception:
            pass


def check_pending_db_notifications(conn):
    now = datetime.utcnow().isoformat()
    rows = conn.execute(
        "SELECT * FROM notifications WHERE user_id=? AND sent=0 AND scheduled_at <= ? ORDER BY scheduled_at ASC LIMIT 5",
        (USER_ID, now)
    ).fetchall()
    for row in rows:
        urgent = row["type"] in ("warning", "overload", "reminder")
        send_telegram(row["title"], row["message"], urgent=urgent)
        mark_sent(conn, row["id"])


def check_overdue_tasks(conn, now):
    today = now.date().isoformat()
    result = conn.execute(
        "SELECT COUNT(*) as cnt, GROUP_CONCAT(title, ', ') as titles FROM tasks WHERE user_id=? AND status!='done' AND deadline < ? AND deadline IS NOT NULL",
        (USER_ID, today)
    ).fetchone()
    if result and result["cnt"] > 0:
        send_telegram("🚨 Overdue Tasks",
            f"You have *{result['cnt']}* overdue task(s):\n_{result['titles']}_\n\nOpen planner to reschedule.", urgent=True)


def check_free_slot_recommendation(conn, now):
    today = now.date().isoformat()
    now_time = now.strftime("%H:%M")
    active = conn.execute(
        "SELECT COUNT(*) as cnt FROM schedule WHERE user_id=? AND date=? AND status='pending' AND start_time <= ? AND end_time > ?",
        (USER_ID, today, now_time, now_time)
    ).fetchone()["cnt"]
    if active > 0:
        return
    task = conn.execute(
        "SELECT title, COALESCE(remaining_duration, duration_min) as dur FROM tasks WHERE user_id=? AND status='todo' ORDER BY priority DESC, dur ASC LIMIT 1",
        (USER_ID,)
    ).fetchone()
    if task:
        send_telegram("💡 Free Time Detected",
            f"Nothing scheduled right now!\nSuggested: *{task['title']}* ({task['dur']} min)\n\nOpen planner to get started.")


def check_weekly_summary(conn, now):
    if not (now.weekday() == 6 and now.hour == 19 and now.minute < 2):
        return
    week_ago = (now.date() - timedelta(days=7)).isoformat()
    stats = conn.execute(
        "SELECT COUNT(*) as total, SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) as done, SUM(actual_duration) as minutes FROM activity_logs WHERE user_id=? AND start_time >= ?",
        (USER_ID, week_ago + "T00:00")
    ).fetchone()
    total = stats["total"] or 0
    done  = stats["done"] or 0
    mins  = stats["minutes"] or 0
    pct   = round(done / total * 100) if total else 0
    hours = mins // 60
    emoji = "🔥" if pct >= 80 else "📈" if pct >= 50 else "💪"
    send_telegram("📊 Weekly Summary",
        f"Tasks: *{done}/{total}* ({pct}%)\nWork time: *{hours}h {mins%60}m*\n{emoji} {'Great week!' if pct >= 70 else 'Keep pushing!'}")


def daemon_loop():
    global _last_overdue_check, _last_free_slot_check, _last_weekly_check
    log.info("Notification daemon started (Telegram mode, IST)")
    if TG_TOKEN and TG_CHAT_ID:
        test_telegram()
    else:
        log.warning("Telegram not configured — set TELEGRAM_TOKEN and TELEGRAM_CHAT_ID")

    while True:
        try:
            conn = get_conn()
            now = ist_now()
            today_str = now.date().isoformat()

            check_pending_db_notifications(conn)
            check_task_reminders(conn)

            if _last_overdue_check != today_str and now.hour >= 8:
                check_overdue_tasks(conn, now)
                _last_overdue_check = today_str

            slot_key = f"{today_str}-{now.hour}-{(now.minute//30)*30}"
            if _last_free_slot_check != slot_key and now.minute % 30 == 0:
                check_free_slot_recommendation(conn, now)
                _last_free_slot_check = slot_key

            week_key = f"{now.year}-{now.isocalendar()[1]}"
            if _last_weekly_check != week_key and now.weekday() == 6 and now.hour >= 19:
                check_weekly_summary(conn, now)
                _last_weekly_check = week_key

            conn.close()
        except Exception as e:
            log.error(f"Daemon error: {e}", exc_info=True)
        time.sleep(POLL_INTERVAL)


def start_daemon_thread():
    t = threading.Thread(target=daemon_loop, daemon=True)
    t.start()
    log.info("Notification daemon thread started")
    return t


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    daemon_loop()
