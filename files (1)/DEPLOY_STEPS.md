# 🚀 Deploy AI Task Planner — Step by Step
## Target: Render.com (free) + Telegram notifications on Android

---

## PHASE 1 — Set Up Telegram Bot (5 minutes)

### Step 1.1 — Create your bot
1. Open Telegram on your Android phone
2. Search for **@BotFather** → tap it → tap START
3. Send:  `/newbot`
4. Give it a name:  `My Task Planner`
5. Give it a username:  `mytaskplanner_bot`  (must end in _bot)
6. BotFather replies with your **TOKEN** — looks like:
   ```
   7412583901:AAHdqTcvCHhvQXDLx9q3n8vVKFh2abc1234
   ```
   📋 **Copy and save this token**

### Step 1.2 — Get your Chat ID
1. Search for **@userinfobot** on Telegram → tap START
2. It instantly replies with your **Id** number, like:  `928374651`
3. 📋 **Copy and save this number**

### Step 1.3 — Test it manually (optional)
Open this URL in your browser (replace TOKEN and CHAT_ID):
```
https://api.telegram.org/botYOUR_TOKEN/sendMessage?chat_id=YOUR_CHAT_ID&text=Hello!
```
You should receive "Hello!" on Telegram.

---

## PHASE 2 — Push Code to GitHub (5 minutes)

### Step 2.1 — Install Git (if not already)
- Windows: https://git-scm.com/download/win  → install → restart terminal
- Already on Linux/Mac

### Step 2.2 — Create GitHub account
Go to https://github.com → Sign Up (free)

### Step 2.3 — Create a new repository
1. Click **+** → **New repository**
2. Name: `ai-task-planner`
3. Set to **Private** (recommended)
4. Click **Create repository**

### Step 2.4 — Push your code
Open terminal/command prompt in your `ai_planner` folder:

```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/ai-task-planner.git
git push -u origin main
```

---

## PHASE 3 — Deploy on Render (10 minutes)

### Step 3.1 — Create Render account
Go to https://render.com → **Get Started for Free**
Sign up with your GitHub account (easiest)

### Step 3.2 — Create Web Service
1. Click **+ New** → **Web Service**
2. Click **Connect a repository**
3. Select your `ai-task-planner` repo
4. Click **Connect**

### Step 3.3 — Configure the service
Fill in these fields:

| Field | Value |
|-------|-------|
| Name | `ai-task-planner` |
| Region | Singapore (closest to India) |
| Branch | `main` |
| Runtime | `Python 3` |
| Build Command | `pip install -r requirements.txt && python database.py` |
| Start Command | `gunicorn app:app --workers 1 --threads 2 --bind 0.0.0.0:$PORT --timeout 120` |
| Instance Type | **Free** |

### Step 3.4 — Add environment variables
Scroll down to **Environment Variables** → Add these:

| Key | Value |
|-----|-------|
| `TELEGRAM_TOKEN` | your token from Step 1.1 |
| `TELEGRAM_CHAT_ID` | your chat ID from Step 1.2 |
| `FLASK_ENV` | `production` |
| `SECRET_KEY` | any random string like `abc123xyz789` |

### Step 3.5 — Add Persistent Disk (IMPORTANT — keeps your data!)
1. Scroll to **Disks** section
2. Click **Add Disk**
3. Fill in:
   - Name: `planner-data`
   - Mount Path: `/data`
   - Size: `1 GB` (free)
4. Click **Save**

### Step 3.6 — Deploy!
Click **Create Web Service**

Render will now:
- Install dependencies (~2 min)
- Initialize the database
- Start your app

Watch the logs at the bottom. When you see:
```
[DB] Initialized: /data/planner.db
* Running on http://0.0.0.0:10000
```
✅ Your app is live!

Your URL will be: `https://ai-task-planner.onrender.com`

You'll also get a **Telegram message** confirming notifications are connected! 🎉

---

## PHASE 4 — Prevent Sleep (Free tier workaround)

Render free tier sleeps after 15 min of inactivity.
Fix: use **UptimeRobot** (free) to ping your app every 5 minutes.

### Step 4.1
1. Go to https://uptimerobot.com → Sign Up Free
2. Click **+ Add New Monitor**
3. Settings:
   - Monitor Type: **HTTP(s)**
   - Friendly Name: `AI Planner`
   - URL: `https://ai-task-planner.onrender.com/ping`
   - Monitoring Interval: **5 minutes**
4. Click **Create Monitor**

✅ Your app now stays awake 24/7 for free.

---

## PHASE 5 — Use it on Android

### Option A — Use in Chrome (easiest)
1. Open Chrome on Android
2. Go to `https://ai-task-planner.onrender.com`
3. Tap the 3-dot menu → **Add to Home Screen**
4. Now it opens like an app from your home screen!

### Option B — Install as PWA
The app has a PWA manifest, so Chrome will show an install prompt automatically.

---

## DONE! Here's what you have:

```
🌐 Web app:     https://ai-task-planner.onrender.com
📱 Mobile:      Add to Home Screen in Chrome
🔔 Telegram:    Notifications to your phone without any app open
💾 Database:    Persistent on Render disk — data never lost
⏰ Keep-alive:  UptimeRobot pings /ping every 5 min
```

---

## Updating your app later

When you make code changes:
```bash
git add .
git commit -m "Update: describe what changed"
git push
```
Render auto-deploys on every push. Takes ~2 minutes.

---

## Troubleshooting

**App not loading:**
- Check Render logs: Dashboard → your service → Logs tab

**Telegram not sending:**
- Verify TOKEN and CHAT_ID in Render → Environment tab
- Make sure you messaged your bot at least once (send /start to it)

**Data disappeared:**
- Make sure you added the `/data` disk in Render
- Check PLANNER_DB env var is not set to wrong path

**Still sleeping despite UptimeRobot:**
- Check UptimeRobot shows the monitor as UP (green)
- Try changing interval to 4 minutes
