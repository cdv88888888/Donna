// Donna dashboard — fetches state and renders the calm focus view.
const $ = (id) => document.getElementById(id);
const api = (path, opts) => fetch(path, opts).then((r) => r.json());
const esc = (s) => (s || "").replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const SRC_ICON = { gmail: "✉", telegram: "✈", calendar: "◷", system: "•" };

// ── Theme toggle (stamps data-theme so it beats the media query both ways) ──
$("theme").onclick = () => {
  const root = document.documentElement;
  const dark = matchMedia("(prefers-color-scheme: dark)").matches;
  const cur = root.getAttribute("data-theme") || (dark ? "dark" : "light");
  root.setAttribute("data-theme", cur === "dark" ? "light" : "dark");
};

function label(name, count) {
  return `<div class="label"><span>${name}</span><div class="rule"></div>` +
         `<div class="count">${count}</div></div>`;
}

function needsCard(it) {
  const cls = ["urgent", "high"].includes(it.priority) ? "card urgent" : "card";
  const draft = it.draft
    ? `<div class="donna"><span class="tag">Donna drafted a reply · in your voice</span>
         <p id="d${it.draft.id}">${esc(it.draft.body)}</p></div>
       <div class="actions">
         <button class="btn primary" onclick="approve(${it.draft.id})">Approve &amp; send</button>
         <button class="btn ghost" onclick="editDraft(${it.draft.id})">Edit</button>
         <button class="btn ghost" onclick="dismiss(${it.id}, this)">Dismiss</button>
       </div>`
    : `<div class="actions">
         <button class="btn ghost" onclick="dismiss(${it.id}, this)">Dismiss</button>
       </div>`;
  return `<div class="${cls}" data-item="${it.id}">
    <div class="meta">
      <span class="chip pri">● ${esc(it.priority)}</span>
      <span class="chip src">${SRC_ICON[it.source] || ""} ${esc(it.source)}</span>
      <span class="who">${esc(it.sender || "")}</span>
      <span class="when">${esc(it.when || "")}</span>
    </div>
    <h3>${esc(it.subject || "(no subject)")}</h3>
    ${draft}
  </div>`;
}

function render(state) {
  $("clock").textContent = state.date;
  $("greet").textContent = state.greeting;
  const t = state.thesis;
  $("thesis").innerHTML =
    `While you were away, <span class="num">${t.incoming}</span> things came in. ` +
    `I handled <span class="num">${t.handled}</span>. <b>${t.needs_you} need you.</b>`;

  let html = "";

  html += label("Needs you", `${state.needs_you.length} items`);
  html += state.needs_you.length
    ? `<div class="stack">${state.needs_you.map(needsCard).join("")}</div>`
    : `<div class="empty">You're all clear. Nothing needs you right now.</div>`;

  if (state.vips.length) {
    html += label("From your people", `${state.vips.length} VIPs`);
    html += `<div class="people">` + state.vips.map((v) =>
      `<div class="person"><div class="av">${esc(initials(v.name))}</div>
       <div class="nm">${esc(v.name.split(" ")[0])}</div>
       <div class="st">${esc(v.note || "")}</div></div>`).join("") + `</div>`;
  }

  if (state.followups.length) {
    html += label("Waiting on a reply", `${state.followups.length} threads`);
    html += `<div class="waiting">` + state.followups.map((f) =>
      `<div class="wrow"><div class="body"><div class="p">${esc(f.name)}</div>
       <div class="s">${esc(f.subject)}</div></div>
       <span class="age ${f.age >= 5 ? "old" : ""}">${f.age}d</span>
       <button class="nudge" onclick="nudge(${f.id}, this)">Nudge</button></div>`).join("") + `</div>`;
  }

  html += label("Today", `${state.today.length} events`);
  html += state.today.length
    ? `<div class="timeline">` + state.today.map((e) =>
        `<div class="slot"><div class="t">${esc(e.time)}</div><div class="ev">${esc(e.title)}</div></div>`).join("") + `</div>`
    : `<div class="empty">Nothing on the calendar today.</div>`;

  html += label("To-do", `${state.tasks.filter((x) => !x.done).length} open`);
  html += `<div class="todos">` + state.tasks.map((t) =>
    `<div class="todo ${t.done ? "done" : ""}"><div class="box" onclick="toggleTask(${t.id})">✓</div>
     <div class="txt">${esc(t.text)}${t.by === "donna" ? '<span class="by">Donna added</span>' : ""}</div></div>`).join("") + `</div>`;

  if (state.handled.length) {
    html += label("Handled for you", `${state.handled.length} items`);
    html += `<details class="handled"><summary>I cleared these so you didn't have to — tap to see</summary>
      <div class="body">${state.handled.map((h) => `<div>${esc(h.summary)}</div>`).join("")}</div></details>`;
  }

  $("sections").innerHTML = html;
}

const initials = (n) => n.split(/\s+/).slice(0, 2).map((w) => w[0]).join("").toUpperCase();

// ── Actions ──
async function approve(id) { await api(`/api/drafts/${id}/approve`, { method: "POST" }); refresh(); }
async function dismiss(id, el) { el.closest(".card").classList.add("gone"); await api(`/api/items/${id}/dismiss`, { method: "POST" }); setTimeout(refresh, 250); }
async function toggleTask(id) { await api(`/api/tasks/${id}/toggle`, { method: "POST" }); refresh(); }
async function nudge(id, el) { el.textContent = "Drafted"; await api(`/api/followups/${id}/nudge`, { method: "POST" }); }
function editDraft(id) {
  const p = $("d" + id);
  const ta = document.createElement("textarea");
  ta.value = p.textContent;
  p.replaceWith(ta);
  ta.focus();
  ta.onblur = () => api(`/api/drafts/${id}`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ body: ta.value }),
  });
}

$("send").onclick = sendCmd;
$("cmd").addEventListener("keydown", (e) => { if (e.key === "Enter") sendCmd(); });
async function sendCmd() {
  const input = $("cmd");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  $("reply").textContent = "Donna is thinking…";
  const res = await api("/api/command", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  $("reply").textContent = res.reply || "";
  refresh();
}

async function refresh() { render(await api("/api/state")); }

// ── PWA: service worker + push registration ──
async function setupPush() {
  if (!("serviceWorker" in navigator)) return;
  const reg = await navigator.serviceWorker.register("/sw.js");
  const { key } = await api("/api/push/key");
  if (!key || Notification.permission === "denied") return;
  const perm = await Notification.requestPermission();
  if (perm !== "granted") return;
  const sub = await reg.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlB64ToUint8Array(key),
  });
  await api("/api/push/subscribe", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(sub),
  });
}
function urlB64ToUint8Array(base64) {
  const pad = "=".repeat((4 - (base64.length % 4)) % 4);
  const b64 = (base64 + pad).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(b64);
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
}

refresh();
setInterval(refresh, 60000);
setupPush();
