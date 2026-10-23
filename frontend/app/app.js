const localDevelopment = ["localhost", "127.0.0.1"].includes(location.hostname) && location.port === "3000";
const API = String(window.NORTHSTAR_API_URL || (localDevelopment ? "http://localhost:8000" : "")).replace(/\/+$/, "");
const API_READY = Boolean(API);
const tokenKey = "northstar_session";
const state = {jobs: [], applications: [], resumes: [], boards: [], platforms: [], notifications: [], profile: {}, showAllJobs: false, showAllApplications: false};
const token = () => sessionStorage.getItem(tokenKey);
const $ = (id) => document.getElementById(id);

const api = async (path, options = {}) => {
  const headers = new Headers(options.headers || {});
  if (token()) headers.set("Authorization", `Bearer ${token()}`);
  if (options.body && !(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
  let response;
  try { response = await fetch(`${API}/api${path}`, {...options, headers}); }
  catch { throw new Error("Could not reach the API. Check the backend URL and network connection."); }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const detail = Array.isArray(data.detail) ? data.detail.map(issue => issue.msg || issue.type || "Invalid input").join("; ") : data.detail;
    throw new Error(typeof detail === "string" ? detail : `Request failed (${response.status})`);
  }
  if (response.status === 204) return null;
  return response.json();
};

const showMessage = (id, message, error = false) => {
  const node = $(id);
  if (!node) return;
  node.textContent = message;
  node.classList.toggle("error", error);
};
function setAuthenticated(yes) { $("auth").classList.toggle("hidden", yes); $("app").classList.toggle("hidden", !yes); }

async function auth(mode) {
  const email = $("email").value.trim(), password = $("password").value;
  try {
    const data = await api(`/auth/${mode}`, {method: "POST", body: JSON.stringify({email, password})});
    sessionStorage.setItem(tokenKey, data.access_token);
    $("auth-error").textContent = "";
    setAuthenticated(true);
    await loadAll();
  } catch (err) { $("auth-error").textContent = err.message; }
}

async function loadAll() {
  try {
    const [dash, jobs, apps, resumes, profile, platforms, boards, notifications, automation] = await Promise.all([
      api("/dashboard"), api("/jobs?limit=200"), api("/applications"), api("/resumes"), api("/profile"),
      api("/platforms"), api("/platforms/company-careers"), api("/notifications"), api("/automation/status"),
    ]);
    state.jobs = jobs.filter(job => {
      const platforms = (job.sources || []).map(source => source.platform);
      return !platforms.length || platforms.some(platform => platform !== "mock");
    });
    state.applications = apps;
    state.resumes = resumes;
    state.platforms = platforms;
    state.boards = boards.boards || [];
    state.notifications = notifications;
    state.profile = profile;
    $("m-discovered").textContent = state.jobs.length;
    $("m-matched").textContent = state.jobs.filter(job => job.match && job.match.score >= 85).length;
    $("m-applied").textContent = dash.applications_submitted;
    $("m-pending").textContent = dash.pending_actions;
    $("score").value = profile.preferences?.minimum_match_score ?? 0;
    $("score-label").textContent = `${$("score").value}%`;
    $("locations").value = (profile.preferences?.preferred_locations || []).join(", ");
    $("profile-name").value = profile.personal?.full_name || "";
    $("profile-phone").value = profile.personal?.phone || "";
    $("target-titles").value = (profile.professional?.target_job_titles || []).join(", ");
    $("minimum-salary").value = profile.preferences?.minimum_salary ?? "";
    $("excluded-keywords").value = (profile.preferences?.excluded_keywords || []).join(", ");
    $("remote-allowed").checked = profile.preferences?.remote_allowed !== false;
    $("automation-state").textContent = automation.active ? "SCHEDULED" : "PAUSED";
    $("automation-help").textContent = automation.scheduler_configured
      ? "Opt in for scheduled discovery. Remote OK refreshes about every six hours; Remotive refreshes daily. Review and submit each application on its source site."
      : "Search job feeds now. Scheduled refresh is not configured on the server yet, so use Search job feeds whenever you want an update.";
    $("start-automation").disabled = !automation.scheduler_configured;
    renderJobs(); renderPlatformSearchLinks(); renderApps(); renderResumes(); renderPlatforms(); renderBoards(); renderNotifications();
  } catch (err) {
    showMessage("message", err.message, true);
    if (err.message.includes("Authentication")) { sessionStorage.removeItem(tokenKey); setAuthenticated(false); }
  }
}

function renderJobs() {
  const list = $("job-list");
  if (!state.jobs.length) { list.innerHTML = '<div class="empty-state">Search public feeds to load listings, or search the job sites above.</div>'; return; }
  const minimumScore = Number($("score").value || 0);
  const minimumSalary = Number($("minimum-salary").value || 0);
  const preferredLocations = splitList($("locations").value).map(value => value.toLowerCase());
  const excludedKeywords = splitList($("excluded-keywords").value).map(value => value.toLowerCase());
  const remoteAllowed = $("remote-allowed").checked;
  const matching = state.jobs.filter(j => {
    if (j.match && j.match.score < minimumScore) return false;
    if (minimumSalary > 0 && j.salary_min != null && Number(j.salary_min) < minimumSalary) return false;
    const searchable = `${j.title || ""} ${j.company || ""} ${j.location || ""} ${j.description || ""}`.toLowerCase();
    if (excludedKeywords.some(keyword => searchable.includes(keyword))) return false;
    const location = String(j.location || "").toLowerCase();
    const isRemote = String(j.remote_type || "").toUpperCase() === "REMOTE" || location.includes("remote") || location.includes("worldwide");
    if (isRemote && !remoteAllowed) return false;
    if (preferredLocations.length && !preferredLocations.some(place => location.includes(place)) && !(isRemote && remoteAllowed)) return false;
    return true;
  }).sort((a, b) => {
    const aPosted = a.posted_at ? new Date(a.posted_at).getTime() : 0;
    const bPosted = b.posted_at ? new Date(b.posted_at).getTime() : 0;
    if (aPosted !== bPosted) return bPosted - aPosted;
    return new Date(b.created_at || 0).getTime() - new Date(a.created_at || 0).getTime();
  });
  const visible = state.showAllJobs ? matching : matching.slice(0, 6);
  $("view-jobs").textContent = state.showAllJobs ? "Top jobs ↑" : `All jobs (${matching.length}) →`;
  if (!matching.length) { list.innerHTML = '<div class="empty-state">No listings match these filters. Lower the match score or relax the location, salary, or excluded-keyword filters.</div>'; return; }
  list.innerHTML = visible.map(j => {
    const sourceNames = [...new Set((j.sources || []).map(source => ({remoteok: "Remote OK", remotive: "Remotive", greenhouse: "Greenhouse", lever: "Lever"}[source.platform] || source.platform)))];
    return `<article class="job-card"><div><div class="job-title">${esc(j.title)}</div><div class="job-company">${esc(j.company)}${sourceNames.length ? ` · ${esc(sourceNames.join(", "))}` : ""}</div><div class="job-meta"><span>⌖ ${esc(j.location || "Location not listed")}</span><span>◷ ${j.posted_at ? timeAgo(j.posted_at) : "Date unknown"}</span><span>${j.salary_min ? money(j.salary_min, j.currency) : "Salary undisclosed"}</span></div></div><div class="score">${j.match ? `${Math.round(j.match.score)}%` : "—"}</div><div class="job-actions"><a href="${safeUrl(j.application_url)}" target="_blank" rel="noreferrer">View job ↗</a><button data-analyze="${esc(j.id)}">Analyze fit</button><button data-apply="${esc(j.id)}">Track application</button></div></article>`;
  }).join("");
  list.querySelectorAll("[data-analyze]").forEach(button => button.onclick = async () => {
    try {
      const result = await api(`/jobs/${encodeURIComponent(button.dataset.analyze)}/analyze`, {method: "POST"});
      alert(`Match ${result.match_score}% · ${result.decision.decision}\n\n${result.reasons.join("\n")}${result.missing.length ? `\n\nSkills not listed on your resume: ${result.missing.join(", ")}` : ""}`);
      await loadAll();
    } catch (err) { showMessage("message", err.message, true); }
  });
  list.querySelectorAll("[data-apply]").forEach(button => button.onclick = async () => {
    try {
      const application = await api(`/applications?job_id=${encodeURIComponent(button.dataset.apply)}`, {method: "POST"});
      alert(`Tracking created: ${application.status}.\nOpen the employer link to complete the application manually.`);
      await loadAll();
    } catch (err) { alert(err.message); }
  });
}

function splitList(value) { return String(value || "").split(",").map(item => item.trim()).filter(Boolean); }

function renderPlatformSearchLinks() {
  const box = $("platform-search-links");
  if (!box) return;
  const titles = splitList($("target-titles").value || (state.profile.professional?.target_job_titles || []).join(", "));
  const locations = splitList($("locations").value || (state.profile.preferences?.preferred_locations || []).join(", "));
  const title = titles[0] || "";
  const location = locations[0] || "India";
  const keyword = title;
  const slug = value => String(value).normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase().trim().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  const indeed = new URL("https://in.indeed.com/jobs");
  if (keyword) indeed.searchParams.set("q", keyword);
  indeed.searchParams.set("l", location);
  indeed.searchParams.set("sort", "date");
  const linkedin = new URL("https://www.linkedin.com/jobs/search/");
  if (keyword) linkedin.searchParams.set("keywords", keyword);
  linkedin.searchParams.set("location", location);
  linkedin.searchParams.set("sortBy", "DD");
  const apna = new URL("https://apna.co/job-search");
  if (title) apna.searchParams.set("query", title);
  if (location) apna.searchParams.set("location", location);
  const links = [
    ["Naukri", `https://www.naukri.com/${slug(keyword) ? `${slug(keyword)}-jobs-in-` : "jobs-in-"}${slug(location.toLowerCase().includes("remote") ? "india" : location) || "india"}`],
    ["Indeed", indeed.href], ["Apna", apna.href], ["LinkedIn", linkedin.href],
  ];
  box.innerHTML = links.map(([name, url]) => `<a class="platform-search-link" href="${safeUrl(url)}" target="_blank" rel="noopener noreferrer">${esc(name)} ↗</a>`).join("");
}

function renderApps() {
  const box = $("application-list"), visible = state.showAllApplications ? state.applications : state.applications.slice(0, 5);
  $("view-applications").textContent = state.showAllApplications ? "Recent activity ↑" : `View tracker (${state.applications.length}) →`;
  if (!visible.length) { box.innerHTML = '<div class="empty-state">Your application activity will appear here.</div>'; return; }
  box.innerHTML = visible.map(app => `<div class="activity-row"><span class="activity-dot ${app.status === "SUBMITTED" ? "submitted" : "pending"}"></span><div><b>${esc(app.job_title)} · ${esc(app.company)}</b><small>${esc(app.status.replaceAll("_", " "))}</small></div><time>${timeAgo(app.created_at)}</time></div>`).join("");
}

function renderResumes() {
  $("resume-count").textContent = state.resumes.length;
  const box = $("resume-list");
  if (!state.resumes.length) { box.innerHTML = '<div class="empty-state">No resumes yet.</div>'; return; }
  box.innerHTML = state.resumes.map(resume => `<div class="resume-row"><span class="resume-icon">▧</span><div class="resume-info"><b>${esc(resume.filename)}${resume.is_preferred ? " · Preferred" : ""}</b><small>${(resume.parsed_data.skills || []).slice(0, 4).map(esc).join(" · ") || "Review extracted details"}</small><div class="resume-actions"><button data-download-resume="${esc(resume.id)}">Download</button><button data-prefer-resume="${esc(resume.id)}">Make preferred</button><button data-delete-resume="${esc(resume.id)}">Delete</button></div></div></div>`).join("");
  box.querySelectorAll("[data-download-resume]").forEach(button => button.onclick = () => downloadResume(button.dataset.downloadResume));
  box.querySelectorAll("[data-prefer-resume]").forEach(button => button.onclick = async () => {
    try { await api(`/resumes/${encodeURIComponent(button.dataset.preferResume)}/preferred`, {method: "PUT"}); await loadAll(); }
    catch (err) { showMessage("upload-message", err.message, true); }
  });
  box.querySelectorAll("[data-delete-resume]").forEach(button => button.onclick = async () => {
    if (!confirm("Delete this encrypted resume and its parsed profile data?")) return;
    try { await api(`/resumes/${encodeURIComponent(button.dataset.deleteResume)}`, {method: "DELETE"}); showMessage("upload-message", "Resume deleted."); await loadAll(); }
    catch (err) { showMessage("upload-message", err.message, true); }
  });
}

async function downloadResume(id) {
  try {
    const headers = token() ? {Authorization: `Bearer ${token()}`} : {};
    const response = await fetch(`${API}/api/resumes/${encodeURIComponent(id)}/download`, {headers});
    if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(data.detail || `Download failed (${response.status})`); }
    const url = URL.createObjectURL(await response.blob()), link = document.createElement("a");
    link.href = url; link.download = state.resumes.find(item => item.id === id)?.filename || "resume";
    document.body.append(link); link.click(); link.remove(); URL.revokeObjectURL(url);
  } catch (err) { showMessage("upload-message", err.message, true); }
}

function renderBoards() {
  const box = $("career-board-list");
  if (!state.boards.length) { box.innerHTML = '<div class="empty-state">No public company boards configured.</div>'; return; }
  box.innerHTML = state.boards.map((board, index) => `<div class="resume-row"><span class="resume-icon">↗</span><div><b>${esc(board.company_name)} · ${esc(board.provider)}</b><small>${esc(board.board_token)} · public jobs only</small></div><button data-remove-board="${index}">Remove</button></div>`).join("");
  box.querySelectorAll("[data-remove-board]").forEach(button => button.onclick = async () => {
    state.boards.splice(Number(button.dataset.removeBoard), 1);
    await saveBoards();
  });
}

function renderPlatforms() {
  const box = $("platform-list");
  box.innerHTML = state.platforms.filter(item => !["greenhouse", "lever", "remoteok", "remotive"].includes(item.platform)).map(item => `<div class="resume-row"><span class="resume-icon">◎</span><div><b>${esc(item.platform)}</b><small>${esc(item.status.replaceAll("_", " "))} · manual link mode</small></div><button data-source-platform="${esc(item.platform)}" data-source-status="${esc(item.status)}">${item.status === "DISCONNECTED" ? "Track" : "Remove"}</button></div>`).join("") || '<div class="empty-state">Other platforms need official integrations; use their job links manually.</div>';
  box.querySelectorAll("[data-source-platform]").forEach(button => button.onclick = async () => {
    try {
      const name = button.dataset.sourcePlatform;
      if (button.dataset.sourceStatus === "DISCONNECTED") await api(`/platforms/connect?platform=${encodeURIComponent(name)}`, {method: "POST"});
      else await api(`/platforms/${encodeURIComponent(name)}`, {method: "DELETE"});
      await loadAll();
    } catch (err) { showMessage("source-message", err.message, true); }
  });
}

function renderNotifications() {
  const box = $("notification-list");
  if (!state.notifications.length) { box.innerHTML = '<div class="empty-state">No notifications yet.</div>'; return; }
  box.innerHTML = state.notifications.map(item => `<div class="activity-row"><span class="activity-dot ${item.read ? "" : "pending"}"></span><div><b>${esc(item.title)}</b><small>${esc(item.body)}</small></div><time>${timeAgo(item.created_at)}</time>${item.read ? "" : `<button data-read-notice="${esc(item.id)}">Mark read</button>`}</div>`).join("");
  box.querySelectorAll("[data-read-notice]").forEach(button => button.onclick = async () => {
    try { await api(`/notifications/${encodeURIComponent(button.dataset.readNotice)}`, {method: "PATCH", body: JSON.stringify({read: true})}); await loadAll(); }
    catch (err) { showMessage("source-message", err.message, true); }
  });
}

const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;"}[char]));
const safeUrl = url => { try { const parsed = new URL(url, location.origin); return ["https:", "http:"].includes(parsed.protocol) ? esc(parsed.href) : "#"; } catch { return "#"; } };
const timeAgo = value => { const hours = Math.max(0, (Date.now() - new Date(value).getTime()) / 3600000); return hours < 1 ? `${Math.max(1, Math.floor(hours * 60))}m ago` : hours < 24 ? `${Math.floor(hours)}h ago` : `${Math.floor(hours / 24)}d ago`; };
const money = (value, currency) => `${currency || "₹"} ${new Intl.NumberFormat("en-IN", {maximumFractionDigits: 0}).format(value)}`;

async function saveBoards() {
  try {
    await api("/platforms/company-careers", {method: "PUT", body: JSON.stringify({boards: state.boards})});
    renderBoards();
    showMessage("source-message", "Company boards saved. Refresh jobs when you are ready.");
  } catch (err) { showMessage("source-message", err.message, true); }
}

$("auth-form").addEventListener("submit", event => { event.preventDefault(); auth("login"); });
$("register").onclick = () => auth("register");
$("signout").onclick = () => { sessionStorage.removeItem(tokenKey); setAuthenticated(false); };
$("refresh").onclick = loadAll;
$("discover").onclick = async () => {
  const button = $("discover");
  button.disabled = true;
  button.textContent = "Searching…";
  try {
    const result = await api("/jobs/discover-live", {method: "POST"});
    await loadAll();
    const sources = result.feeds.map(feed => `${feed.provider}: ${feed.status === "cached" ? "refreshed recently" : `${feed.status}${feed.count !== undefined ? `, ${feed.count} checked` : ""}`}${feed.new ? `, ${feed.new} new` : ""}`).join(" · ");
    const checked = result.feeds.some(feed => feed.status === "ok") ? `${result.count} live listings checked; ` : "";
    showMessage("message", `${checked}${result.new} new listings. ${sources}. Review and submit applications on the source site.`);
  }
  catch (err) { showMessage("message", err.message, true); }
  finally { button.disabled = false; button.textContent = "Search job feeds"; }
};
$("view-jobs").onclick = () => { state.showAllJobs = !state.showAllJobs; renderJobs(); };
$("view-applications").onclick = () => { state.showAllApplications = !state.showAllApplications; renderApps(); };
$("save-preferences").onclick = async () => {
  try {
    const preferences = {
      minimum_match_score: Number($("score").value),
      preferred_locations: $("locations").value.split(",").map(value => value.trim()).filter(Boolean),
      excluded_keywords: $("excluded-keywords").value.split(",").map(value => value.trim()).filter(Boolean),
      remote_allowed: $("remote-allowed").checked,
    };
    if ($("minimum-salary").value !== "") preferences.minimum_salary = Number($("minimum-salary").value);
    else preferences.minimum_salary = null;
    const profile = {
      personal: {...(state.profile.personal || {}), full_name: $("profile-name").value.trim(), phone: $("profile-phone").value.trim()},
      professional: {...(state.profile.professional || {}), target_job_titles: $("target-titles").value.split(",").map(value => value.trim()).filter(Boolean)},
      education: state.profile.education || {},
      preferences: {...(state.profile.preferences || {}), ...preferences},
      application_preferences: state.profile.application_preferences || {},
      answer_bank: state.profile.answer_bank || [],
    };
    await api("/profile", {method: "PUT", body: JSON.stringify(profile)});
    await api("/preferences", {method: "PATCH", body: JSON.stringify(preferences)});
    showMessage("message", "Preferences saved.");
    await loadAll();
  } catch (err) { showMessage("message", err.message, true); }
};
$("score").oninput = () => { $("score-label").textContent = `${$("score").value}%`; renderJobs(); };
$("minimum-salary").oninput = $("locations").oninput = $("excluded-keywords").oninput = () => renderJobs();
$("remote-allowed").onchange = () => renderJobs();
$("target-titles").oninput = () => renderPlatformSearchLinks();
$("notice-resume").onclick = () => $("resume-panel").scrollIntoView({behavior: "smooth"});
$("resume-file").onchange = async event => {
  const file = event.target.files[0]; if (!file) return;
  const form = new FormData(); form.append("file", file);
  try { await api("/resumes/upload", {method: "POST", body: form}); showMessage("upload-message", "Resume uploaded, encrypted, and parsed. Review the extracted information."); await loadAll(); }
  catch (err) { showMessage("upload-message", err.message, true); }
  event.target.value = "";
};
$("manual-job-form").onsubmit = async event => {
  event.preventDefault();
  const url = $("manual-job-url").value.trim();
  try {
    await api("/jobs", {method: "POST", body: JSON.stringify({platform: "manual", platform_job_id: `manual-${crypto.randomUUID()}`, title: $("manual-job-title").value.trim(), company: $("manual-job-company").value.trim(), location: $("manual-job-location").value.trim(), application_url: url, source_url: url, application_type: "EXTERNAL"})});
    event.target.reset(); await loadAll(); showMessage("message", "Job saved. Analyze its fit against your resume.");
  } catch (err) { showMessage("message", err.message, true); }
};
$("career-board-form").onsubmit = async event => {
  event.preventDefault();
  state.boards.push({provider: $("career-provider").value, company_name: $("career-company").value.trim(), board_token: $("career-token").value.trim()});
  await saveBoards();
  if (!$("source-message").classList.contains("error")) event.target.reset();
};
$("discover-careers").onclick = async () => {
  try { const result = await api("/jobs/discover-company-careers", {method: "POST"}); await loadAll(); showMessage("source-message", `Checked ${result.count} jobs; ${result.new} new. ${result.boards.filter(board => board.status === "failed").length} board(s) unavailable.`); }
  catch (err) { showMessage("source-message", err.message, true); }
};
$("connect-manual-source").onclick = async () => {
  try { const platform = $("manual-platform").value; await api(`/platforms/connect?platform=${encodeURIComponent(platform)}`, {method: "POST"}); await loadAll(); showMessage("source-message", "Saved as a manual source. Search and apply on the platform, then paste job links into Northstar."); }
  catch (err) { showMessage("source-message", err.message, true); }
};
$("read-all-notifications").onclick = async () => {
  try { await api("/notifications/read-all", {method: "POST"}); await loadAll(); }
  catch (err) { showMessage("source-message", err.message, true); }
};
$("start-automation").onclick = async () => {
  try { const result = await api("/automation/start", {method: "POST"}); await loadAll(); showMessage("message", result.message); }
  catch (err) { showMessage("message", err.message, true); }
};
$("stop-automation").onclick = async () => {
  try { await api("/automation/stop", {method: "POST"}); await loadAll(); showMessage("message", "Scheduled company-board discovery stopped."); }
  catch (err) { showMessage("message", err.message, true); }
};
$("export-account").onclick = async () => {
  try {
    const data = await api("/me/export"), blob = new Blob([JSON.stringify(data, null, 2)], {type: "application/json"});
    const url = URL.createObjectURL(blob), link = document.createElement("a");
    link.href = url; link.download = "northstar-account-export.json"; link.click(); URL.revokeObjectURL(url);
  } catch (err) { showMessage("message", err.message, true); }
};
$("delete-account").onclick = async () => {
  const confirmation = prompt("This permanently deletes your Northstar account, resumes, profile, applications, and notifications. Type DELETE to continue.");
  if (confirmation !== "DELETE") return;
  try {
    await api("/me", {method: "DELETE"});
    sessionStorage.removeItem(tokenKey);
    setAuthenticated(false);
    alert("Your account and stored data were deleted.");
  } catch (err) { showMessage("message", err.message, true); }
};

if (!API_READY) {
  $("backend-warning").classList.remove("hidden");
  $("api-docs").removeAttribute("target");
  $("api-docs").textContent = "API not configured";
  $("auth-form").querySelectorAll("input, button").forEach(control => { control.disabled = true; });
} else {
  $("api-docs").href = API ? `${API}/docs` : "/docs";
}
if (token() && API_READY) { setAuthenticated(true); loadAll(); } else setAuthenticated(false);
