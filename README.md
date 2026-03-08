# TaskMind — AI Task Planner

An intelligent personal productivity assistant that automatically schedules tasks into a daily timetable, considering routines, deadlines, durations, and available time.

---

## Features

- **AI Scheduling Engine** — urgency-based auto-scheduling with task splitting across days
- **Routine Management** — daily habits placed in preferred time bands
- **Time Tracking** — start/stop timers with actual duration logging
- **Dynamic Replanning** — recalculate any time conditions change
- **Productivity Analytics** — daily, weekly, and monthly reports with charts
- **Browser Notifications** — 30-minute reminders before scheduled tasks
- **Locked Tasks** — manually fix a time slot and the scheduler respects it

---

## Project Structure

```
ai-task-planner/
├── backend/
│   ├── app.py          # Flask app + all API routes
│   ├── auth.py         # Registration, login, password hashing
│   ├── database.py     # SQLite init + connection helper
│   ├── scheduler.py    # Core AI scheduling engine
│   └── analytics.py    # Report generation
├── frontend/
│   ├── templates/
│   │   └── index.html  # Single-page app shell
│   └── static/
│       ├── css/main.css
│       └── js/app.js
├── requirements.txt
├── render.yaml
└── Procfile
```

---

## Local Development

### Prerequisites
- Python 3.10+

### Setup

```bash
# Clone / enter project
cd ai-task-planner

# Install dependencies
pip install -r requirements.txt

# Run the server
python backend/app.py
```

Open **http://localhost:5000** in your browser.

The SQLite database (`taskplanner.db`) is created automatically on first run.

---

## Scheduler Engine Logic

The engine (`backend/scheduler.py`) runs these steps on demand:

1. **Load user preferences** — wake/sleep window
2. **Load locked entries** — items the user has manually fixed
3. **Build free time slots** — subtract locked times from the day
4. **Place routines** — insert enabled routines into their preferred bands
5. **Calculate urgency** for each pending task:
   ```
   urgency = remaining_minutes / free_minutes_before_deadline
   ```
6. **Sort tasks** by urgency (most urgent first)
7. **Assign tasks to slots** — fit entirely if possible, else split remainder to future days
8. **Persist** the schedule to the `schedule` table
9. **Return** the full day's timeline

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/register` | Create account |
| POST | `/api/auth/login` | Sign in |
| POST | `/api/auth/logout` | Sign out |
| GET  | `/api/auth/me` | Current user |
| GET/POST | `/api/tasks` | List / create tasks |
| PUT/DELETE | `/api/tasks/:id` | Update / delete task |
| POST | `/api/tasks/:id/complete` | Mark complete |
| POST | `/api/tasks/:id/start` | Start timer |
| POST | `/api/tasks/:id/stop` | Stop timer |
| GET/POST | `/api/routines` | List / create routines |
| PUT/DELETE | `/api/routines/:id` | Update / delete routine |
| GET  | `/api/schedule?date=` | Get schedule for date |
| POST | `/api/schedule/recalculate` | Regenerate schedule |
| POST | `/api/schedule/:id/lock` | Lock a schedule item |
| GET  | `/api/reports/daily` | Daily analytics |
| GET  | `/api/reports/weekly` | Weekly analytics |
| GET  | `/api/reports/monthly` | Monthly analytics |
| PUT  | `/api/settings` | Update user settings |
| GET/POST | `/api/categories` | List / create categories |
| DELETE | `/api/categories/:id` | Delete category |

---

## Deployment on Render

1. Push to a GitHub repo
2. Create a new **Web Service** on [render.com](https://render.com)
3. Connect your repo — Render will detect `render.yaml` automatically
4. A persistent disk is configured for the SQLite DB
5. `SECRET_KEY` is auto-generated

For production, consider upgrading to PostgreSQL by replacing the SQLite driver with `psycopg2` and updating `get_db()`.

---

## Extending the App

- **PWA Push Notifications** — add a service worker + Web Push API
- **Drag-and-drop scheduling** — allow reordering timeline items
- **Google Calendar sync** — import events as blocked time slots
- **AI priority suggestions** — call an LLM to re-score task priorities
- **Mobile app** — the PWA manifest can make it installable on iOS/Android
