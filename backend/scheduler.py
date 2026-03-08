"""
AI Scheduler Engine
===================
Produces a daily timetable by:
1. Loading user's wake/sleep window
2. Placing locked schedule items (immovable)
3. Placing enabled routines in their preferred slots
4. Calculating urgency for pending tasks
5. Fitting tasks into remaining free slots (splitting across days if needed)
6. Persisting the schedule to the DB
"""

from datetime import datetime, date, timedelta
from database import get_db

TIME_BANDS = {
    "morning":   ("06:00", "12:00"),
    "afternoon": ("12:00", "17:00"),
    "evening":   ("17:00", "21:00"),
    "night":     ("21:00", "23:59"),
    "any":       None,
}

def hhmm_to_minutes(t: str) -> int:
    """Convert 'HH:MM' string to minutes since midnight."""
    h, m = map(int, t.split(":"))
    return h * 60 + m

def minutes_to_hhmm(minutes: int) -> str:
    minutes = max(0, min(1439, int(minutes)))
    return f"{minutes // 60:02d}:{minutes % 60:02d}"

def build_free_slots(wake: str, sleep: str, blocked: list) -> list:
    """
    Given wake/sleep times and a list of blocked intervals [(start_min, end_min)],
    return list of free intervals [(start_min, end_min)].
    """
    day_start = hhmm_to_minutes(wake)
    day_end   = hhmm_to_minutes(sleep)

    # Sort and merge blocked intervals
    blocked_sorted = sorted(blocked, key=lambda x: x[0])
    merged = []
    for s, e in blocked_sorted:
        s, e = max(s, day_start), min(e, day_end)
        if s >= e:
            continue
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))

    free = []
    cursor = day_start
    for s, e in merged:
        if cursor < s:
            free.append((cursor, s))
        cursor = max(cursor, e)
    if cursor < day_end:
        free.append((cursor, day_end))
    return free

def preferred_band(pref: str):
    band = TIME_BANDS.get(pref)
    if band:
        return hhmm_to_minutes(band[0]), hhmm_to_minutes(band[1])
    return None

def fit_into_slots(slots: list, duration_min: int, pref_band=None):
    """
    Find the best (start, end) in slots where duration_min fits.
    Prefers slots inside pref_band if given.
    Returns (slot_index, start_min, end_min) or None.
    """
    # First pass: try preferred band
    if pref_band:
        pb_start, pb_end = pref_band
        for i, (s, e) in enumerate(slots):
            overlap_s = max(s, pb_start)
            overlap_e = min(e, pb_end)
            if overlap_e - overlap_s >= duration_min:
                return i, overlap_s, overlap_s + duration_min

    # Second pass: any slot
    for i, (s, e) in enumerate(slots):
        if e - s >= duration_min:
            return i, s, s + duration_min
    return None

def consume_slot(slots: list, idx: int, used_start: int, used_end: int) -> list:
    """Remove used time from slot, may split into two."""
    s, e = slots[idx]
    new_slots = slots[:idx]
    if s < used_start:
        new_slots.append((s, used_start))
    if used_end < e:
        new_slots.append((used_end, e))
    new_slots.extend(slots[idx+1:])
    return new_slots

def calculate_urgency(task: dict, today: date, free_minutes_today: int) -> float:
    """
    urgency = remaining_duration_in_minutes / free_minutes_before_deadline
    Higher = more urgent. Tasks without deadlines get lower urgency.
    """
    remaining_min = task["remaining_duration"] * 60
    if not task["deadline"]:
        return remaining_min / max(free_minutes_today, 1) * 0.5

    try:
        dl_str = task["deadline"].strip()
        # Support both "YYYY-MM-DD" and "YYYY-MM-DD HH:mm"
        if " " in dl_str:
            dl = datetime.strptime(dl_str, "%Y-%m-%d %H:%M").date()
        else:
            dl = datetime.strptime(dl_str, "%Y-%m-%d").date()
    except Exception:
        return remaining_min / max(free_minutes_today, 1) * 0.5

    days_left = max((dl - today).days, 0) + 1
    free_total = days_left * free_minutes_today
    return remaining_min / max(free_total, 1)

def generate_schedule(user_id: int, target_date: date = None):
    """
    Main entry point. Generates schedule for target_date (default: today).
    Clears existing non-locked entries for the day, then fills in.
    Returns list of schedule items.
    """
    if target_date is None:
        target_date = date.today()

    date_str = target_date.isoformat()
    db = get_db()

    # --- Load user preferences ---
    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    wake  = user["wake_time"]  or "07:00"
    sleep = user["sleep_time"] or "23:00"

    # --- Remove existing non-locked schedule entries for the day ---
    db.execute(
        "DELETE FROM schedule WHERE user_id = ? AND date = ? AND locked = 0",
        (user_id, date_str)
    )
    db.commit()

    # --- Load locked entries (user-fixed items) ---
    locked_entries = db.execute(
        "SELECT * FROM schedule WHERE user_id = ? AND date = ? AND locked = 1",
        (user_id, date_str)
    ).fetchall()

    blocked = []
    schedule_items = []
    for le in locked_entries:
        s = hhmm_to_minutes(le["start_time"])
        e = hhmm_to_minutes(le["end_time"])
        blocked.append((s, e))
        schedule_items.append(dict(le))

    # --- Load enabled routines ---
    routines = db.execute(
        "SELECT * FROM routines WHERE user_id = ? AND enabled = 1",
        (user_id,)
    ).fetchall()

    # We need initial free slots to place routines
    free_slots = build_free_slots(wake, sleep, blocked)
    total_free_min = sum(e - s for s, e in free_slots)

    routine_items = []
    for r in routines:
        dur_min = int(r["duration"] * 60)
        pb = preferred_band(r["preferred_time"])
        result = fit_into_slots(free_slots, dur_min, pb)
        if result:
            idx, start, end = result
            free_slots = consume_slot(free_slots, idx, start, end)
            item = {
                "user_id": user_id,
                "task_id": None,
                "routine_id": r["id"],
                "date": date_str,
                "start_time": minutes_to_hhmm(start),
                "end_time": minutes_to_hhmm(end),
                "locked": 0,
                "item_type": "routine",
                "title": r["title"],
            }
            routine_items.append(item)

    # Recalculate free after routines
    free_slots = build_free_slots(wake, sleep, blocked + [
        (hhmm_to_minutes(i["start_time"]), hhmm_to_minutes(i["end_time"]))
        for i in routine_items
    ])
    total_free_min = sum(e - s for s, e in free_slots)

    # --- Load pending tasks ---
    tasks = db.execute(
        """SELECT t.*, c.name as category_name, c.color as category_color
           FROM tasks t
           LEFT JOIN categories c ON t.category_id = c.id
           WHERE t.user_id = ? AND t.status IN ('pending', 'in_progress')
           ORDER BY t.created_at""",
        (user_id,)
    ).fetchall()
    tasks = [dict(t) for t in tasks]

    # --- Calculate urgency and sort ---
    for t in tasks:
        t["urgency"] = calculate_urgency(t, target_date, total_free_min)
    tasks.sort(key=lambda t: t["urgency"], reverse=True)

    # --- Assign tasks to free slots ---
    task_items = []
    for task in tasks:
        remaining_min = int(task["remaining_duration"] * 60)
        if remaining_min <= 0:
            continue

        pb = preferred_band(task["preferred_time"])

        while remaining_min > 0 and free_slots:
            result = fit_into_slots(free_slots, remaining_min, pb)
            if result:
                # Fits entirely
                idx, start, end = result
                free_slots = consume_slot(free_slots, idx, start, end)
                item = {
                    "user_id": user_id,
                    "task_id": task["id"],
                    "routine_id": None,
                    "date": date_str,
                    "start_time": minutes_to_hhmm(start),
                    "end_time": minutes_to_hhmm(end),
                    "locked": 0,
                    "item_type": "task",
                    "title": task["title"],
                }
                task_items.append(item)
                remaining_min = 0
            else:
                # Try to fill the largest available slot (splitting)
                if not free_slots:
                    break
                largest = max(free_slots, key=lambda x: x[1] - x[0])
                avail = largest[1] - largest[0]
                if avail < 10:  # don't schedule fragments < 10 min
                    break
                idx = free_slots.index(largest)
                start = largest[0]
                end = largest[1]
                free_slots = consume_slot(free_slots, idx, start, end)
                item = {
                    "user_id": user_id,
                    "task_id": task["id"],
                    "routine_id": None,
                    "date": date_str,
                    "start_time": minutes_to_hhmm(start),
                    "end_time": minutes_to_hhmm(end),
                    "locked": 0,
                    "item_type": "task",
                    "title": task["title"],
                }
                task_items.append(item)
                remaining_min -= avail
                # Remaining will be scheduled on future days via multi-day splits
                break

    # --- Persist schedule to DB ---
    for item in routine_items + task_items:
        db.execute(
            """INSERT INTO schedule (user_id, task_id, routine_id, date,
               start_time, end_time, locked, item_type, title)
               VALUES (:user_id, :task_id, :routine_id, :date,
               :start_time, :end_time, :locked, :item_type, :title)""",
            item
        )
    db.commit()

    # --- Return full schedule for the day (sorted) ---
    rows = db.execute(
        """SELECT s.*, t.status as task_status, t.category_id,
                  c.name as category_name, c.color as category_color
           FROM schedule s
           LEFT JOIN tasks t ON s.task_id = t.id
           LEFT JOIN categories c ON t.category_id = c.id
           WHERE s.user_id = ? AND s.date = ?
           ORDER BY s.start_time""",
        (user_id, date_str)
    ).fetchall()
    db.close()

    return [dict(r) for r in rows]


def schedule_multi_day(user_id: int, days_ahead: int = 7):
    """Generate schedules for today + days_ahead to handle task splitting."""
    today = date.today()
    results = {}
    for i in range(days_ahead):
        d = today + timedelta(days=i)
        results[d.isoformat()] = generate_schedule(user_id, d)
    return results
