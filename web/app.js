// Donna — Decision Mode. One decision at a time; everything else hidden.
const $ = (id) => document.getElementById(id);
const api = (path, opts) => fetch(path, opts).then((r) => r.json());
const esc = (s) => (s || "").replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const SRC = { gmail: "✉ Gmail", telegram: "✈ Telegram", calendar: "◷ Calendar", system: "•" };

let state = null, queue = [], i = 0;

$("theme").onclick = () => {
  const root = document.documentElement;
  const dark = matchMedia("(prefers-color-scheme: dark)").matches;
  const cur = root.getAttribute("data-theme") || (dark ? "dark" : "light");
  root.setAttribute("data-theme", cur === "dark" ? "light" : "dark");
};

async function load() {
  state = await api("/api/state");
  queue = state.needs_you;
  i = 0;
  $("greet").textContent = state.greeting;
  renderMore();
  render();
}

function render() {
  const left = queue.length - i;
  $("sub").innerHTML =
    `<b>${left} decision${left === 1 ? "" : "s"}</b> · I handled ${state.thesis.handled} others.`;

  const routine = queue.slice(i).filter((it) => it.draft).length;
  const batch = $("batch");
  if (routine > 1) {
    batch.hidden = false;
    batch.textContent = `⚡ Approve all ${routine} routine replies at once`;
    batch.onclick = approveAll;
  } else batch.hidden = true;

  if (i >= queue.length) {
    $("live").style.display = "none";
    $("doneScreen").classList.add("show");
    return;
  }
  $("progress").innerHTML = queue.map((_, n) =>
    `<div class="dot ${n < i ? "done" : n === i ? "on" : ""}"></div>`).join("");

  const it = queue[i];
  const d = it.draft;
  const pri = ["urgent", "high"].includes(it.priority);
  const yes = it.source === "calendar" ? "Do it" : "Approve & send";
  // Show Donna's actual reply on the card (editable inline), not just a summary.
  const replyBlock = d
    ? `<div class="reply"><span class="tag">Donna's reply — tweak it if you like</span>
         <textarea id="reply">${esc(d.body)}</textarea></div>`
    : `<div class="line act"><span class="k">Donna will</span><span class="v">${esc(it.reason || "Review this")}</span></div>`;
  const orig = it.body
    ? `<button class="details" onclick="this.nextElementSibling.classList.toggle('show')">See the original message</button><div class="full">${esc(it.body)}</div>`
    : "";

  $("cardslot").innerHTML = `<div class="card ${pri ? "urgent" : ""}">
    <div class="meta">
      ${pri ? `<span class="chip pri">● ${esc(it.priority)}</span>` : ""}
      <span class="chip src">${SRC[it.source] || ""}</span>
      <span class="who">${esc((it.sender || "").split("—")[0].trim())}</span>
      <span class="when">${esc(it.when || "")}</span>
    </div>
    <h2 class="subject">${esc(it.subject || "(no subject)")}</h2>
    <div class="line"><span class="k">What it's about</span><span class="v">${esc(it.snippet || "")}</span></div>
    ${replyBlock}
    ${orig}
    <div class="actions">
      <button class="btn primary" onclick="decide('approve')">${yes}</button>
      <button class="btn ghost" onclick="decide('skip')">Skip</button>
    </div>
    <div class="hint">← Skip · Approve →</div>
  </div>`;
  attachSwipe($("cardslot").querySelector(".card"));
  const ta = document.getElementById("reply");
  if (ta) {  // grow to fit the whole reply, and on edit
    const grow = () => { ta.style.height = "auto"; ta.style.height = ta.scrollHeight + "px"; };
    grow(); ta.addEventListener("input", grow);
  }
}

const firstSentence = (t) => (t || "").split(/(?<=[.!?])\s/)[0].slice(0, 120);

async function commit(action) {
  const it = queue[i], d = it.draft;
  if (action === "approve" && d) {
    const ta = document.getElementById("reply");           // save any inline edit first
    if (ta && ta.value !== d.body) {
      await api(`/api/drafts/${d.id}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ body: ta.value }) });
    }
    await api(`/api/drafts/${d.id}/approve`, { method: "POST" });
  }
  else if (action === "approve") await api(`/api/items/${it.id}/dismiss`, { method: "POST" });  // calendar "Do it"
  else if (action === "skip") await api(`/api/items/${it.id}/snooze`, { method: "POST" });      // back later
}

// Fly the card out in a direction, then commit + show the next one.
function finish(action, dir) {
  const card = $("cardslot").querySelector(".card");
  if (card) {
    card.style.transition = "transform .22s, opacity .22s";
    card.style.transform = `translateX(${dir * 540}px) rotate(${dir * 15}deg)`;
    card.style.opacity = "0";
  }
  setTimeout(async () => { await commit(action); i++; render(); }, 200);
}

function decide(action) {
  finish(action, action === "approve" ? 1 : -1);
}

// Drag-to-decide: right = approve, left = skip (back later).
function attachSwipe(card) {
  let startX = 0, dx = 0, dragging = false;
  const T = 90;
  card.style.touchAction = "pan-y";
  card.addEventListener("pointerdown", (e) => {
    if (e.target.closest("button, textarea, input, .details")) return;
    dragging = true; startX = e.clientX; dx = 0;
    card.setPointerCapture(e.pointerId);
    card.style.transition = "none";
  });
  card.addEventListener("pointermove", (e) => {
    if (!dragging) return;
    dx = e.clientX - startX;
    card.style.transform = `translateX(${dx}px) rotate(${dx / 30}deg)`;
    card.style.borderColor = dx > 40 ? "var(--good)" : dx < -40 ? "var(--brass)" : "var(--line)";
    const h = card.querySelector(".hint");
    if (h) h.textContent = dx > 40 ? "Approve ✓" : dx < -40 ? "Skip — back later ↩" : "← Skip · Approve →";
  });
  const end = () => {
    if (!dragging) return; dragging = false;
    if (dx > T) finish("approve", 1);
    else if (dx < -T) finish("skip", -1);
    else { card.style.transition = "transform .2s"; card.style.transform = ""; card.style.borderColor = ""; }
    dx = 0;
  };
  card.addEventListener("pointerup", end);
  card.addEventListener("pointercancel", end);
}

async function approveAll() {
  await api("/api/drafts/approve_all", { method: "POST" });
  await load();
  i = queue.length; render();
}

function renderMore() {
  const s = state;
  const oldest = s.followups.length ? Math.max(...s.followups.map((f) => f.age)) : 0;
  const open = s.tasks.filter((t) => !t.done).length;
  const today = s.today.map((e) => `${e.time} ${e.title.split(" ")[0]}`).slice(0, 4).join(" · ");
  $("moreBody").innerHTML = `
    <div class="row"><span>📌 From your people</span><span class="r">${s.vips.map((v) => v.name.split(" ")[0]).join(", ") || "—"}</span></div>
    <div class="row"><span>⏳ Waiting on a reply</span><span class="r">${s.followups.length} threads${oldest ? ` (oldest ${oldest}d)` : ""}</span></div>
    <div class="row"><span>📅 Today</span><span class="r">${today || "clear"}</span></div>
    <div class="row"><span>✅ To-do</span><span class="r">${open} open</span></div>
    <div class="row"><span>🗂 Handled for you</span><span class="r">${s.handled.length}</span></div>`;
}

$("send").onclick = sendCmd;
$("cmd").addEventListener("keydown", (e) => { if (e.key === "Enter") sendCmd(); });
async function sendCmd() {
  const input = $("cmd"), text = input.value.trim();
  if (!text) return;
  input.value = ""; $("reply").textContent = "Donna is thinking…";
  const res = await api("/api/command", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) });
  $("reply").textContent = res.reply || "";
}

// PWA: service worker + push
async function setupPush() {
  if (!("serviceWorker" in navigator)) return;
  const reg = await navigator.serviceWorker.register("/sw.js");
  const { key } = await api("/api/push/key");
  if (!key || Notification.permission === "denied") return;
  if ((await Notification.requestPermission()) !== "granted") return;
  const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64(key) });
  await api("/api/push/subscribe", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(sub) });
}
const b64 = (s) => { const p = "=".repeat((4 - (s.length % 4)) % 4); const r = atob((s + p).replace(/-/g, "+").replace(/_/g, "/")); return Uint8Array.from([...r].map((c) => c.charCodeAt(0))); };

window.decide = decide;
load();
setupPush();
