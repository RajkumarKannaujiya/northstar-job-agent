const API = String(window.NORTHSTAR_API_URL || "").replace(/\/+$/, "");
const API_READY = Boolean(API) || (["localhost", "127.0.0.1"].includes(location.hostname) && location.port === "3000");
const tokenKey = "northstar_session";
const token = () => sessionStorage.getItem(tokenKey);
const api = async (path, options = {}) => {
  const headers = new Headers(options.headers || {});
  if (token()) headers.set("Authorization", `Bearer ${token()}`);
  if (options.body && !(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const response = await fetch(`${API}/api${path}`, {...options, headers});
  if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(data.detail || `Request failed (${response.status})`); }
  if (response.status === 204) return null;
  return response.json();
};
const $ = (id) => document.getElementById(id);
const showMessage = (id, message, error = false) => { const node = $(id); node.textContent = message; node.classList.toggle("error", error); };
function setAuthenticated(yes) { $("auth").classList.toggle("hidden", yes); $("app").classList.toggle("hidden", !yes); }
async function auth(mode) {
  const email = $("email").value.trim(), password = $("password").value;
  try {
    const data = await api(`/auth/${mode}`, {method:"POST", body:JSON.stringify({email,password})});
    sessionStorage.setItem(tokenKey, data.access_token); $("auth-error").textContent = ""; setAuthenticated(true); await loadAll();
  } catch (err) { $("auth-error").textContent = err.message; }
}
async function loadAll() {
  try {
    const [dash,jobs,apps,resumes,profile] = await Promise.all([api("/dashboard"),api("/jobs?limit=30"),api("/applications"),api("/resumes"),api("/profile")]);
    $("m-discovered").textContent = dash.jobs_discovered; $("m-matched").textContent = dash.high_match_jobs; $("m-applied").textContent = dash.applications_submitted; $("m-pending").textContent = dash.pending_actions;
    renderJobs(jobs); renderApps(apps); renderResumes(resumes);
    $("score").value = profile.preferences?.minimum_match_score ?? 80; $("score-label").textContent = `${$("score").value}%`;
    $("locations").value = (profile.preferences?.preferred_locations || []).join(", ");
  } catch (err) { showMessage("message", err.message, true); if (err.message.includes("Authentication")) {sessionStorage.removeItem(tokenKey);setAuthenticated(false);} }
}
function renderJobs(jobs) {
  const list = $("job-list");
  if (!jobs.length) { list.innerHTML = '<div class="empty-state">No jobs yet. Run demo discovery to try the sample portal.</div>'; return; }
  list.innerHTML = jobs.filter(j => !j.match || j.match.score >= 50).slice(0,6).map(j => `<article class="job-card"><div><div class="job-title">${esc(j.title)}</div><div class="job-company">${esc(j.company)}</div><div class="job-meta"><span>⌖ ${esc(j.location || "Location not listed")}</span><span>◷ ${j.posted_at ? timeAgo(j.posted_at) : "Date unknown"}</span><span>${j.salary_min ? money(j.salary_min,j.currency) : "Salary undisclosed"}</span></div></div><div class="score">${j.match ? `${Math.round(j.match.score)}%` : "—"}</div><div class="job-actions"><a href="${safeUrl(j.application_url)}" target="_blank" rel="noreferrer">View job ↗</a><button data-analyze="${j.id}">Analyze fit</button><button data-apply="${j.id}">Track application</button></div></article>`).join("");
  list.querySelectorAll("[data-analyze]").forEach(b=>b.onclick=async()=>{try{const r=await api(`/jobs/${b.dataset.analyze}/analyze`,{method:"POST"});alert(`Match ${r.match_score}% · ${r.decision.decision}\n\n${r.reasons.join("\n")}${r.missing.length?`\n\nSkills not present: ${r.missing.join(", ")}`:""}`);await loadAll();}catch(e){showMessage("message",e.message,true);}});
  list.querySelectorAll("[data-apply]").forEach(b=>b.onclick=async()=>{try{const a=await api("/applications?job_id="+encodeURIComponent(b.dataset.apply),{method:"POST"});alert(`Application tracking created: ${a.status}.\nOpen the job link to continue manually.`);await loadAll();}catch(e){alert(e.message);}});
}
function renderApps(apps) { const box=$("application-list"); if(!apps.length){box.innerHTML='<div class="empty-state">Your application activity will appear here.</div>';return;} box.innerHTML=apps.slice(0,5).map(a=>`<div class="activity-row"><span class="activity-dot ${a.status==="SUBMITTED"?"submitted":"pending"}"></span><div><b>${esc(a.job_title)} · ${esc(a.company)}</b><small>${esc(a.status.replaceAll("_"," "))}</small></div><time>${timeAgo(a.created_at)}</time></div>`).join(""); }
function renderResumes(resumes) { $("resume-count").textContent=resumes.length; const box=$("resume-list"); if(!resumes.length){box.innerHTML='<div class="empty-state">No resumes yet.</div>';return;} box.innerHTML=resumes.map(r=>`<div class="resume-row"><span class="resume-icon">▧</span><div><b>${esc(r.filename)}</b><small>${(r.parsed_data.skills||[]).slice(0,4).map(esc).join(" · ")||"Review extracted details"}</small></div></div>`).join(""); }
const esc = (s) => String(s ?? "").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
const safeUrl = (url) => { try { const parsed=new URL(url,location.origin); return ["http:","https:"].includes(parsed.protocol)?esc(parsed.href):"#"; } catch{return "#";} };
const timeAgo = (value) => {const hours=Math.max(0,(Date.now()-new Date(value).getTime())/3600000);return hours<1?`${Math.max(1,Math.floor(hours*60))}m ago`:hours<24?`${Math.floor(hours)}h ago`:`${Math.floor(hours/24)}d ago`;};
const money = (value,currency) => `${currency||"₹"} ${new Intl.NumberFormat("en-IN",{maximumFractionDigits:0}).format(value)}`;
$("auth-form").addEventListener("submit",e=>{e.preventDefault();auth("login")}); $("register").onclick=()=>auth("register");
$("signout").onclick=()=>{sessionStorage.removeItem(tokenKey);setAuthenticated(false)}; $("refresh").onclick=loadAll;
$("discover").onclick=async()=>{try{await api("/jobs/discover-mock",{method:"POST"});await loadAll();showMessage("message","Demo jobs discovered and ranked.");}catch(e){showMessage("message",e.message,true)}};
$("save-preferences").onclick=async()=>{try{await api("/preferences",{method:"PATCH",body:JSON.stringify({minimum_match_score:Number($("score").value),preferred_locations:$(("locations")).value.split(",").map(x=>x.trim()).filter(Boolean)})});showMessage("message","Preferences saved.")}catch(e){showMessage("message",e.message,true)}};
$("score").oninput=()=>$("score-label").textContent=`${$("score").value}%`; $("notice-resume").onclick=()=>$("resume-panel").scrollIntoView({behavior:"smooth"});
$("resume-file").onchange=async(e)=>{const file=e.target.files[0];if(!file)return;const form=new FormData();form.append("file",file);try{await api("/resumes/upload",{method:"POST",body:form});showMessage("upload-message","Resume uploaded and parsed. Review extracted fields in your profile.");await loadAll();}catch(err){showMessage("upload-message",err.message,true);}e.target.value=""};
if (!API_READY) {
  $("backend-warning").classList.remove("hidden");
  $("api-docs").removeAttribute("target");
  $("api-docs").textContent = "API not configured";
  $("auth-form").querySelectorAll("input, button").forEach(control => { control.disabled = true; });
} else {
  $("api-docs").href = API ? API + "/docs" : "/docs";
}
if(token() && API_READY){setAuthenticated(true);loadAll()} else setAuthenticated(false);
