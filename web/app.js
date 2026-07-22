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
  const act = d ? d.summary || firstSentence(d.body) : (it.reason || "Review this");
  const full = (it.body ? `<span class="lbl">Full message</span>${esc(it.body)}` : "") +
    (d ? `<span class="lbl">Donna's exact reply — edit if you like</span>
          <textarea id="edit">${esc(d.body)}</textarea>` : "");

  $("cardslot").innerHTML = `<div class="card ${pri ? "urgent" : ""}">
    <div class="meta">
      ${pri ? `<span class="chip pri">● ${esc(it.priority)}</span>` : ""}
      <span class="chip src">${SRC[it.source] || ""}</span>
      <span class="who">${esc((it.sender || "").split("—")[0].trim())}</span>
      <span class="when">${esc(it.when || "")}</span>
    </div>
    <h2 class="subject">${esc(it.subject || "(no subject)")}</h2>
    <div class="line"><span class="k">What it's about</span><span class="v">${esc(it.snippet || "")}</span></div>
    <div class="line act"><span class="k">Donna will</span><span class="v">${esc(act)}</span></div>
    ${full ? `<button class="details" onclick="this.nextElementSibling.classList.toggle('show')">See full message &amp; exact wording</button><div class="full">${full}</div>` : ""}
    <div class="actions">
      <button class="btn primary" onclick="decide('approve')">${yes}</button>
      ${d ? `<button class="btn ghost" onclick="decide('edit')">Save edit</button>` : ""}
      <button class="btn ghost" onclick="decide('skip')">Skip</button>
    </div>
  </div>`;
}

const firstSentence = (t) => (t || "").split(/(?<=[.!?])\s/)[0].slice(0, 120);

async function decide(action) {
  const it = queue[i];
  const d = it.draft;
  if (action === "approve" && d) await api(`/api/drafts/${d.id}/approve`, { method: "POST" });
  else if (action === "approve") await api(`/api/items/${it.id}/dismiss`, { method: "POST" });
  else if (action === "skip") await api(`/api/items/${it.id}/dismiss`, { method: "POST" });
  else if (action === "edit" && d) {
    const body = $("edit").value;
    await api(`/api/drafts/${d.id}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ body }) });
    await api(`/api/drafts/${d.id}/approve`, { method: "POST" });
  }
  advance();
}

function advance() {
  const card = $("cardslot").querySelector(".card");
  if (card) { card.style.opacity = "0"; card.style.transform = "translateX(-24px)"; }
  setTimeout(() => { i++; render(); }, 170);
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
