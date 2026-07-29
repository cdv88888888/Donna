// Donna dashboard — fetches state and renders the calm focus view.
const $ = (id) => document.getElementById(id);
const api = (path, opts) => fetch(path, opts).then((r) => r.json());
const esc = (s) => (s || "").replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const SRC_ICON = { gmail: "✉", telegram: "✈", calendar: "◷", monday: "⬡", web: "⌘", system: "•" };

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
  const original = it.body || it.snippet || "";
  const who = (it.sender || "").split("—")[0].trim();
  const long = original.length > 140;
  const incoming = original
    ? `<div class="incoming">
         <span class="tag">What you're replying to${who ? " · " + esc(who) : ""}</span>
         <p class="msg ${long ? "clamp" : ""}" id="m${it.id}">${esc(original)}</p>
         ${long ? `<button class="more" onclick="toggleMsg(${it.id}, this)">Show full message</button>` : ""}
       </div>`
    : "";
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
  return `<div class="${cls}" data-item="${it.id}" data-draft="${it.draft ? it.draft.id : ""}">
    <div class="meta">
      <span class="chip pri">● ${esc(it.priority)}</span>
      <span class="chip src">${SRC_ICON[it.source] || ""} ${esc(it.source)}</span>
      <span class="who">${esc(it.sender || "")}</span>
      <span class="when">${esc(it.when || "")}</span>
    </div>
    <h3>${esc(it.subject || "(no subject)")}</h3>
    ${incoming}
    ${draft}
    <div class="hint">← Later · Approve →</div>
  </div>`;
}

// Swipe right = approve, swipe left = dismiss. Buttons still work too.
function attachSwipe(card) {
  const itemId = card.getAttribute("data-item");
  const draftId = card.getAttribute("data-draft");
  let startX = 0, dx = 0, dragging = false;
  const T = 90;
  card.style.touchAction = "pan-y";
  card.addEventListener("pointerdown", (e) => {
    if (e.target.closest("button, textarea, input, .more")) return;
    dragging = true; startX = e.clientX; dx = 0;
    card.setPointerCapture(e.pointerId);
    card.style.transition = "none";
  });
  card.addEventListener("pointermove", (e) => {
    if (!dragging) return;
    dx = e.clientX - startX;
    card.style.transform = `translateX(${dx}px) rotate(${dx / 30}deg)`;
    card.style.borderColor = dx > 40 ? "var(--good)" : dx < -40 ? "var(--urgent)" : "";
    const h = card.querySelector(".hint");
    if (h) h.textContent = dx > 40 ? (draftId ? "Approve & send ✓" : "Clear ✓")
      : dx < -40 ? "Later ↩" : "← Later · Approve →";
  });
  const end = () => {
    if (!dragging) return; dragging = false;
    if (dx > T) swipeCommit(card, "approve");
    else if (dx < -T) swipeCommit(card, "later");
    else { card.style.transition = "transform .2s"; card.style.transform = ""; card.style.borderColor = ""; }
    dx = 0;
  };
  card.addEventListener("pointerup", end);
  card.addEventListener("pointercancel", end);
}

function swipeCommit(card, action) {
  const itemId = card.getAttribute("data-item");
  const draftId = card.getAttribute("data-draft");
  const dir = action === "approve" ? 1 : -1;
  card.style.transition = "transform .26s cubic-bezier(.22,.61,.36,1), opacity .26s ease";
  card.style.transform = `translateX(${dir * 560}px) rotate(${dir * 12}deg)`;
  card.style.opacity = "0";
  setTimeout(async () => {
    if (action === "approve" && draftId) await api(`/api/drafts/${draftId}/approve`, { method: "POST" });
    else if (action === "later") await api(`/api/items/${itemId}/snooze`, { method: "POST" });  // comes back later
    else await api(`/api/items/${itemId}/dismiss`, { method: "POST" });
    refresh();
  }, 260);
}

function toggleMsg(id, btn) {
  const p = document.getElementById("m" + id);
  const collapsed = p.classList.toggle("clamp");
  btn.textContent = collapsed ? "Show full message" : "Show less";
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
  document.querySelectorAll(".stack .card").forEach(attachSwipe);
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

let currentView = "today";
async function refresh() {
  if (currentView === "projects") return renderProjects();
  if (currentView === "stash") return renderStash();
  render(await api("/api/state"));
}

// ── Projects view ──
function switchView(v) {
  currentView = v;
  for (const [tab, name] of [["tabToday", "today"], ["tabProjects", "projects"], ["tabStash", "stash"]]) {
    document.getElementById(tab).classList.toggle("on", v === name);
  }
  const show = v === "today" ? "" : "none";
  $("greet").style.display = show;
  $("thesis").style.display = show;
  refresh();
}

const PSTATUS = { needs_you: "Needs you", on_track: "On track", stalled: "Stalled" };

function projCard(p) {
  const chips = [
    p.deadline ? `<span class="pchip">${esc(p.deadline)}</span>` : "",
    p.amount ? `<span class="pchip">${esc(p.amount)}</span>` : "",
    p.created_by === "monday" ? `<span class="byd">⬡ Monday board</span>`
      : p.created_by === "donna" ? `<span class="byd">Donna created</span>` : "",
  ].join("");
  return `<div class="proj ${p.status}">
    <div class="prow">
      <span class="pstatus ${p.status}">● ${PSTATUS[p.status] || esc(p.status)}</span>
      ${chips}
      <button class="pmenu" title="Dismiss" onclick="dismissProject(${p.id})">⋯</button>
    </div>
    <div class="pname">${esc(p.name)}</div>
    ${p.next_action ? `<div class="pnext"><span class="k">Next action</span><span class="v">${esc(p.next_action)}</span></div>` : ""}
    ${p.owes ? `<div class="powes">${esc(p.owes)}</div>` : ""}
    <div class="pfoot">
      <span class="src">${esc(p.sources || "")}</span>
      ${p.needs_you ? `<span class="badge">${p.needs_you} need you</span>` : ""}
      <span class="when">${esc(p.when || "")}</span>
    </div>
  </div>`;
}

async function renderProjects() {
  const { projects, counts } = await api("/api/projects");
  if (!projects.length) {
    $("sections").innerHTML = `<div class="empty">No projects yet — Donna creates them as she scans your inbox.</div>`;
    return;
  }
  $("sections").innerHTML =
    `<p class="phead"><b>${counts.active} active</b> · <span class="r">${counts.needs_you} need you</span> · <span class="a">${counts.stalled} stalled</span> · tracked across your sources</p>` +
    `<div class="stack">${projects.map(projCard).join("")}</div>`;
}

async function dismissProject(id) {
  await api(`/api/projects/${id}/dismiss`, { method: "POST" });
  renderProjects();
}
window.switchView = switchView;
window.dismissProject = dismissProject;

// ── Stash view ──
// Where forwarded posts land. Four fixed buckets; topic folders inside them;
// sub-folders only ever appear after you accept a split Donna proposed.
const KINDS = { tool: "Tools to try", inspo: "Inspo", idea: "Ideas", read: "Read later" };

function stashItem(it) {
  const link = it.url
    ? `<a href="${esc(it.url)}" target="_blank" rel="noopener">${esc(it.title)}</a>`
    : esc(it.title);
  const desc = [it.summary, it.why].filter(Boolean).map(esc).join(" · ");
  const tried = it.kind === "tool"
    ? `<button class="mini" onclick="markTried(${it.id})">Tried it</button>` : "";
  return `<div class="sitem">
    <span class="plat">${esc(it.platform || "web")}</span>
    <div class="b">
      <div class="h">${link}</div>
      ${desc ? `<div class="d">${desc}</div>` : ""}
      ${it.note ? `<div class="d">Your note: ${esc(it.note)}</div>` : ""}
      <div class="acts">
        ${tried}
        <button class="mini" onclick="archiveStash(${it.id})">Archive</button>
      </div>
    </div>
    <span class="w">${esc(it.when || "")}</span>
  </div>`;
}

function askCard(it) {
  const kinds = Object.entries(KINDS).map(([k, label]) =>
    `<button class="kbtn" onclick="setKind(${it.id}, '${k}')">${label}</button>`).join("");
  return `<div class="ask">
    <p class="q">${esc(it.question || "What is this one?")}</p>
    <div class="src">${esc(it.url || (it.raw || "").slice(0, 160))}</div>
    <div class="row">
      <input id="ans${it.id}" placeholder="One line — what is it?"
             onkeydown="if(event.key==='Enter')answerStash(${it.id})">
      <button class="btn primary" onclick="answerStash(${it.id})">File it</button>
    </div>
    <div class="kinds"><span style="font-size:12px;color:var(--ink-faint);align-self:center;margin-right:2px;">or drop it straight into:</span>${kinds}</div>
  </div>`;
}

function splitCard(p) {
  return `<div class="split">
    <div class="t">Split <b>${esc(p.parent)}</b> → <b>${esc(p.name)}</b>?</div>
    <div class="r">${esc(p.rationale || "")} · ${p.count} items would move.</div>
    <div class="actions">
      <button class="btn primary" onclick="acceptSplit(${p.id})">Split it</button>
      <button class="btn ghost" onclick="rejectSplit(${p.id})">Keep as is</button>
    </div>
  </div>`;
}

function topicBlock(t) {
  const subs = t.subs.filter((sub) => sub.items.length).map((sub) =>
    `<div class="sub"><div class="n">${esc(sub.name)}</div>
     ${sub.items.map(stashItem).join("")}</div>`).join("");
  const total = t.items.length + t.subs.reduce((n, sub) => n + sub.items.length, 0);
  return `<div class="topic">
    <div class="thead"><span class="n">${esc(t.name)}</span><span class="c">${total}</span></div>
    ${t.items.map(stashItem).join("")}
    ${subs}
  </div>`;
}

async function renderStash() {
  const st = await api("/api/stash");
  const c = st.counts;
  let html = `<div class="paste">
      <input id="pasteUrl" placeholder="Paste a link…" onkeydown="if(event.key==='Enter')captureStash()">
      <button class="btn primary" onclick="captureStash()">Stash</button>
    </div>
    <p class="phead"><b>${c.filed} saved</b>${c.asking ? ` · <span class="r">${c.asking} need${c.asking === 1 ? "s" : ""} a word from you</span>` : ""} · ${c.tools} to try · ${c.tried} judged
      <button class="mini" style="margin-left:8px;" onclick="organizeStash(this)">Re-organize</button></p>`;

  if (st.asking.length) {
    html += label("Donna can't tell what these are", `${st.asking.length} waiting`);
    html += `<div class="stack">${st.asking.map(askCard).join("")}</div>`;
  }

  if (st.proposals.length) {
    html += label("Worth splitting?", `${st.proposals.length} proposed`);
    html += `<div class="stack">${st.proposals.map(splitCard).join("")}</div>`;
  }

  let any = false;
  for (const k of st.kinds) {
    if (!k.topics.length) continue;
    any = true;
    const n = k.topics.reduce((a, t) =>
      a + t.items.length + t.subs.reduce((b, s) => b + s.items.length, 0), 0);
    html += label(k.label, `${n} item${n === 1 ? "" : "s"}`);
    html += `<div class="kblurb">${esc(k.blurb)}</div>`;
    html += k.topics.map(topicBlock).join("");
  }

  if (!any && !st.asking.length) {
    html += `<div class="empty">Nothing stashed yet. Share a post to your Telegram
      Saved Messages and Donna will file it — she'll reply there telling you where it went.</div>`;
  }

  if (st.tried.length) {
    html += label("Already judged", `${st.tried.length}`);
    html += `<details class="handled"><summary>Things you've tried — so you never
      evaluate the same tool twice</summary><div class="body">` +
      st.tried.map((t) => `<div>${esc(t.title)} — ${esc(t.verdict || "no verdict")}</div>`).join("") +
      `</div></details>`;
  }

  $("sections").innerHTML = html;
}

async function captureStash() {
  const input = $("pasteUrl");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  $("reply").textContent = "Donna is reading it…";
  const res = await api("/api/stash/capture", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  $("reply").textContent = res.reply || "Stashed.";
  renderStash();
}

async function answerStash(id) {
  const note = $("ans" + id).value.trim();
  if (!note) return;
  $("reply").textContent = "Filing it…";
  const res = await api(`/api/stash/${id}/answer`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ note }),
  });
  $("reply").textContent = res.reply || "";
  renderStash();
}

// Whatever you typed doubles as the folder name, so "Meta ads" + tapping Inspo
// files it straight into an Inspo › Meta Ads folder.
async function setKind(id, kind) {
  const field = $("ans" + id);
  const topic = field ? field.value.trim() : "";
  await api(`/api/stash/${id}/kind`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind, topic }),
  });
  renderStash();
}

async function markTried(id) {
  const verdict = prompt("How was it? One line — 'good, using it' / 'meh'.");
  if (verdict === null) return;
  await api(`/api/stash/${id}/tried`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ verdict }),
  });
  renderStash();
}

async function archiveStash(id) { await api(`/api/stash/${id}/archive`, { method: "POST" }); renderStash(); }
async function acceptSplit(id) { await api(`/api/stash/proposals/${id}/accept`, { method: "POST" }); renderStash(); }
async function rejectSplit(id) { await api(`/api/stash/proposals/${id}/reject`, { method: "POST" }); renderStash(); }
async function organizeStash(el) {
  el.textContent = "Looking…";
  const res = await api("/api/stash/organize", { method: "POST" });
  $("reply").textContent = res.proposed
    ? `${res.proposed} split(s) to look at.` : "Nothing worth splitting yet.";
  renderStash();
}

Object.assign(window, { captureStash, answerStash, setKind, markTried, archiveStash,
                        acceptSplit, rejectSplit, organizeStash });

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
