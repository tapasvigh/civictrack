const welcome = document.querySelector("#welcome");
const authScreen = document.querySelector("#auth-screen");
const appShell = document.querySelector("#app");
const notice = document.querySelector("#notice");
const authNotice = document.querySelector("#auth-notice");
let noticeTimer;
let calendarDate = new Date();
let previousBadgeIds = null;
let reminderTimer;
let dailyTimer;

function showNotice(message, isError = false, target = notice) {
  target.textContent = message;
  target.classList.toggle("error", isError);
  target.hidden = false;
  window.clearTimeout(noticeTimer);
  noticeTimer = window.setTimeout(() => { target.hidden = true; }, 5500);
}

async function api(path, options = {}) {
  let response;
  try {
    response = await fetch(path, {
      ...options,
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    });
  } catch {
    throw new Error("Can't reach Civic Track. Check your connection or make sure the app server is running, then try again.");
  }
  const result = response.status === 204 ? {} : await response.json();
  if (!response.ok) throw new Error(result.error || "Something went wrong.");
  return result;
}

function formatDate(value, options = { month: "short", day: "numeric", year: "numeric" }) {
  return new Date(`${value}T12:00:00`).toLocaleDateString(undefined, options);
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]);
}

async function fileData(file, maxBytes = 1100000) {
  if (!file) return "";
  if (!["image/png", "image/jpeg", "image/webp"].includes(file.type)) {
    throw new Error("Choose a PNG, JPEG, or WebP image.");
  }
  if (file.size > maxBytes) throw new Error("Choose an image smaller than 1 MB.");
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error("The image could not be read."));
    reader.readAsDataURL(file);
  });
}

function badgeMarkup(badge, canPin = false) {
  const name = typeof badge === "string" ? badge : badge.name;
  const pin = canPin
    ? `<button class="badge-pin ${badge.pinned ? "pinned" : ""}" data-pin="${badge.id}" data-pinned="${badge.pinned ? "true" : "false"}" aria-label="${badge.pinned ? "Unpin" : "Pin"} ${escapeHtml(name)}">${badge.pinned ? "★" : "☆"}</button>`
    : "";
  return `<span class="badge"><span class="badge-symbol" aria-hidden="true">✦</span>${escapeHtml(name)}${pin}</span>`;
}

function assignmentWhen(dueDate) {
  const due = new Date(`${dueDate}T00:00:00`);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const remaining = Math.round((due - today) / 86400000);
  if (remaining < 0) return { text: `Overdue · ${formatDate(dueDate)}`, urgent: true };
  if (remaining <= 3) return { text: `Due date · ${formatDate(dueDate)}`, urgent: true };
  return { text: `Due ${formatDate(dueDate)}`, urgent: false };
}

function notify(title, body) {
  if (Notification.permission === "granted") new Notification(title, { body, icon: "/static/icons/civic-track-192.png" });
}

async function loadDashboard() {
  const period = document.querySelector("#period-select").value;
  const data = await api(`/api/dashboard?period=${encodeURIComponent(period)}`);
  document.querySelector("#hours-value").textContent = data.hours.toLocaleString();
  document.querySelector("#assignments-value").innerHTML =
    `${data.on_time_assignments}<span class="stat-total"> / ${data.assignment_count}</span>`;
  document.querySelector("#badges-value").textContent = data.badge_count.toLocaleString();
  document.querySelector("#impact-value").textContent = `$${data.impact_value.toLocaleString()}`;
  document.querySelector("#impact-caption").textContent =
    `${data.overall_hours} hours × $${Number(data.impact_rate).toFixed(2)} illustrative rate per hour. Change the example rate in Settings.`;
  document.querySelector("#milestone-bar").style.width = `${data.milestone_progress}%`;
  document.querySelector("#milestone-label").textContent =
    `${data.hours_to_milestone} hours until your ${data.next_milestone}-hour badge.`;

  const goalContent = document.querySelector("#goal-content");
  if (data.goal) {
    const remaining = Math.max(0, data.goal.target - data.goal.progress);
    goalContent.innerHTML = `<div class="goal-summary">
      <div class="progress-ring" style="--progress:${data.goal.percent}%"><strong>${data.goal.percent}%</strong></div>
      <div class="goal-copy"><strong>${data.goal.progress} of ${data.goal.target} hours</strong>
      <p>${remaining === 0 ? "You met your goal. Amazing work!" : `${remaining.toFixed(2).replace(/\.00$/, "")} hours to go`} · ${formatDate(data.goal.ends_on, { month: "short", day: "numeric" })} deadline</p></div></div>`;
  } else {
    goalContent.innerHTML = '<p class="goal-empty">No active goal yet. Pick a target and give yourself something to work toward.</p>';
  }

  const upcomingList = document.querySelector("#upcoming-list");
  upcomingList.innerHTML = data.upcoming.length ? data.upcoming.map((item) => {
    const due = assignmentWhen(item.due_date);
    return `<div class="upcoming-item"><div class="date-chip"><strong>${formatDate(item.due_date, { day: "numeric" })}</strong><span>${formatDate(item.due_date, { month: "short" })}</span></div>
      <div class="assignment-info"><strong>${escapeHtml(item.title)}</strong><span class="${due.urgent ? "due-soon" : ""}">${escapeHtml(item.subject)} · ${escapeHtml(due.text)}</span></div></div>`;
  }).join("") : '<p class="empty-message">Nothing on your list yet. Enjoy the breathing room!</p>';
  document.querySelector("#badge-preview").innerHTML = data.badges.length
    ? data.badges.slice(0, 4).map((badge) => badgeMarkup(badge)).join("")
    : '<p class="empty-message">Your first badge is waiting for you. Log some hours to get started!</p>';
}

async function loadVolunteer() {
  const [{ entries }, { organizations }] = await Promise.all([
    api("/api/volunteer"), api("/api/organizations"),
  ]);
  updateAffiliationSelect(organizations);
  document.querySelector("#volunteer-rows").innerHTML = entries.length ? entries.map((entry) => `
    <tr><td>${formatDate(entry.date)}</td><td>${escapeHtml(entry.activity)}</td><td>${escapeHtml(entry.location)}</td><td>${escapeHtml(entry.organization || "—")}</td>
    <td>${Number(entry.hours).toLocaleString()}</td><td>${escapeHtml(entry.advisor || "—")}</td>
    <td>${entry.proof_photo ? `<a href="${entry.proof_photo}" target="_blank" rel="noopener">View photo</a>` : "—"}</td></tr>`).join("")
    : '<tr><td class="table-empty" colspan="7">No hours logged yet. Your first entry starts your story.</td></tr>';
}

function updateAffiliationSelect(organizations) {
  const organizationSelect = document.querySelector("#volunteer-form [name=organization]");
  const selectedOrganization = organizationSelect.value;
  const placeholder = organizations.length
    ? "Choose an affiliation"
    : "No affiliations yet — add one in Profile";
  organizationSelect.innerHTML = `<option value="">${placeholder}</option>` +
    organizations.map((organization) => `<option value="${escapeHtml(organization.name)}">${escapeHtml(organization.name)} · ${escapeHtml(organization.kind)}</option>`).join("");
  organizationSelect.value = organizations.some((organization) => organization.name === selectedOrganization)
    ? selectedOrganization : "";
  document.querySelector("#manage-affiliations").textContent = organizations.length
    ? "Manage affiliations" : "Add an affiliation";
}

async function loadAssignments() {
  const { assignments } = await api("/api/assignments");
  const list = document.querySelector("#assignment-list");
  list.innerHTML = assignments.length ? assignments.map((item) => {
    const due = assignmentWhen(item.due_date);
    return `<article class="assignment-card ${item.completed_at ? "completed" : ""}">
      <div class="assignment-info"><strong>${escapeHtml(item.title)}</strong>
        <span class="assignment-details">${escapeHtml(item.subject)} · <span class="${due.urgent && !item.completed_at ? "due-soon" : ""}">${item.completed_at ? `Completed ${formatDate(item.completed_at.slice(0, 10))}` : escapeHtml(due.text)}</span></span>
        ${item.description ? `<p class="assignment-description">${escapeHtml(item.description)}</p>` : ""}
        ${item.reminder_at && !item.completed_at ? `<span class="assignment-reminder">Study reminder · ${escapeHtml(new Date(item.reminder_at).toLocaleString())}</span>` : ""}
      </div>${item.completed_at ? '<span class="complete-label">✓ Done</span>' : `<button class="button complete-button" data-complete="${item.id}">Mark done</button>`}</article>`;
  }).join("") : '<p class="empty-message">No assignments yet. Add one above to get organized.</p>';
  scheduleStudyReminders(assignments);
}

async function loadBadges() {
  const { badges } = await api("/api/badges");
  document.querySelector("#all-badges").innerHTML = badges.length
    ? badges.map((badge) => badgeMarkup(badge, true)).join("")
    : '<p class="empty-message">Badges you earn will show up here. Keep going!</p>';
  const pinned = badges.filter((badge) => badge.pinned);
  document.querySelector("#profile-pinned-badges").innerHTML = pinned.length
    ? pinned.map((badge) => badgeMarkup(badge)).join("")
    : '<p class="empty-message">Pin up to three favorite badges from Achievements.</p>';
  if (previousBadgeIds !== null && "Notification" in window
      && Notification.permission === "granted" && localStorage.getItem("civicNotifications") === "true") {
    const newBadges = badges.filter((badge) => !previousBadgeIds.includes(badge.id));
    newBadges.forEach((badge) => notify("New Civic Track badge!", `You earned ${badge.name}. Nice work!`));
  }
  previousBadgeIds = badges.map((badge) => badge.id);
}

async function loadProfile() {
  const data = await api("/api/profile");
  const form = document.querySelector("#profile-form");
  for (const key of ["full_name", "birthdate", "email", "phone", "username"]) form.elements[key].value = data.profile[key] || "";
  document.querySelector("#hello-name").textContent = data.profile.username || data.profile.full_name || "volunteer";
  const avatar = document.querySelector("#profile-avatar");
  avatar.textContent = "";
  avatar.style.backgroundImage = `url("${data.profile.photo || "/static/icons/civic-track-192.png"}")`;
  document.querySelector("#organization-list").innerHTML = data.organizations.length
    ? data.organizations.map((item) => `<div class="simple-list-item"><span><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.kind)}</small></span><button class="text-button" data-remove-organization="${item.id}">Remove</button></div>`).join("")
    : '<p class="empty-message">Add a school, club, or organization to group your service.</p>';
  updateAffiliationSelect(data.organizations);
  document.querySelector("#signature-list").innerHTML = data.signatures.length
    ? data.signatures.map((item) => `<div class="simple-list-item"><span class="signature-preview"><img src="${item.image}" alt=""><span><strong>${escapeHtml(item.name)}</strong><small>Private local reference</small></span></span><button class="text-button" data-remove-signature="${item.id}">Remove</button></div>`).join("")
    : '<p class="empty-message">No optional signatures saved.</p>';
}

async function loadSettings() {
  const settings = await api("/api/settings");
  const form = document.querySelector("#settings-form");
  form.elements.theme.value = settings.theme;
  form.elements.font_scale.value = String(settings.font_scale);
  form.elements.period.value = settings.period;
  form.elements.impact_rate.value = settings.impact_rate;
  document.querySelector("#period-select").value = settings.period;
  const notificationForm = document.querySelector("#notification-form");
  notificationForm.elements.reminder_time.value = settings.reminder_time;
  notificationForm.elements.notifications.checked = Boolean(settings.notifications);
  localStorage.setItem("civicNotifications", String(Boolean(settings.notifications)));
  applySettings(settings);
  scheduleDailyReminder(settings);
}

function applySettings(settings) {
  document.documentElement.style.setProperty("--teal", settings.theme);
  document.documentElement.style.setProperty("--deep-teal", settings.theme);
  document.documentElement.style.setProperty("--font-scale", settings.font_scale);
}

async function loadReports() {
  const [reports, dashboard] = await Promise.all([
    api(`/api/reports?period=${encodeURIComponent(document.querySelector("#period-select").value)}`),
    api(`/api/dashboard?period=${encodeURIComponent(document.querySelector("#period-select").value)}`),
  ]);
  const volunteerPercent = reports.hours
    ? (dashboard.goal ? dashboard.goal.percent : dashboard.milestone_progress)
    : 0;
  document.querySelector("#report-volunteer-ring").style.setProperty("--progress", `${volunteerPercent}%`);
  document.querySelector("#report-volunteer-percent").textContent = `${volunteerPercent}%`;
  document.querySelector("#report-volunteer-label").textContent =
    `${reports.hours} hours · ${dashboard.goal ? `${dashboard.goal.progress} of ${dashboard.goal.target} goal hours` : `${dashboard.hours_to_milestone} until next badge`}`;
  document.querySelector("#report-assignment-ring").style.setProperty("--progress", `${reports.assignments_total ? Math.round(reports.assignments_completed / reports.assignments_total * 100) : 0}%`);
  document.querySelector("#report-assignment-percent").textContent =
    `${reports.assignments_total ? Math.round(reports.assignments_completed / reports.assignments_total * 100) : 0}%`;
  document.querySelector("#report-assignment-label").textContent =
    `${reports.assignments_completed} of ${reports.assignments_total} assignments completed`;
  renderReport(reports);
}

let reportData;
function renderReport(data) {
  reportData = data;
  const type = document.querySelector("#report-type").value;
  const volunteer = type === "volunteer";
  document.querySelector("#report-title").textContent = volunteer ? "Volunteer hours report" : "Assignments report";
  const details = volunteer
    ? `<p><strong>Total volunteer hours:</strong> ${data.hours}</p><h3>Volunteer activity</h3><ul>${data.entries.map((entry) => `<li>${formatDate(entry.date)} — ${escapeHtml(entry.activity)} at ${escapeHtml(entry.location)}${entry.organization ? ` · ${escapeHtml(entry.organization)}` : ""} (${entry.hours} hours)${entry.advisor ? ` · Advisor: ${escapeHtml(entry.advisor)}` : ""}</li>`).join("") || "<li>No service entries recorded.</li>"}</ul>`
    : `<p><strong>Assignments completed on time:</strong> ${data.assignments_on_time}</p><p><strong>All completed:</strong> ${data.assignments_completed} of ${data.assignments_total}</p><h3>Assignment record</h3><ul>${data.assignments.filter((item) => item.completed_at).map((item) => `<li>${escapeHtml(item.title)} (${escapeHtml(item.subject)}) — due ${formatDate(item.due_date)} · ${item.on_time ? "Completed on time" : "Completed late"}</li>`).join("") || "<li>No completed assignments recorded.</li>"}</ul>`;
  document.querySelector("#report-preview").innerHTML = `<div class="report-paper"><p class="eyebrow">CIVIC TRACK · PROGRESS REPORT</p><h2>${escapeHtml(data.name || "Volunteer")}</h2><p>Prepared ${formatDate(new Date().toISOString().slice(0, 10))}</p><hr>${details}<p class="report-footnote">A personal progress summary; entries are not independently verified.</p></div>`;
}

async function loadCalendar() {
  const [assignments, volunteer] = await Promise.all([api("/api/assignments"), api("/api/volunteer")]);
  const month = calendarDate.getMonth();
  const year = calendarDate.getFullYear();
  const firstWeekday = new Date(year, month, 1).getDay();
  const days = new Date(year, month + 1, 0).getDate();
  const offsets = firstWeekday;
  document.querySelector("#calendar-month").textContent = calendarDate.toLocaleDateString(undefined, { month: "long", year: "numeric" });
  const assignmentsByDate = new Map();
  assignments.assignments.forEach((item) => {
    assignmentsByDate.set(item.due_date, [...(assignmentsByDate.get(item.due_date) || []), item]);
  });
  const volunteersByDate = new Map();
  volunteer.entries.forEach((item) => {
    volunteersByDate.set(item.date, [...(volunteersByDate.get(item.date) || []), item]);
  });
  const headers = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((day) => `<div class="calendar-weekday">${day}</div>`).join("");
  const cells = Array.from({ length: offsets }, () => '<div class="calendar-day outside"></div>');
  for (let day = 1; day <= days; day += 1) {
    const key = `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    const due = assignmentsByDate.get(key) || [];
    const logged = volunteersByDate.get(key) || [];
    const isToday = key === new Date().toISOString().slice(0, 10);
    const events = [
      ...due.map((item) => `<span class="calendar-event due-event" title="${escapeHtml(item.title)}">${escapeHtml(item.title)}</span>`),
      ...logged.map((item) => `<span class="calendar-event volunteer-event" title="${escapeHtml(item.activity)}${item.organization ? ` · ${escapeHtml(item.organization)}` : ""}">${Number(item.hours)}h · ${escapeHtml(item.activity)}</span>`),
    ].join("");
    cells.push(`<div class="calendar-day ${isToday ? "today" : ""}"><strong>${day}</strong>${events}</div>`);
  }
  document.querySelector("#calendar-grid").innerHTML = headers + cells.join("");
}

function printPage(title, content) {
  const frame = document.createElement("iframe");
  frame.className = "print-frame";
  frame.title = title;
  frame.setAttribute("aria-hidden", "true");
  frame.style.cssText = "position:fixed;right:0;bottom:0;width:0;height:0;border:0;opacity:0";
  frame.onload = () => {
    try {
      frame.contentWindow.focus();
      frame.contentWindow.print();
      frame.contentWindow.addEventListener("afterprint", () => frame.remove(), { once: true });
      window.setTimeout(() => frame.remove(), 60000);
    } catch (error) {
      frame.remove();
      showNotice(`Could not open print preview: ${error.message}`, true);
    }
  };
  frame.srcdoc = `<!doctype html><html><head><title>${escapeHtml(title)}</title><meta charset="utf-8"><style>
    body{font:15px Arial,sans-serif;color:#182b35;max-width:760px;margin:40px auto;padding:20px}
    h1,h2{color:#148e94}li{margin:8px 0}.eyebrow{font-size:11px;letter-spacing:2px;color:#148e94}
    .badge{display:inline-flex;align-items:center;margin:8px;padding:10px;border:1px solid #e8d59c;border-radius:20px;background:#fffaf0}
    .badge-pin{display:none}
    .report-footnote{margin-top:35px;color:#68787c;font-size:12px;border-top:1px solid #ddd;padding-top:12px}
    @media print{body{margin:0 auto}.no-print{display:none}}
    </style></head><body><h1>${escapeHtml(title)}</h1>${content}</body></html>`;
  document.body.append(frame);
}

function reminderEnabled() {
  return localStorage.getItem("civicNotifications") === "true" && Notification.permission === "granted";
}

async function scheduleStudyReminders(assignments) {
  window.clearInterval(reminderTimer);
  if (!("Notification" in window) || !reminderEnabled()) return;
  const sent = JSON.parse(localStorage.getItem("civicSentReminders") || "[]");
  const now = Date.now();
  assignments.filter((item) => !item.completed_at && item.reminder_at).forEach((item) => {
    const dueAt = new Date(item.reminder_at).getTime();
    const key = `${item.id}:${item.reminder_at}`;
    if (dueAt <= now && !sent.includes(key)) {
      notify("Civic Track study reminder", `Remember to work on: ${item.title}`);
      sent.push(key);
    }
  });
  localStorage.setItem("civicSentReminders", JSON.stringify(sent));
  reminderTimer = window.setInterval(() => loadAssignments().catch(() => {}), 60000);
}

function scheduleDailyReminder(settings) {
  window.clearInterval(dailyTimer);
  if (!("Notification" in window) || !reminderEnabled()) return;
  const [hour, minute] = settings.reminder_time.split(":").map(Number);
  const check = () => {
    const now = new Date();
    const today = now.toISOString().slice(0, 10);
    const sentKey = localStorage.getItem("civicDailyReminder");
    if (now.getHours() === hour && now.getMinutes() === minute && sentKey !== today) {
      notify("A little Civic Track nudge", "Take a moment to study or log your volunteer hours.");
      localStorage.setItem("civicDailyReminder", today);
    }
  };
  check();
  dailyTimer = window.setInterval(check, 30000);
}

async function startApp(profile) {
  welcome.hidden = true;
  authScreen.hidden = true;
  appShell.hidden = false;
  if (profile) {
    document.querySelector("#hello-name").textContent = profile.username || profile.full_name || "volunteer";
    const avatar = document.querySelector("#profile-avatar");
    avatar.textContent = "";
    avatar.style.backgroundImage = `url("${profile.photo || "/static/icons/civic-track-192.png"}")`;
  }
  try {
    await loadSettings();
    await refreshAll();
    await loadProfile();
  } catch (error) {
    showNotice(error.message, true);
  }
}

async function refreshAll() {
  await Promise.all([loadDashboard(), loadVolunteer(), loadAssignments(), loadBadges()]);
}

function showAuth(tab = "signup") {
  welcome.hidden = true;
  appShell.hidden = true;
  authScreen.hidden = false;
  document.querySelectorAll(".auth-tab").forEach((button) => button.classList.toggle("active", button.dataset.authTab === tab));
  document.querySelector("#signup-pane").hidden = tab !== "signup";
  document.querySelector("#login-pane").hidden = tab !== "login";
  document.querySelector("#forgot-pane").hidden = true;
  authNotice.hidden = true;
}

function openPage(page) {
  document.querySelectorAll(".page").forEach((section) => section.classList.toggle("active", section.id === `page-${page}`));
  document.querySelectorAll(".nav-link").forEach((link) => link.classList.toggle("active", link.dataset.page === page));
  document.querySelector("#sidebar").classList.remove("open");
  document.querySelector("#menu-button").setAttribute("aria-expanded", "false");
  const loaders = {
    dashboard: loadDashboard, volunteer: loadVolunteer, assignments: loadAssignments,
    calendar: loadCalendar, progress: loadReports, achievements: loadBadges,
    profile: loadProfile, settings: loadSettings,
  };
  if (loaders[page]) loaders[page]().catch((error) => showNotice(error.message, true));
}

async function requestVerificationCode(purpose) {
  const result = await api("/api/auth/code", { method: "POST", body: JSON.stringify({ purpose }) });
  const form = purpose === "reset" ? document.querySelector("#reset-form") : document.querySelector("#change-password-form");
  const message = purpose === "reset" ? document.querySelector("#reset-code-message") : document.querySelector("#change-code-message");
  message.textContent = `${result.message} ${result.demo_code} · expires in 2 minutes`;
  form.hidden = false;
  showNotice("The verification code is shown in the form. It was not sent to your contact.", false, purpose === "reset" ? authNotice : notice);
}

async function loadAppFromSession() {
  try {
    const status = await api("/api/auth/status");
    if (status.signed_in) {
      await startApp(status.profile);
    } else if (status.has_account) {
      welcome.querySelector("#start-button").hidden = true;
      document.querySelector("#welcome-login").hidden = false;
    }
  } catch (error) {
    showNotice(error.message, true, authNotice);
  }
}

document.querySelector("#start-button").addEventListener("click", () => showAuth("signup"));
document.querySelector("#welcome-login").addEventListener("click", () => showAuth("login"));
document.querySelector("#back-welcome").addEventListener("click", () => {
  authScreen.hidden = true;
  welcome.hidden = false;
});
document.querySelectorAll(".auth-tab").forEach((button) => button.addEventListener("click", () => showAuth(button.dataset.authTab)));
document.querySelector("#forgot-link").addEventListener("click", () => {
  document.querySelector("#signup-pane").hidden = true;
  document.querySelector("#login-pane").hidden = true;
  document.querySelector("#forgot-pane").hidden = false;
});

document.querySelector("#signup-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const values = Object.fromEntries(new FormData(form));
  try {
    values.photo = await fileData(form.elements.photo.files[0]);
    const result = await api("/api/auth/signup", { method: "POST", body: JSON.stringify(values) });
    form.reset();
    showNotice(result.message, false, authNotice);
    await startApp({ full_name: values.full_name, username: values.username, photo: values.photo });
  } catch (error) {
    showNotice(error.message, true, authNotice);
  }
});

document.querySelector("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const values = Object.fromEntries(new FormData(event.currentTarget));
  try {
    await api("/api/auth/login", { method: "POST", body: JSON.stringify(values) });
    const status = await api("/api/auth/status");
    await startApp(status.profile);
  } catch (error) {
    showNotice(error.message, true, authNotice);
  }
});

document.querySelector("#request-reset-code").addEventListener("click", () => requestVerificationCode("reset").catch((error) => showNotice(error.message, true, authNotice)));
document.querySelector("#resend-reset-code").addEventListener("click", () => requestVerificationCode("reset").catch((error) => showNotice(error.message, true, authNotice)));
document.querySelector("#reset-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const values = Object.fromEntries(new FormData(event.currentTarget));
  try {
    await api("/api/auth/reset", { method: "POST", body: JSON.stringify(values) });
    const status = await api("/api/auth/status");
    await startApp(status.profile);
  } catch (error) {
    showNotice(error.message, true, authNotice);
  }
});

document.querySelectorAll("[data-page]").forEach((button) => button.addEventListener("click", (event) => {
  event.preventDefault();
  openPage(button.dataset.page);
}));
document.querySelector("#profile-avatar").addEventListener("click", () => openPage("profile"));
document.querySelector("#profile-link").addEventListener("click", () => openPage("profile"));
document.querySelector("#menu-button").addEventListener("click", (event) => {
  const sidebar = document.querySelector("#sidebar");
  const isOpen = sidebar.classList.toggle("open");
  event.currentTarget.setAttribute("aria-expanded", String(isOpen));
});
document.querySelector("#period-select").addEventListener("change", () => {
  Promise.all([loadDashboard(), loadReports()]).catch((error) => showNotice(error.message, true));
});

let installPrompt;
const installButton = document.querySelector("#install-app");
const welcomeInstallButton = document.querySelector("#welcome-install-app");
const installHelp = document.querySelector("#install-help");
const isStandalone = window.matchMedia("(display-mode: standalone)").matches
  || window.navigator.standalone === true;

if (isStandalone) {
  installButton.hidden = true;
  welcomeInstallButton.hidden = true;
} else {
  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    installPrompt = event;
    installButton.textContent = "Install app";
    installButton.hidden = false;
    welcomeInstallButton.textContent = "Install app";
    welcomeInstallButton.hidden = false;
  });
  window.addEventListener("appinstalled", () => {
    installPrompt = null;
    installButton.hidden = true;
    welcomeInstallButton.hidden = true;
    showNotice("Civic Track was added to your device.");
  });
}

async function promptInstall() {
  if (installPrompt) {
    installPrompt.prompt();
    const choice = await installPrompt.userChoice;
    if (choice.outcome === "accepted") {
      installButton.hidden = true;
      welcomeInstallButton.hidden = true;
    }
    installPrompt = null;
    return;
  }
  const instruction = document.querySelector("#install-instructions");
  const isIos = /iphone|ipad|ipod/i.test(navigator.userAgent);
  const isSafari = isIos && /safari/i.test(navigator.userAgent) && !/crios|fxios|edgios/i.test(navigator.userAgent);
  instruction.textContent = isSafari
    ? "In Safari, tap Share, then Add to Home Screen. Open Civic Track from the new icon."
    : "Use your browser menu and choose Install app or Add to Home Screen. If that option is unavailable, open Civic Track in a supported browser over HTTPS.";
  installHelp.showModal();
}

installButton.addEventListener("click", promptInstall);
welcomeInstallButton.addEventListener("click", promptInstall);

document.querySelector("#close-install-help").addEventListener("click", () => installHelp.close());

if ("serviceWorker" in navigator && window.isSecureContext) {
  window.addEventListener("load", () => {
    const legacyScope = new URL("/static/", window.location.href).href;
    navigator.serviceWorker.getRegistrations()
      .then((registrations) => Promise.all(
        registrations
          .filter((registration) => registration.scope === legacyScope)
          .map((registration) => registration.unregister()),
      ))
      .catch((error) => {
        console.error("Civic Track could not clean up the old offline shell.", error);
      })
      .finally(() => {
        navigator.serviceWorker.register("/sw.js", { updateViaCache: "none" }).catch((error) => {
          console.error("Civic Track offline shell registration failed.", error);
        });
      });
  });
}

const networkStatus = document.querySelector("#network-status");
window.addEventListener("offline", () => {
  networkStatus.textContent = "You're offline. The app shell may open, but account and data actions need a connection.";
  networkStatus.hidden = false;
});
window.addEventListener("online", () => {
  networkStatus.textContent = "You're back online.";
  networkStatus.hidden = false;
  window.setTimeout(() => { networkStatus.hidden = true; }, 3500);
});

document.querySelector("#volunteer-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const values = Object.fromEntries(new FormData(form));
  try {
    values.proof_photo = await fileData(form.elements.proof_photo.files[0]);
    await api("/api/volunteer", { method: "POST", body: JSON.stringify(values) });
    form.reset();
    form.elements.date.value = new Date().toISOString().slice(0, 10);
    await refreshAll();
    showNotice("Volunteer hours saved. Thanks for making a difference!");
  } catch (error) {
    showNotice(error.message, true);
  }
});

document.querySelector("#goal-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  try {
    await api("/api/goals", { method: "POST", body: JSON.stringify(Object.fromEntries(new FormData(form))) });
    form.reset();
    const today = new Date();
    form.elements.starts_on.value = today.toISOString().slice(0, 10);
    form.elements.ends_on.value = new Date(today.getTime() + 7 * 86400000).toISOString().slice(0, 10);
    await refreshAll();
    showNotice("Your volunteer goal is set. You can do this!");
  } catch (error) {
    showNotice(error.message, true);
  }
});

document.querySelector("#assignment-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const values = Object.fromEntries(new FormData(form));
  if (values.reminder_at) values.reminder_at = new Date(values.reminder_at).toISOString();
  try {
    await api("/api/assignments", { method: "POST", body: JSON.stringify(values) });
    form.reset();
    await refreshAll();
    showNotice("Assignment added to your list.");
  } catch (error) {
    showNotice(error.message, true);
  }
});

document.querySelector("#assignment-list").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-complete]");
  if (!button) return;
  try {
    await api(`/api/assignments/${button.dataset.complete}`, { method: "PATCH", body: JSON.stringify({ completed: true }) });
    await refreshAll();
    showNotice("Assignment complete. Nice work!");
  } catch (error) {
    showNotice(error.message, true);
  }
});

document.querySelector("#all-badges").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-pin]");
  if (!button) return;
  try {
    await api(`/api/badges/${button.dataset.pin}`, {
      method: "PATCH", body: JSON.stringify({ pinned: button.dataset.pinned !== "true" }),
    });
    await Promise.all([loadBadges(), loadProfile()]);
    showNotice("Badge showcase updated.");
  } catch (error) {
    showNotice(error.message, true);
  }
});

document.querySelector("#profile-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const values = Object.fromEntries(new FormData(form));
  try {
    values.photo = await fileData(form.elements.photo.files[0]);
    await api("/api/profile", { method: "PUT", body: JSON.stringify(values) });
    await loadProfile();
    showNotice("Profile saved.");
  } catch (error) {
    showNotice(error.message, true);
  }
});

document.querySelector("#remove-profile-photo").addEventListener("click", async () => {
  const form = document.querySelector("#profile-form");
  const values = Object.fromEntries(new FormData(form));
  values.photo = "";
  values.remove_photo = true;
  try {
    await api("/api/profile", { method: "PUT", body: JSON.stringify(values) });
    form.elements.photo.value = "";
    await loadProfile();
    showNotice("The Civic Track profile logo is restored.");
  } catch (error) {
    showNotice(error.message, true);
  }
});

document.querySelector("#organization-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  try {
    await api("/api/organizations", { method: "POST", body: JSON.stringify(Object.fromEntries(new FormData(form))) });
    form.reset();
    await loadProfile();
    showNotice("Affiliation added.");
  } catch (error) {
    showNotice(error.message, true);
  }
});

document.querySelector("#organization-list").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-remove-organization]");
  if (!button) return;
  try {
    await api("/api/organizations", { method: "DELETE", body: JSON.stringify({ id: button.dataset.removeOrganization }) });
    await loadProfile();
  } catch (error) {
    showNotice(error.message, true);
  }
});

document.querySelector("#signature-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const values = { name: form.elements.name.value, image: "" };
  try {
    values.image = await fileData(form.elements.image.files[0]);
    await api("/api/signatures", { method: "POST", body: JSON.stringify(values) });
    form.reset();
    await loadProfile();
    showNotice("Signature saved in the local signature vault.");
  } catch (error) {
    showNotice(error.message, true);
  }
});

document.querySelector("#signature-list").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-remove-signature]");
  if (!button) return;
  try {
    await api("/api/signatures", { method: "DELETE", body: JSON.stringify({ id: button.dataset.removeSignature }) });
    await loadProfile();
  } catch (error) {
    showNotice(error.message, true);
  }
});

document.querySelector("#settings-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const values = Object.fromEntries(new FormData(event.currentTarget));
  try {
    const settings = await api("/api/settings", { method: "PUT", body: JSON.stringify(values) });
    applySettings({ ...values, font_scale: Number(values.font_scale) });
    document.querySelector("#period-select").value = values.period;
    await Promise.all([loadDashboard(), loadReports()]);
    showNotice(settings.message);
  } catch (error) {
    showNotice(error.message, true);
  }
});

document.querySelector("#notification-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const values = Object.fromEntries(new FormData(form));
  values.notifications = form.elements.notifications.checked;
  if (values.notifications && "Notification" in window) {
    const permission = await Notification.requestPermission();
    if (permission !== "granted") {
      form.elements.notifications.checked = false;
      values.notifications = false;
      showNotice("Browser notifications were not allowed.", true);
    }
  }
  try {
    const current = await api("/api/settings");
    await api("/api/settings", { method: "PUT", body: JSON.stringify({ ...current, ...values }) });
    localStorage.setItem("civicNotifications", String(values.notifications));
    scheduleDailyReminder({ ...current, ...values });
    await loadAssignments();
    showNotice("Notification settings saved.");
  } catch (error) {
    showNotice(error.message, true);
  }
});

document.querySelector("#test-notification").addEventListener("click", async () => {
  if (!("Notification" in window)) {
    showNotice("This browser does not support notifications.", true);
    return;
  }
  const permission = await Notification.requestPermission();
  if (permission === "granted") {
    notify("Civic Track notifications are on", "You can now receive reminders while this app is open.");
    showNotice("Test notification sent.");
  } else showNotice("Browser notification permission was not granted.", true);
});

document.querySelector("#request-change-code").addEventListener("click", () => requestVerificationCode("change").catch((error) => showNotice(error.message, true)));
document.querySelector("#change-password-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  try {
    await api("/api/auth/change-password", { method: "POST", body: JSON.stringify(Object.fromEntries(new FormData(form))) });
    form.reset();
    form.hidden = true;
    showNotice("Password changed.");
  } catch (error) {
    showNotice(error.message, true);
  }
});

document.querySelector("#delete-account-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!window.confirm("Permanently delete your account and all local Civic Track data? This cannot be undone.")) return;
  try {
    await api("/api/account", { method: "DELETE", body: JSON.stringify(Object.fromEntries(new FormData(event.currentTarget))) });
    window.location.reload();
  } catch (error) {
    showNotice(error.message, true);
  }
});

document.querySelector("#logout-button").addEventListener("click", async () => {
  try {
    await api("/api/auth/logout", { method: "POST" });
    window.location.reload();
  } catch (error) {
    showNotice(error.message, true);
  }
});

document.querySelector("#troubleshoot-button").addEventListener("click", async () => {
  try {
    await api("/api/auth/status");
    await refreshAll();
    await loadSettings();
    showNotice("App refreshed. Your saved local data is still here.");
  } catch (error) {
    showNotice(`Refresh failed: ${error.message}`, true);
  }
});

document.querySelector("#calendar-prev").addEventListener("click", () => {
  calendarDate = new Date(calendarDate.getFullYear(), calendarDate.getMonth() - 1, 1);
  loadCalendar().catch((error) => showNotice(error.message, true));
});
document.querySelector("#calendar-next").addEventListener("click", () => {
  calendarDate = new Date(calendarDate.getFullYear(), calendarDate.getMonth() + 1, 1);
  loadCalendar().catch((error) => showNotice(error.message, true));
});

document.querySelector("#report-type").addEventListener("change", () => {
  if (reportData) renderReport(reportData);
});
document.querySelector("#print-report").addEventListener("click", () => {
  if (!reportData) return;
  printPage(document.querySelector("#report-title").textContent, document.querySelector("#report-preview").innerHTML);
});
document.querySelector("#print-badges").addEventListener("click", () => {
  printPage("Civic Track achievement badges", document.querySelector("#all-badges").innerHTML);
});
document.querySelector("#export-resume").addEventListener("click", async () => {
  try {
    const data = await api(`/api/reports?period=${encodeURIComponent(document.querySelector("#period-select").value)}`);
    const organizations = data.organizations.map((item) => `<li>${escapeHtml(item.name)} — ${escapeHtml(item.kind)}</li>`).join("") || "<li>No affiliations listed.</li>";
    const service = data.entries.map((item) => `<li>${formatDate(item.date)} — ${escapeHtml(item.activity)} at ${escapeHtml(item.location)}${item.organization ? ` · ${escapeHtml(item.organization)}` : ""}, ${item.hours} hours</li>`).join("") || "<li>No volunteer entries.</li>";
    const assignments = data.assignments.filter((item) => item.completed_at).map((item) => `<li>${escapeHtml(item.title)} — ${escapeHtml(item.subject)}; ${item.on_time ? "completed on time" : "completed late"}</li>`).join("") || "<li>No completed tasks listed.</li>";
    printPage("Volunteer & Learning Resume", `<h2>${escapeHtml(data.name || "Volunteer")}</h2><p>Volunteer and student activity draft · ${data.hours} hours logged (not independently verified)</p><h3>Affiliations</h3><ul>${organizations}</ul><h3>Community service</h3><ul>${service}</ul><h3>Completed assignments</h3><ul>${assignments}</ul><p class="report-footnote">Review and personalize this draft before sharing it.</p>`);
  } catch (error) {
    showNotice(error.message, true);
  }
});

document.querySelector("#volunteer-form").elements.date.value = new Date().toISOString().slice(0, 10);
document.querySelector("#goal-form").elements.starts_on.value = new Date().toISOString().slice(0, 10);
document.querySelector("#goal-form").elements.ends_on.value = new Date(Date.now() + 7 * 86400000).toISOString().slice(0, 10);
document.querySelector("#signup-form").elements.birthdate.max = new Date().toISOString().slice(0, 10);
loadAppFromSession();
