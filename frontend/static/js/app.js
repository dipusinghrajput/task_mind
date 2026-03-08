/* TaskMind — Mobile-first SPA with full notification system */

const state = {
  user: null, tasks: [], routines: [], categories: [],
  schedule: [], activeFilter: "all", activeReport: "daily",
  reportChart: null, sw: null, notifLeadMin: 15,
};

/* ── API ───────────────────────────────────────────────────────────────── */
async function api(method, path, body = null) {
  const opts = { method, headers: { "Content-Type": "application/json" }, credentials: "include" };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  return { ok: res.ok, status: res.status, data };
}

/* ── Toast ─────────────────────────────────────────────────────────────── */
let toastTimer;
function showToast(msg, type = "info") {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.className = `toast ${type}`;
  el.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add("hidden"), 3000);
}

/* ── Navigation ────────────────────────────────────────────────────────── */
function navigateTo(page) {
  document.querySelectorAll(".page").forEach(p => p.classList.remove("active"));
  document.querySelectorAll(".bn-item").forEach(l => l.classList.remove("active"));
  const pg = document.getElementById(`page-${page}`);
  if (pg) pg.classList.add("active");
  const link = document.querySelector(`.bn-item[data-page="${page}"]`);
  if (link) link.classList.add("active");
  if (page === "dashboard") loadDashboard();
  if (page === "tasks")     loadTasks();
  if (page === "routines")  loadRoutines();
  if (page === "reports")   loadReport(state.activeReport);
  if (page === "settings")  loadSettings();
}

/* ── Auth ──────────────────────────────────────────────────────────────── */
async function checkAuth() {
  const { ok, data } = await api("GET", "/api/auth/me");
  if (ok) { state.user = data; showApp(); }
  else showAuth();
}

function showApp() {
  document.getElementById("auth-overlay").style.display = "none";
  document.getElementById("app").classList.remove("hidden");
  const name = state.user.name || state.user.email || "there";
  document.getElementById("dash-name").textContent = name;
  document.getElementById("user-avatar").textContent = name[0].toUpperCase();
  initSW();
  navigateTo("dashboard");
  startClock();
}

function showAuth() {
  document.getElementById("auth-overlay").style.display = "flex";
  document.getElementById("app").classList.add("hidden");
}

/* ═════════════════════════════════════════════════════════════════════════
   SERVICE WORKER + NOTIFICATIONS
   ═════════════════════════════════════════════════════════════════════════ */
async function initSW() {
  if (!("serviceWorker" in navigator)) return;
  try {
    const reg = await navigator.serviceWorker.register("/sw.js", { scope: "/" });
    state.sw = reg;
    console.log("SW registered:", reg.scope);
    updateNotifUI();
  } catch (e) {
    console.warn("SW registration failed:", e);
  }
}

function getNotifPermission() {
  if (!("Notification" in window)) return "unsupported";
  return Notification.permission;
}

function updateNotifUI() {
  const perm = getNotifPermission();
  const statusEl = document.getElementById("notif-status-text");
  const toggleBtn = document.getElementById("notif-toggle-btn");
  const bellDot = document.getElementById("notif-dot");
  const btnLabel = document.getElementById("notif-btn-label");

  if (perm === "unsupported") {
    if (statusEl) statusEl.textContent = "Not supported";
    if (toggleBtn) toggleBtn.textContent = "N/A";
    return;
  }
  if (perm === "granted") {
    if (statusEl) { statusEl.textContent = "Active ✓"; statusEl.className = "notif-status granted"; }
    if (toggleBtn) toggleBtn.textContent = "Enabled";
    if (bellDot) bellDot.classList.remove("hidden");
    if (btnLabel) btnLabel.textContent = "On";
  } else if (perm === "denied") {
    if (statusEl) { statusEl.textContent = "Blocked — allow in browser"; statusEl.className = "notif-status denied"; }
    if (toggleBtn) toggleBtn.textContent = "Blocked";
    if (btnLabel) btnLabel.textContent = "Blocked";
  } else {
    if (statusEl) { statusEl.textContent = "Not enabled"; statusEl.className = "notif-status"; }
    if (toggleBtn) toggleBtn.textContent = "Enable";
    if (btnLabel) btnLabel.textContent = "Notify";
  }
}

async function requestNotifPermission() {
  if (!("Notification" in window)) { showToast("Notifications not supported", "error"); return; }
  if (Notification.permission === "denied") {
    showToast("Blocked — please allow in browser settings", "error"); return;
  }
  const result = await Notification.requestPermission();
  updateNotifUI();
  if (result === "granted") {
    showToast("Notifications enabled! 🔔", "success");
    scheduleNotifications();
    // Show a test notification
    setTimeout(() => {
      sendNotification("TaskMind Active", "You'll get reminders before your tasks start.", "welcome");
    }, 800);
  } else {
    showToast("Permission denied", "error");
  }
}

function sendNotification(title, body, tag = "taskmind") {
  if (Notification.permission !== "granted") return;
  if (state.sw && state.sw.active) {
    // Use SW for reliable delivery (works when tab is in background)
    state.sw.active.postMessage({ type: "SCHEDULE_NOTIF", delay: 0, title, body, tag });
  } else {
    // Fallback to direct Notification API
    new Notification(title, {
      body,
      icon: "/static/icons/icon-192.svg",
      tag,
      vibrate: [200, 100, 200],
    });
  }
}

let scheduledNotifTimers = [];

function scheduleNotifications() {
  // Cancel all previously scheduled timers
  scheduledNotifTimers.forEach(clearTimeout);
  scheduledNotifTimers = [];

  if (Notification.permission !== "granted") return;

  const leadMin = parseInt(document.getElementById("notif-lead-time")?.value || "15", 10);
  const today = new Date().toISOString().split("T")[0];
  const now = Date.now();

  state.schedule.forEach(item => {
    if (item.task_status === "completed") return;
    if (item.date !== today) return;

    const [h, m] = item.start_time.split(":").map(Number);
    const startMs = new Date().setHours(h, m, 0, 0);
    const reminderMs = startMs - leadMin * 60 * 1000;
    const delay = reminderMs - now;

    if (delay <= 0) return; // already passed

    const title = `⏰ Upcoming — ${item.title}`;
    const body  = `Starts at ${item.start_time} (in ${leadMin} min)`;
    const tag   = `task-${item.id}-${item.start_time}`;

    if (state.sw && state.sw.active) {
      // Delegate to SW so notification fires even when tab is backgrounded
      state.sw.active.postMessage({ type: "SCHEDULE_NOTIF", delay, title, body, tag });
      console.log(`Scheduled SW notif: "${item.title}" in ${Math.round(delay/60000)} min`);
    } else {
      // Fallback: setTimeout in page (only works if tab stays open)
      const t = setTimeout(() => {
        try {
          new Notification(title, {
            body,
            icon: "/static/icons/icon-192.svg",
            tag,
            vibrate: [200, 100, 200],
          });
        } catch(e) { console.warn("Notif error:", e); }
      }, delay);
      scheduledNotifTimers.push(t);
      console.log(`Scheduled tab notif: "${item.title}" in ${Math.round(delay/60000)} min`);
    }
  });

  const count = state.schedule.filter(i => i.task_status !== "completed" && i.date === today).length;
  if (count) showToast(`${count} reminder(s) scheduled 🔔`, "success");
}

/* ── Dashboard ─────────────────────────────────────────────────────────── */
async function loadDashboard() {
  const today = new Date().toISOString().split("T")[0];
  const hour = new Date().getHours();
  const greeting = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
  document.getElementById("dash-greeting").textContent = greeting;
  document.getElementById("dash-name").textContent = state.user?.name || state.user?.email || "—";
  document.getElementById("today-date").textContent = new Date().toLocaleDateString(undefined, {
    weekday: "long", month: "long", day: "numeric"
  });

  const [schedRes, rptRes] = await Promise.all([
    api("GET", `/api/schedule?date=${today}`),
    api("GET", `/api/reports/daily?date=${today}`),
  ]);

  if (schedRes.ok) {
    state.schedule = schedRes.data;
    renderTimeline(state.schedule);
    renderUpNext(state.schedule);
    if (Notification.permission === "granted") scheduleNotifications();
  }
  if (rptRes.ok) {
    const r = rptRes.data;
    document.getElementById("stat-scheduled").textContent = r.scheduled_tasks;
    document.getElementById("stat-completed").textContent = r.completed_tasks;
    document.getElementById("stat-hours").textContent = (r.hours_worked || 0) + "h";
    const pct = r.completion_pct || 0;
    document.getElementById("progress-pct").textContent = pct + "%";
    document.getElementById("progress-fill").style.width = pct + "%";
  }
  updateNotifUI();
}

function renderTimeline(items) {
  const list = document.getElementById("timeline-list");
  if (!items.length) {
    list.innerHTML = `<div class="empty-state"><div class="empty-icon">&#x25C8;</div><p>No schedule yet.<br/>Add tasks and tap Recalculate.</p></div>`;
    return;
  }
  list.innerHTML = items.map(item => {
    const isRoutine = item.item_type === "routine";
    const status = item.task_status || "";
    let cls = isRoutine ? "routine" : "task";
    if (status === "completed") cls = "completed";
    if (status === "in_progress") cls = "in-progress";

    const actionBtns = isRoutine || status === "completed" ? "" : `
      ${status === "in_progress"
        ? `<button class="tl-btn stop" onclick="stopTask(${item.task_id})" title="Stop">&#x23F9;</button>`
        : `<button class="tl-btn play" onclick="startTask(${item.task_id})" title="Start">&#x25B6;</button>`
      }
      <button class="tl-btn done" onclick="completeTask(${item.task_id})" title="Done">&#x2713;</button>
    `;

    const catChip = item.category_name
      ? `<span class="tl-chip" style="color:${item.category_color};border-color:${item.category_color}33">${item.category_name}</span>`
      : "";
    const typeChip = `<span class="tl-chip">${isRoutine ? "routine" : status || "pending"}</span>`;

    return `<div class="tl-item ${cls}">
      <div class="tl-time-col">
        <div class="tl-start">${item.start_time}</div>
        <div class="tl-end">${item.end_time}</div>
      </div>
      <div class="tl-body">
        <div class="tl-title">${esc(item.title)}</div>
        <div class="tl-chips">${catChip}${typeChip}</div>
      </div>
      <div class="tl-actions">${actionBtns}</div>
    </div>`;
  }).join("");
}

function renderUpNext(items) {
  const el = document.getElementById("up-next-card");
  const now = new Date();
  const nowMin = now.getHours() * 60 + now.getMinutes();
  const next = items.find(i => {
    if (i.task_status === "completed") return false;
    const [h,m] = i.start_time.split(":").map(Number);
    return h * 60 + m > nowMin;
  });
  if (!next) { el.innerHTML = `<div class="un-empty">Nothing coming up today</div>`; return; }
  const [h,m] = next.start_time.split(":").map(Number);
  const diffMin = h * 60 + m - nowMin;
  const eta = diffMin < 60 ? `${diffMin} min` : `${Math.round(diffMin/60)}h ${diffMin%60}m`;
  el.innerHTML = `
    <div class="un-time">Starts at ${next.start_time} &nbsp;·&nbsp; in ${eta}</div>
    <div class="un-title">${esc(next.title)}</div>
    ${next.category_name ? `<div class="un-cat" style="color:${next.category_color}">${next.category_name}</div>` : ""}
    ${next.item_type !== "routine" && next.task_status !== "completed"
      ? `<button class="un-start-btn" onclick="startTask(${next.task_id})">&#x25B6; Start Now</button>` : ""}
  `;
}

function startClock() {
  const tick = () => {
    const n = new Date();
    const t = `${String(n.getHours()).padStart(2,"0")}:${String(n.getMinutes()).padStart(2,"0")}`;
    document.getElementById("current-time-display").textContent = t;
  };
  tick(); setInterval(tick, 30000);
}

/* ── Tasks ─────────────────────────────────────────────────────────────── */
async function loadTasks() {
  const [tr, cr] = await Promise.all([api("GET", "/api/tasks"), api("GET", "/api/categories")]);
  if (tr.ok) state.tasks = tr.data;
  if (cr.ok) state.categories = cr.data;
  renderTasks();
}

function renderTasks() {
  const el = document.getElementById("tasks-list");
  let tasks = state.tasks;
  if (state.activeFilter !== "all") tasks = tasks.filter(t => t.status === state.activeFilter);
  if (!tasks.length) {
    el.innerHTML = `<div class="empty-state"><div class="empty-icon">&#x25FB;</div><p>No tasks found.</p></div>`;
    return;
  }
  el.innerHTML = tasks.map(t => {
    const pct = t.duration > 0 ? Math.round(((t.duration - t.remaining_duration) / t.duration) * 100) : 100;
    const isUrgent = t.deadline && daysBefore(t.deadline) <= 1;
    const color = t.category_color || "#7c6cf8";
    return `<div class="task-item">
      <div class="task-item-top">
        <div class="task-color-bar" style="background:${color}"></div>
        <div class="task-title-text">${esc(t.title)}</div>
      </div>
      <div class="task-meta">
        <span class="task-chip">${t.duration}h</span>
        ${t.deadline ? `<span class="task-chip ${isUrgent ? "urgent" : "deadline"}">&#x1F4C5; ${formatDeadlineDisplay(t.deadline)}</span>` : ""}
        ${t.category_name ? `<span class="task-chip" style="color:${color}">${t.category_name}</span>` : ""}
        ${t.preferred_time !== "any" ? `<span class="task-chip">${t.preferred_time}</span>` : ""}
      </div>
      <div class="task-bottom">
        <span class="task-status-badge s-${t.status}">${t.status.replace("_"," ")}</span>
        <div class="task-actions">
          ${t.status !== "completed" ? `<button class="task-action-btn done" onclick="completeTask(${t.id})">Done</button>` : ""}
          <button class="task-action-btn edit" onclick="editTask(${t.id})">Edit</button>
          <button class="task-action-btn del" onclick="deleteTask(${t.id})">Del</button>
        </div>
      </div>
      <div class="task-progress"><div class="task-progress-fill" style="width:${pct}%"></div></div>
    </div>`;
  }).join("");
}

function daysBefore(d) {
  // handles "YYYY-MM-DD" or "YYYY-MM-DD HH:mm"
  const iso = d.includes(" ") ? d.replace(" ", "T") : d + "T23:59:00";
  return Math.ceil((new Date(iso) - new Date()) / 86400000);
}

function formatDeadlineDisplay(dl) {
  if (!dl) return "";
  const [datePart, timePart] = dl.split(" ");
  const [y, m, d] = datePart.split("-");
  return timePart ? `${d}-${m}-${y} ${timePart}` : `${d}-${m}-${y}`;
}

async function completeTask(id) {
  const { ok } = await api("POST", `/api/tasks/${id}/complete`);
  if (ok) { showToast("Task complete! ✓", "success"); await loadTasks(); loadDashboard(); }
}
async function startTask(id) {
  const { ok } = await api("POST", `/api/tasks/${id}/start`);
  if (ok) { showToast("Task started ▶", "success"); loadDashboard(); }
}
async function stopTask(id) {
  const { ok, data } = await api("POST", `/api/tasks/${id}/stop`);
  if (ok) { showToast(`+${Math.round((data.actual_duration||0)*60)} min logged`, "success"); loadDashboard(); }
}
async function deleteTask(id) {
  if (!confirm("Delete this task?")) return;
  const { ok } = await api("DELETE", `/api/tasks/${id}`);
  if (ok) { showToast("Deleted"); await loadTasks(); }
}
function editTask(id) {
  const t = state.tasks.find(x => x.id === id);
  if (!t) return;
  populateCatSelect("t-category");
  document.getElementById("task-modal-title").textContent = "Edit Task";
  document.getElementById("task-id").value = t.id;
  document.getElementById("t-title").value = t.title;
  document.getElementById("t-duration").value = t.duration;
  // Populate deadline fields
  if (t.deadline) {
    const { dateStr, timeStr } = splitDeadline(t.deadline);
    document.getElementById("t-deadline-date").value = dateStr;
    document.getElementById("t-deadline-time").value = timeStr;
  } else {
    document.getElementById("t-deadline-date").value = "";
    document.getElementById("t-deadline-time").value = "";
  }
  updateDeadlinePreview();
  document.getElementById("t-preferred").value = t.preferred_time || "any";
  document.getElementById("t-category").value = t.category_id || "";
  document.getElementById("t-notes").value = t.notes || "";
  openSheet("task-modal");
}

/* ── Routines ──────────────────────────────────────────────────────────── */
async function loadRoutines() {
  const { ok, data } = await api("GET", "/api/routines");
  if (ok) { state.routines = data; renderRoutines(); }
}
function renderRoutines() {
  const el = document.getElementById("routines-list");
  if (!state.routines.length) {
    el.innerHTML = `<div class="empty-state"><div class="empty-icon">&#x21BA;</div><p>No routines yet.</p></div>`;
    return;
  }
  el.innerHTML = state.routines.map(r => `
    <div class="routine-item ${r.enabled ? "" : "disabled"}" id="ri-${r.id}">
      <label class="toggle-wrap">
        <input type="checkbox" ${r.enabled ? "checked" : ""} onchange="toggleRoutine(${r.id}, this.checked)" />
        <span class="toggle-track"></span>
        <span class="toggle-thumb"></span>
      </label>
      <div class="routine-info">
        <div class="routine-name">${esc(r.title)}</div>
        <div class="routine-meta">${r.duration}h &middot; ${r.preferred_time}</div>
      </div>
      <div class="routine-actions">
        <button class="r-btn" onclick="editRoutine(${r.id})">Edit</button>
        <button class="r-btn del" onclick="deleteRoutine(${r.id})">Del</button>
      </div>
    </div>`).join("");
}
async function toggleRoutine(id, enabled) {
  await api("PUT", `/api/routines/${id}`, { enabled: enabled ? 1 : 0 });
  await loadRoutines();
}
async function deleteRoutine(id) {
  if (!confirm("Delete this routine?")) return;
  await api("DELETE", `/api/routines/${id}`);
  await loadRoutines();
}
function editRoutine(id) {
  const r = state.routines.find(x => x.id === id);
  if (!r) return;
  document.getElementById("routine-modal-title").textContent = "Edit Routine";
  document.getElementById("routine-id").value = r.id;
  document.getElementById("r-title").value = r.title;
  document.getElementById("r-duration").value = r.duration;
  document.getElementById("r-preferred").value = r.preferred_time;
  openSheet("routine-modal");
}

/* ── Reports ───────────────────────────────────────────────────────────── */
async function loadReport(type) {
  state.activeReport = type;
  document.querySelectorAll("[data-report]").forEach(b =>
    b.classList.toggle("active", b.dataset.report === type)
  );
  document.getElementById("cat-breakdown-card").style.display = "none";

  if (type === "daily") {
    const { ok, data } = await api("GET", "/api/reports/daily");
    if (!ok) return;
    setMetrics(data.completed_tasks, data.hours_worked+"h", data.completion_pct+"%");
    const s = await api("GET", `/api/schedule?date=${data.date}`);
    const items = (s.data||[]).filter(i => i.item_type==="task");
    renderBar("Today's Tasks (h)", items.map(i=>i.title.slice(0,12)), items.map(i=>{
      const [sh,sm]=i.start_time.split(":").map(Number);
      const [eh,em]=i.end_time.split(":").map(Number);
      return ((eh*60+em)-(sh*60+sm))/60;
    }));
  } else if (type === "weekly") {
    const { ok, data } = await api("GET", "/api/reports/weekly");
    if (!ok) return;
    setMetrics(data.tasks_completed, data.total_hours+"h", data.most_productive_day?.date || "-");
    renderBar("Hours / Day", data.daily_breakdown.map(d=>d.date.slice(5)), data.daily_breakdown.map(d=>d.hours));
  } else {
    const { ok, data } = await api("GET", "/api/reports/monthly");
    if (!ok) return;
    const tot = data.category_breakdown.reduce((a,c)=>a+c.task_count,0);
    setMetrics(tot, data.total_hours+"h", data.month);
    if (data.daily_trend.length)
      renderLine("Hours / Day — "+data.month, data.daily_trend.map(d=>d.date.slice(5)), data.daily_trend.map(d=>d.hours));
    if (data.category_breakdown.length) {
      document.getElementById("cat-breakdown-card").style.display = "block";
      document.getElementById("cat-breakdown").innerHTML = data.category_breakdown.map(c=>`
        <div class="cat-row">
          <span class="cat-dot" style="background:${c.color}"></span>
          <span class="cat-name-label">${c.name}</span>
          <span class="cat-val-label">${c.task_count} tasks</span>
        </div>`).join("");
    }
  }
}
function setMetrics(a,b,c) {
  document.getElementById("rpt-completed").textContent = a ?? "—";
  document.getElementById("rpt-hours").textContent = b ?? "—";
  document.getElementById("rpt-rate").textContent = c ?? "—";
}
function chartConfig(type, label, labels, values) {
  return {
    type,
    data: {
      labels,
      datasets: [{
        data: values,
        backgroundColor: type==="bar" ? "rgba(124,108,248,0.45)" : "rgba(124,108,248,0.15)",
        borderColor: "#7c6cf8",
        borderWidth: 2,
        borderRadius: type==="bar" ? 6 : 0,
        tension: 0.4, fill: type==="line",
        pointBackgroundColor: "#7c6cf8",
      }]
    },
    options: {
      responsive: true, plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: "#8888aa", font:{size:10} }, grid: { color: "#28284a" } },
        y: { ticks: { color: "#8888aa", font:{size:10} }, grid: { color: "#28284a" }, beginAtZero: true },
      }
    }
  };
}
function renderBar(title, labels, values) {
  document.getElementById("chart-title").textContent = title;
  const ctx = document.getElementById("report-chart").getContext("2d");
  if (state.reportChart) state.reportChart.destroy();
  state.reportChart = new Chart(ctx, chartConfig("bar", title, labels, values));
}
function renderLine(title, labels, values) {
  document.getElementById("chart-title").textContent = title;
  const ctx = document.getElementById("report-chart").getContext("2d");
  if (state.reportChart) state.reportChart.destroy();
  state.reportChart = new Chart(ctx, chartConfig("line", title, labels, values));
}

/* ── Settings ──────────────────────────────────────────────────────────── */
async function loadSettings() {
  const { ok, data } = await api("GET", "/api/auth/me");
  if (ok) {
    document.getElementById("s-name").value = data.name || "";
    document.getElementById("s-wake").value = data.wake_time || "07:00";
    document.getElementById("s-sleep").value = data.sleep_time || "23:00";
  }
  await loadCats();
  updateNotifUI();
}
async function loadCats() {
  const { ok, data } = await api("GET", "/api/categories");
  if (ok) { state.categories = data; renderCats(); }
}
function renderCats() {
  document.getElementById("categories-list").innerHTML = state.categories.map(c => `
    <div class="cat-item">
      <span class="cat-item-dot" style="background:${c.color}"></span>
      <span class="cat-item-name">${esc(c.name)}</span>
      <button class="cat-del-btn" onclick="deleteCat(${c.id})">&#x2715;</button>
    </div>`).join("");
}
async function deleteCat(id) {
  await api("DELETE", `/api/categories/${id}`); await loadCats();
}

/* ── Sheets (modals) ───────────────────────────────────────────────────── */
function openSheet(id) { document.getElementById(id).classList.remove("hidden"); }
function closeSheet(id) { document.getElementById(id).classList.add("hidden"); }
function populateCatSelect(selectId) {
  const sel = document.getElementById(selectId);
  const v = sel.value;
  sel.innerHTML = `<option value="">None</option>` +
    state.categories.map(c => `<option value="${c.id}">${c.name}</option>`).join("");
  sel.value = v;
}
function openTaskModal() {
  populateCatSelect("t-category");
  document.getElementById("task-modal-title").textContent = "New Task";
  document.getElementById("task-id").value = "";
  document.getElementById("task-form").reset();
  document.getElementById("t-deadline-date").value = "";
  document.getElementById("t-deadline-time").value = "";
  updateDeadlinePreview();
  openSheet("task-modal");
}

/* ── Helpers ───────────────────────────────────────────────────────────── */
function esc(s) {
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}

/* ── Deadline helpers ──────────────────────────────────────────────────── */
// Parse "YYYY-MM-DD HH:mm" or "YYYY-MM-DD" → { dateStr: "dd-mm-yyyy", timeStr: "HH:mm" }
function splitDeadline(dl) {
  if (!dl) return { dateStr: "", timeStr: "" };
  const [datePart, timePart] = dl.split(" ");
  const [y, m, d] = datePart.split("-");
  return {
    dateStr: `${d}-${m}-${y}`,
    timeStr: timePart || "",
  };
}

// Build ISO deadline string from the two inputs → "YYYY-MM-DD HH:mm" or "YYYY-MM-DD"
function buildDeadline() {
  const dateRaw = (document.getElementById("t-deadline-date")?.value || "").trim();
  const timeRaw = (document.getElementById("t-deadline-time")?.value || "").trim();
  if (!dateRaw) return null;
  // Parse dd-mm-yyyy
  const parts = dateRaw.split("-");
  if (parts.length !== 3) return null;
  const [dd, mm, yyyy] = parts;
  if (!dd || !mm || !yyyy || yyyy.length !== 4) return null;
  const isoDate = `${yyyy}-${mm.padStart(2,"0")}-${dd.padStart(2,"0")}`;
  if (timeRaw && /^\d{1,2}:\d{2}$/.test(timeRaw)) {
    const [hh, min] = timeRaw.split(":");
    return `${isoDate} ${String(hh).padStart(2,"0")}:${min}`;
  }
  return isoDate;
}

function updateDeadlinePreview() {
  const el = document.getElementById("deadline-preview");
  if (!el) return;
  const dl = buildDeadline();
  if (!dl) { el.textContent = "Not set"; el.className = "deadline-preview"; return; }
  const [datePart, timePart] = dl.split(" ");
  const [y,m,d] = datePart.split("-");
  const dateObj = new Date(dl.replace(" ", "T") || datePart);
  const now = new Date();
  const diffMs = dateObj - now;
  const diffDays = Math.ceil(diffMs / 86400000);
  let cls = "deadline-preview";
  let label = timePart ? `${d}-${m}-${y} at ${timePart}` : `${d}-${m}-${y}`;
  if (diffDays < 0) { label += " · overdue!"; cls += " overdue"; }
  else if (diffDays === 0) { label += " · today!"; cls += " urgent"; }
  else if (diffDays === 1) { label += " · tomorrow"; cls += " urgent"; }
  else { label += ` · ${diffDays}d left`; }
  el.textContent = label;
  el.className = cls;
}

// Auto-format date input: insert dashes as user types (dd-mm-yyyy)
function autoFormatDate(input) {
  let v = input.value.replace(/\D/g, "");
  if (v.length > 2) v = v.slice(0,2) + "-" + v.slice(2);
  if (v.length > 5) v = v.slice(0,5) + "-" + v.slice(5);
  input.value = v.slice(0, 10);
  updateDeadlinePreview();
}

// Auto-format time input: insert colon as user types (HH:mm)
function autoFormatTime(input) {
  let v = input.value.replace(/\D/g, "");
  if (v.length > 2) v = v.slice(0,2) + ":" + v.slice(2);
  input.value = v.slice(0, 5);
  updateDeadlinePreview();
}

/* ══════════════════════════════════════════════════════════════════════════
   EVENT WIRING
   ══════════════════════════════════════════════════════════════════════════ */
document.addEventListener("DOMContentLoaded", () => {

  /* Auth tabs */
  document.querySelectorAll(".tab-btn").forEach(btn => btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".auth-form").forEach(f => f.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(`${btn.dataset.tab}-form`).classList.add("active");
  }));

  document.getElementById("login-form").addEventListener("submit", async e => {
    e.preventDefault();
    const { ok, data } = await api("POST", "/api/auth/login", {
      email: document.getElementById("login-email").value,
      password: document.getElementById("login-password").value,
    });
    if (ok) { state.user = data; showApp(); }
    else document.getElementById("login-error").textContent = data.error || "Login failed";
  });

  document.getElementById("register-form").addEventListener("submit", async e => {
    e.preventDefault();
    const { ok, data } = await api("POST", "/api/auth/register", {
      name: document.getElementById("reg-name").value,
      email: document.getElementById("reg-email").value,
      password: document.getElementById("reg-password").value,
    });
    if (ok) { state.user = data; showApp(); }
    else document.getElementById("register-error").textContent = data.error || "Registration failed";
  });

  /* Logout */
  document.getElementById("logout-btn").addEventListener("click", async () => {
    await api("POST", "/api/auth/logout");
    state.user = null; showAuth();
  });

  /* Bottom nav */
  document.querySelectorAll(".bn-item").forEach(item => {
    item.addEventListener("click", e => { e.preventDefault(); navigateTo(item.dataset.page); });
  });

  /* Dashboard buttons */
  document.getElementById("recalculate-btn").addEventListener("click", async () => {
    const today = new Date().toISOString().split("T")[0];
    const { ok, data } = await api("POST", "/api/schedule/recalculate", { date: today });
    if (ok) {
      state.schedule = data;
      renderTimeline(data);
      renderUpNext(data);
      showToast("Schedule updated ✓", "success");
      if (Notification.permission === "granted") scheduleNotifications();
    }
  });
  document.getElementById("add-task-btn-dash").addEventListener("click", openTaskModal);

  /* Notification bell + button */
  document.getElementById("notif-bell").addEventListener("click", requestNotifPermission);
  document.getElementById("notif-enable-btn").addEventListener("click", requestNotifPermission);
  document.getElementById("notif-toggle-btn")?.addEventListener("click", requestNotifPermission);

  /* Lead time change */
  document.getElementById("notif-lead-time")?.addEventListener("change", () => {
    if (Notification.permission === "granted" && state.schedule.length) {
      scheduleNotifications();
    }
  });

  /* Task filters */
  document.querySelectorAll("[data-filter]").forEach(btn => btn.addEventListener("click", () => {
    document.querySelectorAll("[data-filter]").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    state.activeFilter = btn.dataset.filter;
    renderTasks();
  }));

  /* Add / save task */
  document.getElementById("add-task-btn").addEventListener("click", openTaskModal);

  document.getElementById("task-form").addEventListener("submit", async e => {
    e.preventDefault();
    const id = document.getElementById("task-id").value;
    const dur = parseFloat(document.getElementById("t-duration").value);
    const payload = {
      title: document.getElementById("t-title").value,
      duration: dur,
      remaining_duration: id ? undefined : dur,
      deadline: buildDeadline() || null,
      preferred_time: document.getElementById("t-preferred").value,
      category_id: document.getElementById("t-category").value || null,
      notes: document.getElementById("t-notes").value,
    };
    if (!id) payload.remaining_duration = dur;
    const { ok } = id
      ? await api("PUT", `/api/tasks/${id}`, payload)
      : await api("POST", "/api/tasks", payload);
    if (ok) {
      closeSheet("task-modal");
      showToast(id ? "Task updated ✓" : "Task created ✓", "success");
      await loadTasks();
    }
  });

  /* Routines */
  document.getElementById("add-routine-btn").addEventListener("click", () => {
    document.getElementById("routine-modal-title").textContent = "New Routine";
    document.getElementById("routine-id").value = "";
    document.getElementById("routine-form").reset();
    openSheet("routine-modal");
  });
  document.getElementById("routine-form").addEventListener("submit", async e => {
    e.preventDefault();
    const id = document.getElementById("routine-id").value;
    const payload = {
      title: document.getElementById("r-title").value,
      duration: parseFloat(document.getElementById("r-duration").value),
      preferred_time: document.getElementById("r-preferred").value,
    };
    const { ok } = id
      ? await api("PUT", `/api/routines/${id}`, payload)
      : await api("POST", "/api/routines", payload);
    if (ok) { closeSheet("routine-modal"); showToast("Routine saved ✓", "success"); await loadRoutines(); }
  });

  /* Reports */
  document.querySelectorAll("[data-report]").forEach(btn =>
    btn.addEventListener("click", () => loadReport(btn.dataset.report))
  );

  /* Settings */
  document.getElementById("profile-form").addEventListener("submit", async e => {
    e.preventDefault();
    const { ok } = await api("PUT", "/api/settings", {
      name: document.getElementById("s-name").value,
      wake_time: document.getElementById("s-wake").value,
      sleep_time: document.getElementById("s-sleep").value,
    });
    if (ok) {
      const msg = document.getElementById("settings-msg");
      msg.classList.remove("hidden");
      setTimeout(() => msg.classList.add("hidden"), 2500);
    }
  });
  document.getElementById("add-cat-btn").addEventListener("click", async () => {
    const name = document.getElementById("new-cat-name").value.trim();
    const color = document.getElementById("new-cat-color").value;
    if (!name) return;
    await api("POST", "/api/categories", { name, color });
    document.getElementById("new-cat-name").value = "";
    await loadCats();
  });

  /* Close sheets */
  document.querySelectorAll("[data-close]").forEach(btn =>
    btn.addEventListener("click", () => closeSheet(btn.dataset.close))
  );
  document.querySelectorAll(".sheet-overlay").forEach(overlay =>
    overlay.addEventListener("click", e => { if (e.target === overlay) closeSheet(overlay.id); })
  );

  /* Deadline live formatting */
  document.addEventListener("input", e => {
    if (e.target.id === "t-deadline-date") autoFormatDate(e.target);
    if (e.target.id === "t-deadline-time") autoFormatTime(e.target);
  });

  checkAuth();
});
