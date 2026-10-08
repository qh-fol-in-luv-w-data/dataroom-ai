/* Data Room AI — single-page app (vanilla JS, no build). */
"use strict";

// ------------------------------------------------------------------ utils
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const store = {
  get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} },
  del(k) { try { localStorage.removeItem(k); } catch (e) {} },
};

const ICONS = {
  chat: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
  folder: '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>',
  shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
  grid: '<rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/>',
  play: '<polygon points="6 3 20 12 6 21 6 3"/>',
  list: '<line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/>',
  activity: '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>',
  logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/>',
  sun: '<circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/>',
  moon: '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>',
  user: '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
  users: '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>',
  plus: '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
  x: '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
  send: '<line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>',
  lock: '<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
  search: '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>',
  ext: '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/>',
  eye: '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>',
  menu: '<line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="18" x2="21" y2="18"/>',
  check: '<polyline points="20 6 9 17 4 12"/>',
  info: '<circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>',
  spark: '<path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/>',
  file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/>',
  globe: '<circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>',
  refresh: '<polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>',
  key: '<circle cx="7.5" cy="15.5" r="5.5"/><path d="M21 2l-9.6 9.6M15.5 7.5l3 3L22 7l-3-3"/>',
};
const icon = (n, cls = "") => `<svg class="i ${cls}" viewBox="0 0 24 24" aria-hidden="true">${ICONS[n] || ""}</svg>`;
const COLORS = ["#0e6b5c", "#3b5bdb", "#c4501b", "#6941c6", "#107c41", "#b42318", "#0e9384", "#2e5aac", "#9e3a8c", "#475467"];
const avatar = (name, size = 32) => {
  const ini = String(name || "?").trim().split(/\s+/).slice(-2).map((w) => w[0]).join("").toUpperCase();
  let h = 0; for (const ch of String(name)) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return `<span class="avatar" style="width:${size}px;height:${size}px;background:${COLORS[h % COLORS.length]}">${esc(ini)}</span>`;
};
const ftype = (ext) => `<span class="ftype ${esc(ext)}">${esc(ext)}</span>`;
const GROUP_LABEL = { "DR-INV-A": "Nhóm A", "DR-INV-B": "Nhóm B", "DR-INV-C": "Nhóm C", ADVISERS: "Cố vấn", STAFF: "Nhân viên", REVIEWERS: "Người duyệt" };
const SITE_LABEL = { COMMON: "Chung", "GRP-A": "Nhóm A", "GRP-B": "Nhóm B", "GRP-C": "Nhóm C", INTERNAL: "Nội bộ" };
const ROLE_LABEL = { "Investor.AI": "AI nhà đầu tư", "Investor.AI.Summarize": "Tổng hợp", "Staff.AI": "AI nhân viên", Reviewer: "Người duyệt", Admin: "Quản trị" };
const STATUS = {
  ai_ok: ["AI dùng được", "ok"], excluded: ["Không cho AI", "warn"], encrypted: ["Mã hóa", "bad"], malware: ["Mã độc", "bad"],
  pending: ["Đang nạp", "info"], unsupported: ["Không đọc được", ""], ai_blocked: ["AI đang chặn", "warn"],
};

function toast(msg, kind = "") {
  const t = document.createElement("div");
  t.className = "toast " + kind; t.textContent = msg;
  $("#toasts").appendChild(t);
  setTimeout(() => t.remove(), kind === "bad" ? 6000 : 4000);
}

function modal({ title, body, actions = [], wide = false }) {
  const ov = document.createElement("div");
  ov.className = "overlay";
  ov.innerHTML = `<div class="modal" role="dialog" aria-modal="true" aria-label="${esc(title)}" ${wide ? 'style="max-width:720px"' : ""}>
    <div class="card-h"><h3>${esc(title)}</h3><span style="flex:1"></span><button class="btn icon ghost" data-close aria-label="Đóng">${icon("x")}</button></div>
    <div class="card-b">${body}</div>
    ${actions.length ? `<div class="modal-f">${actions.map((a, i) => `<button class="btn ${a.primary ? "primary" : ""}" data-act="${i}">${esc(a.label)}</button>`).join("")}</div>` : ""}</div>`;
  const close = () => ov.remove();
  ov.addEventListener("click", (e) => { if (e.target === ov || e.target.closest("[data-close]")) close(); });
  document.addEventListener("keydown", function k(e) { if (e.key === "Escape") { close(); document.removeEventListener("keydown", k); } });
  actions.forEach((a, i) => ov.querySelector(`[data-act="${i}"]`).onclick = async () => { if ((await a.onClick?.(ov)) !== false) close(); });
  document.body.appendChild(ov);
  ov.querySelector("input,select,textarea,button:not([data-close])")?.focus();
  return ov;
}

function drawer(title, html) {
  $(".drawer")?.remove(); $(".drawer-ov")?.remove();
  const ov = document.createElement("div"); ov.className = "overlay drawer-ov"; ov.style.background = "rgba(16,24,40,.25)";
  const d = document.createElement("aside"); d.className = "drawer"; d.setAttribute("role", "dialog");
  d.innerHTML = `<div class="card-h"><h3>${esc(title)}</h3><span style="flex:1"></span><button class="btn icon ghost" aria-label="Đóng">${icon("x")}</button></div><div class="card-b"></div>`;
  const close = () => { d.remove(); ov.remove(); };
  ov.onclick = close; d.querySelector(".card-h button").onclick = close;
  document.body.append(ov, d);
  d.querySelector(".card-b").innerHTML = html;
  return d.querySelector(".card-b");
}

// ------------------------------------------------------------------ api + session
let TOKEN = store.get("dr-token");
let ME = null;
let STATUS_CACHE = null;

// Sign-in mode: "demo" (password) or "m365" (Entra ID via MSAL, token for the AI API)
let AUTH = { mode: "demo" }, MSAL = null;
const loadScript = (src) => new Promise((ok, bad) => {
  const s = document.createElement("script"); s.src = src; s.onload = ok; s.onerror = bad; document.head.appendChild(s);
});
async function initAuth() {
  try { AUTH = await (await fetch("/api/auth/config")).json(); } catch { AUTH = { mode: "demo" }; }
  if (AUTH.mode !== "m365") return;
  await loadScript("https://cdn.jsdelivr.net/npm/@azure/msal-browser@3.28.1/lib/msal-browser.min.js");
  MSAL = new msal.PublicClientApplication({
    auth: { clientId: AUTH.client_id, authority: AUTH.authority, redirectUri: location.origin + "/" },
    cache: { cacheLocation: "sessionStorage" },
  });
  await MSAL.initialize();
  const res = await MSAL.handleRedirectPromise();
  const acc = (res && res.account) || MSAL.getAllAccounts()[0];
  if (acc) MSAL.setActiveAccount(acc);
}
async function msalToken() {
  const account = MSAL.getActiveAccount();
  if (!account) return null;
  try { return (await MSAL.acquireTokenSilent({ scopes: [AUTH.scope], account })).accessToken; }
  catch { await MSAL.acquireTokenRedirect({ scopes: [AUTH.scope], account }); return null; }
}

async function api(path, opts = {}) {
  if (MSAL && !path.startsWith("/api/auth/")) TOKEN = await msalToken();
  const r = await fetch(path, {
    ...opts,
    headers: { "Content-Type": "application/json", ...(TOKEN ? { Authorization: "Bearer " + TOKEN } : {}), ...(opts.headers || {}) },
    body: opts.body && typeof opts.body !== "string" ? JSON.stringify(opts.body) : opts.body,
  });
  const ct = r.headers.get("content-type") || "";
  const data = ct.includes("json") ? await r.json() : await r.text();
  if (r.status === 401 && !path.startsWith("/api/auth/")) { logout("Phiên đăng nhập đã hết hạn, vui lòng đăng nhập lại."); throw new Error("401"); }
  if (!r.ok) throw new Error((data && data.detail) || r.statusText);
  return data;
}
const post = (path, body) => api(path, { method: "POST", body });

// POST that answers with one JSON object per line (progress events, then {result} or {error}).
async function postStream(path, body, onEvent) {
  if (MSAL) TOKEN = await msalToken();
  const r = await fetch(path, { method: "POST", body: JSON.stringify(body),
    headers: { "Content-Type": "application/json", ...(TOKEN ? { Authorization: "Bearer " + TOKEN } : {}) } });
  if (!r.ok) {
    const data = (r.headers.get("content-type") || "").includes("json") ? await r.json() : {};
    if (r.status === 401) { logout("Phiên đăng nhập đã hết hạn, vui lòng đăng nhập lại."); throw new Error("401"); }
    throw new Error(data.detail || r.statusText);
  }
  const reader = r.body.getReader(), dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, i); buf = buf.slice(i + 1);
      if (!line.trim()) continue;
      const ev = JSON.parse(line);
      if (ev.result) return ev.result;
      if (ev.error) throw new Error(ev.error);
      onEvent(ev);
    }
  }
  throw new Error("Mất kết nối trước khi có kết quả");
}

function logout(msg) {
  if (MSAL && MSAL.getActiveAccount()) { MSAL.logoutRedirect({ postLogoutRedirectUri: location.origin + "/" }); return; }
  TOKEN = null; ME = null; store.del("dr-token");
  CHAT.length = 0;
  location.hash = "";
  renderLogin(msg);
}

// ------------------------------------------------------------------ login
async function renderLogin(message) {
  document.title = "Đăng nhập · Data Room AI";
  if (AUTH.mode === "m365") return renderLoginMicrosoft(message);
  $("#app").innerHTML = `
  <div class="login">
    <section class="login-art" aria-hidden="true">
      <div class="login-logo"><span class="logo-mark">SM</span> Data Room AI</div>
      <div>
        <h1>Trợ lý AI cho Data Room IPO, đúng quyền của từng nhà đầu tư.</h1>
        <p class="lead">CTCP Năng lượng Sao Mai · đợt chào bán lần đầu 2026</p>
        <div class="login-points">
          <div>${icon("shield")}<span><b>4 cổng phân quyền</b>RLS, hỏi lại SharePoint, tập thu hồi, kiểm danh tính — sai ở đâu cũng đóng an toàn.</span></div>
          <div>${icon("spark")}<span><b>Trả lời có trích dẫn nguyên văn</b>Mọi ý được kiểm chứng với tài liệu gốc trước khi hiển thị.</span></div>
          <div>${icon("lock")}<span><b>Chạy hoàn toàn on-prem</b>Model, OCR và dữ liệu ở trên máy này; không gửi ra ngoài.</span></div>
        </div>
      </div>
      <div class="login-foot">Bản demo · dữ liệu giả lập · không dùng cho giao dịch thật</div>
    </section>
    <section class="login-panel">
      <div class="login-card">
        <h2>Đăng nhập</h2>
        <div class="muted">Dùng tài khoản được mời vào Data Room (Entra ID giả lập).</div>
        <form id="login-form" novalidate>
          ${message ? `<div class="alert info">${esc(message)}</div>` : ""}
          <div class="alert bad hidden" id="login-err" role="alert"></div>
          <label class="field">Email<input class="input" id="email" type="email" autocomplete="username" required placeholder="ten@congty.com"></label>
          <label class="field">Mật khẩu
            <span class="pw-wrap"><input class="input" id="password" type="password" autocomplete="current-password" required>
            <button type="button" class="btn ghost sm" id="pw-toggle" aria-label="Hiện mật khẩu">${icon("eye")}</button></span></label>
          <button class="btn primary" id="login-btn" type="submit" style="height:40px">Đăng nhập</button>
        </form>
        <details class="demo-acc">
          <summary>Tài khoản demo</summary>
          <p class="small muted" style="margin:8px 0 0">Bấm để điền email. Mật khẩu demo nằm trong file <span class="mono">data/tenant/DEMO_ACCOUNTS.md</span>.</p>
          <div class="demo-list" id="demo-list"><div class="muted small">Đang tải…</div></div>
        </details>
      </div>
    </section>
  </div>`;
  $("#pw-toggle").onclick = () => { const p = $("#password"); p.type = p.type === "password" ? "text" : "password"; };
  $("#login-form").onsubmit = async (e) => {
    e.preventDefault();
    const btn = $("#login-btn"), err = $("#login-err");
    err.classList.add("hidden"); btn.disabled = true; btn.textContent = "Đang đăng nhập…";
    try {
      const r = await post("/api/auth/login", { email: $("#email").value, password: $("#password").value });
      TOKEN = r.token; store.set("dr-token", TOKEN);
      await boot();
    } catch (ex) {
      err.textContent = ex.message; err.classList.remove("hidden");
      btn.disabled = false; btn.textContent = "Đăng nhập";
    }
  };
  try {
    const accs = await api("/api/auth/demo-accounts");
    $("#demo-list").innerHTML = accs.map((a) => `<button type="button" data-email="${esc(a.email)}">${avatar(a.name, 28)}
      <span class="who"><b>${esc(a.name)}</b><small>${esc(a.org)} · ${a.type === "admin" ? "Quản trị" : a.groups.map((g) => GROUP_LABEL[g] || g).join(", ") || "—"}${a.enabled === false ? " · đã tắt" : ""}</small></span></button>`).join("");
    $$("#demo-list button").forEach((b) => b.onclick = () => { $("#email").value = b.dataset.email; $("#password").focus(); });
  } catch { $("#demo-list").innerHTML = '<div class="muted small">Không tải được danh sách.</div>'; }
  $("#email").focus();
}

function renderLoginMicrosoft(message) {
  $("#app").innerHTML = `
  <div class="login">
    <section class="login-art" aria-hidden="true">
      <div class="login-logo"><span class="logo-mark">SM</span> Data Room AI</div>
      <div><h1>Trợ lý AI cho Data Room IPO, đúng quyền của từng nhà đầu tư.</h1>
        <p class="lead">Đăng nhập bằng tài khoản được mời vào Data Room trên SharePoint.</p></div>
      <div class="login-foot">Quyền truy cập do SharePoint và Entra ID quyết định</div>
    </section>
    <section class="login-panel"><div class="login-card">
      <h2>Đăng nhập</h2>
      <div class="muted">Dùng tài khoản Microsoft (Entra ID) mà Ban IPO đã mời. Có thể được yêu cầu xác thực đa yếu tố.</div>
      ${message ? `<div class="alert info" style="margin-top:16px">${esc(message)}</div>` : ""}
      <button class="btn primary" id="ms-login" style="height:42px;width:100%;margin-top:20px">${icon("lock")} Đăng nhập bằng tài khoản Microsoft</button>
    </div></section>
  </div>`;
  $("#ms-login").onclick = () => MSAL.loginRedirect({ scopes: [AUTH.scope] });
}

// ------------------------------------------------------------------ shell + router
const NAV = [
  { sec: "Trợ lý", items: [
    { id: "chat", label: "Hỏi đáp", icon: "chat", who: "user" },
  ] },
  { sec: "Quản trị Data Room", items: [
    { id: "perms", label: "Phân quyền", icon: "key", who: "admin" },
    { id: "matrix", label: "Ma trận quyền", icon: "grid", who: "admin" },
    { id: "scope", label: "Phạm vi truy xuất", icon: "folder", who: "admin" },
    { id: "scenarios", label: "Kịch bản demo", icon: "play", who: "admin" },
    { id: "audit", label: "Nhật ký", icon: "list", who: "admin" },
    { id: "system", label: "Hệ thống", icon: "activity", who: "admin" },
  ] },
];
const TITLES = {
  chat: ["Hỏi đáp", "Chỉ dùng tài liệu bạn được mở trên SharePoint và được phép dùng AI"],
  search: ["Tìm hồ sơ", "Tìm theo từ khóa, nội dung hoặc ý nghĩa — chỉ trong phạm vi của bạn"],
  drafts: ["Câu hỏi chờ duyệt", "Câu hỏi thuộc chủ đề nhạy cảm được Ban IPO xem xét trước khi trả lời"],
  review: ["Duyệt câu trả lời", "Bản nháp cho câu hỏi nhạy cảm — chỉ xem được khi bạn có quyền trên mọi nguồn"],
  scope: ["Phạm vi truy xuất", "Chọn một người dùng để xem AI truy xuất được đến đâu cho người đó"],
  perms: ["Phân quyền", "Người dùng, nhóm, thư mục, tài liệu — nguồn sự thật là SharePoint/Entra"],
  matrix: ["Ma trận quyền", "Mỗi người × mỗi site: AI dùng được / SharePoint cho mở"],
  scenarios: ["Kịch bản demo", "Tái hiện các tình huống thu hồi quyền trong kế hoạch"],
  audit: ["Nhật ký", "Chuỗi hash chống sửa"],
  system: ["Hệ thống", "Nguồn đồng bộ, model, chỉ mục"],
};

const isAdmin = () => ME && ME.type === "admin";
const roleLabel = () => isAdmin() ? "Quản trị Data Room"
  : (ME.roles || []).includes("Staff.AI") ? (ME.type === "guest" ? "Cố vấn" : "Nhân viên")
  : ME.type === "guest" ? "Nhà đầu tư" : "Người dùng";
function updateRecent() {
  const el = $("#sb-recent"); if (!el) return;
  const items = CHAT.map((m, i) => [m, i]).reverse().slice(0, 12);
  el.innerHTML = items.length ? items.map(([m, i]) => `<button data-i="${i}" title="${esc(m.q)}">${icon("chat")}<span>${esc(m.q)}</span></button>`).join("")
    : '<div class="sb-empty">Chưa có câu hỏi nào trong phiên này</div>';
  $$("button", el).forEach((b) => b.onclick = () => {
    if (!location.hash.startsWith("#/chat")) location.hash = "#/chat";
    setTimeout(() => { const t = $("#q-" + b.dataset.i); if (t) { t.scrollIntoView({ behavior: "smooth", block: "start" }); } $("#sidebar").classList.remove("open"); }, 60);
  });
}
const visibleNav = (i) => i.who === "admin" ? isAdmin()
  : i.who === "reviewer" ? !isAdmin() && (ME.roles || []).includes("Reviewer") : !isAdmin();

function renderShell() {
  $("#app").innerHTML = `
  <div class="shell">
    <aside class="sidebar" id="sidebar">
      <div class="sb-brand"><span class="sb-logo">SM</span><div><b>Data Room AI</b><small>Sao Mai · IPO 2026</small></div></div>
      ${isAdmin() ? "" : `<button class="sb-new" id="new-chat">${icon("plus")}<span>Cuộc hỏi mới</span></button>`}
      <nav class="sb-nav" aria-label="Điều hướng">${NAV.map((s) => {
        const items = s.items.filter(visibleNav);
        return items.length ? (isAdmin() ? `<div class="sb-sec">${s.sec}</div>` : "") + items.map((i) =>
          `<a href="#/${i.id}" data-id="${i.id}"><span class="sb-ico">${icon(i.icon)}</span><span>${i.label}</span></a>`).join("") : "";
      }).join("")}
        ${isAdmin() ? "" : '<div class="sb-sec">Câu đã hỏi</div><div class="sb-recent" id="sb-recent"></div>'}</nav>
      <div class="sb-user">${avatar(ME.name, 36)}<div class="who"><b>${esc(ME.name)}</b><small>${esc(roleLabel())}</small></div>
        <button class="btn icon" id="logout" title="Đăng xuất" aria-label="Đăng xuất">${icon("logout")}</button></div>
    </aside>
    <div class="main">
      <header class="topbar">
        <button class="btn icon ghost menu-btn" id="menu" aria-label="Mở menu">${icon("menu")}</button>
        <div><h1 id="page-title"></h1><div class="sub" id="page-sub"></div></div>
        <span class="spacer"></span>
        <div class="pills" id="pills"></div>
        <button class="btn icon ghost" id="theme" aria-label="Đổi giao diện sáng/tối">${icon(document.documentElement.dataset.theme === "dark" ? "sun" : "moon")}</button>
      </header>
      <main id="page"></main>
    </div>
  </div>`;
  $("#logout").onclick = () => logout();
  const nc = $("#new-chat");
  if (nc) nc.onclick = () => { if (CHAT.some((m) => !m.r)) return; CHAT.length = 0; location.hash = "#/chat"; renderThread(); updateRecent(); $("#q")?.focus(); };
  updateRecent();
  $("#menu").onclick = () => $("#sidebar").classList.toggle("open");
  $("#theme").onclick = () => {
    const t = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = t; store.set("dr-theme", t);
    $("#theme").innerHTML = icon(t === "dark" ? "sun" : "moon");
  };
}

function route() {
  if (!ME) return;
  const def = isAdmin() ? "perms" : "chat";
  let id = (location.hash.replace(/^#\/?/, "") || def).split("?")[0];
  const allowed = NAV.flatMap((s) => s.items).filter(visibleNav).map((i) => i.id);
  if (!allowed.includes(id)) { id = def; history.replaceState(null, "", "#/" + id); }
  $$(".sb-nav a").forEach((a) => a.classList.toggle("active", a.dataset.id === id));
  $("#sidebar").classList.remove("open");
  const [t, sub] = TITLES[id];
  $("#page-title").textContent = t; $("#page-sub").textContent = sub;
  document.title = `${t} · Data Room AI`;
  const page = $("#page");
  page.className = id === "chat" ? "" : "page";
  ({ chat: pageChat, search: pageSearch, drafts: pageDrafts, review: pageReview, scope: pageScope, perms: pagePerms, matrix: pageMatrix, scenarios: pageScenarios, audit: pageAudit, system: pageSystem })[id](page);
}
window.addEventListener("hashchange", route);

async function boot() {
  try { ME = await api("/api/me"); } catch { return renderLogin(); }
  renderShell();
  route();
  pollStatus();
}

// ------------------------------------------------------------------ status pills
async function pollStatus() {
  if (!TOKEN || !ME || !isAdmin()) return;
  try { STATUS_CACHE = await api("/api/status"); } catch { return; }
  const s = STATUS_CACHE, age = (k) => s.feeds[k] ?? 1e9;
  const p = (txt, cls, title = "") => `<span class="chip ${cls}" title="${esc(title)}">${txt}</span>`;
  const el = $("#pills");
  if (el) el.innerHTML = [
    p(`Entra ${age("entra") > 1e8 ? "—" : Math.round(age("entra")) + "s"}`, age("entra") > s.feed_max_age ? "bad" : "ok", "Độ tươi nguồn Entra"),
    p(`SharePoint ${age("drive") > 1e8 ? "—" : Math.round(age("drive")) + "s"}`, age("drive") > s.feed_max_age ? "bad" : "ok", "Độ tươi nguồn SharePoint"),
    p(s.models_ready ? "Model sẵn sàng" : "Đang nạp model…", s.models_ready ? "ok" : "warn"),
    s.ingest_busy ? p("Đang nạp tài liệu…", "info") : "",
  ].join("");
  if (location.hash.includes("scenarios")) renderLive();
}
setInterval(pollStatus, 3000);

// ------------------------------------------------------------------ chat
const CHAT = [];
const SUGGEST = [   // [label, question, group needed (null = everyone), staff only]
  ["Tài chính", "Doanh thu thuần năm 2025 của Sao Mai là bao nhiêu?", null],
  ["Nhà máy", "Tổng công suất lắp đặt các nhà máy là bao nhiêu MW?", null],
  ["Đợt IPO", "Đợt IPO chào bán bao nhiêu cổ phần?", null],
  ["Thỏa thuận", "Phí thu xếp áp dụng cho nhóm quỹ trong nước là bao nhiêu?", "DR-INV-A"],
  ["Thỏa thuận", "Tỷ lệ room ngoại dành riêng cho Nhóm B là bao nhiêu?", "DR-INV-B"],
  ["Thỏa thuận", "Nhà đầu tư chiến lược được đề cử bao nhiêu thành viên HĐQT?", "DR-INV-C"],
  ["Nội bộ", "Khoản dự phòng tranh chấp với nhà thầu là bao nhiêu?", null, true],
  ["Bản scan", "Biên bản xác nhận công suất lắp đặt các nhà máy ghi gì?", null],
  ["English", "What was Sao Mai's net revenue in 2025?", null],
];
const mySuggestions = () => {
  const staff = (ME.roles || []).includes("Staff.AI");
  return SUGGEST.filter(([, , grp, staffOnly]) => staff ? true : !staffOnly && (!grp || (ME.groups || []).includes(grp)));
};
const THINK = ["Kiểm tra danh tính, vai trò và độ tươi nguồn quyền", "Lọc tài liệu theo quyền và kiểm tra an toàn câu hỏi",
  "Tìm kiếm lai và xếp hạng lại", "Hỏi lại SharePoint bằng danh tính của bạn", "Model local đọc tài liệu và chọn câu trả lời",
  "Kiểm chứng trích dẫn, con số và quyền lần cuối"];
// server progress → number of finished rows above (step names come from dr/core/answer.py)
const STEP_DONE = [["Cổng 4", 1], ["Cổng 1+3", 2], ["Lớp đầu vào", 2], ["Tìm kiếm", 2], ["Rerank", 3],
  ["Cổng 2 – kiểm tra trực tiếp", 4], ["LLM", 5], ["Thử lại", 5], ["Kiểm chứng", 5]];
function onProgress(m, ev) {
  if (ev.stage === "queue") m.queued = true;
  if (ev.step) {
    m.queued = false;
    const hit = STEP_DONE.find(([p]) => ev.step.startsWith(p));
    if (hit && hit[1] > m.done) { for (let k = m.done; k < hit[1]; k++) m.ms[k] = Date.now() - m.t0; m.done = hit[1]; }
  }
  const el = $("#ans-" + CHAT.indexOf(m)); if (el && !m.r) el.innerHTML = renderThinking(m);
}

function pageChat(page) {
  const canAI = ME.roles.some((r) => r === "Investor.AI" || r === "Staff.AI");
  page.innerHTML = `
  <div class="chat">
    <div class="thread" id="thread"><div class="thread-inner" id="thread-inner"></div></div>
    <div class="composer"><div class="composer-inner">
      <form class="composer-box" id="ask">
        <label class="sr-only" for="q">Câu hỏi</label>
        <textarea id="q" rows="1" placeholder="${canAI ? "Hỏi về tài liệu trong Data Room… (Enter để gửi, Shift+Enter xuống dòng)" : "Tài khoản của bạn chưa được cấp quyền dùng trợ lý AI"}" ${canAI ? "" : "disabled"}></textarea>
        <button class="btn primary icon" id="send" type="submit" aria-label="Gửi" ${canAI ? "" : "disabled"}>${icon("send")}</button>
      </form>
      <div class="composer-meta">
        ${ME.roles.includes("Staff.AI") ? `<label>Phạm vi <select id="scope-site"><option value="">Mọi site được phép</option>${(ME.sites || []).map((s) => `<option value="${s.id}">${esc(s.name)}</option>`).join("")}</select></label>` : ""}
        <span>${icon("shield")} Câu trả lời chỉ hiển thị sau khi qua đủ 4 cổng quyền và bước kiểm chứng.</span>
      </div>
    </div></div>
  </div>`;
  renderThread();
  const q = $("#q");
  q.addEventListener("input", () => { q.style.height = "auto"; q.style.height = Math.min(q.scrollHeight, 160) + "px"; });
  q.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#ask").requestSubmit(); } });
  $("#ask").onsubmit = (e) => { e.preventDefault(); ask(q.value.trim()); };
  if (canAI) q.focus();
}

function renderThread() {
  const inner = $("#thread-inner");
  if (!inner) return;
  if (!CHAT.length) {
    inner.innerHTML = `<div class="hero">
      <h2>Xin chào, ${esc(ME.name.split(" ").slice(-1)[0])}</h2>
      <p>Hỏi bằng tiếng Việt (có dấu hoặc không dấu) hoặc tiếng Anh. Mỗi câu trả lời đều kèm trích dẫn nguyên văn và link tới tài liệu gốc trên SharePoint.</p>
      ${ME.roles.some((r) => r.endsWith(".AI")) ? "" : '<div class="scope-strip"><span class="chip bad">Tài khoản chưa được cấp quyền dùng trợ lý AI</span></div>'}
      <div class="suggest">${mySuggestions().map(([tag, s]) => `<button type="button" data-q="${esc(s)}"><small>${tag}</small>${esc(s)}</button>`).join("")}</div>
    </div>`;
    $$(".suggest button", inner).forEach((b) => b.onclick = () => ask(b.dataset.q));
    return;
  }
  updateRecent();
  inner.innerHTML = CHAT.map((m, i) => `<div class="q-bubble" id="q-${i}">${esc(m.q)}</div><div class="a-card" id="ans-${i}">${m.r ? renderAnswer(m.r, i) : renderThinking(m)}</div>`).join("");
  CHAT.forEach((m, i) => { if (m.r) wireAnswer($("#ans-" + i), i); });
  const th = $("#thread"); th.scrollTop = th.scrollHeight;
}

const secs = (ms) => (ms / 1000).toFixed(1).replace(".", ",") + " s";
function renderThinking(m) {
  const step = m.done || 0, now = Date.now() - (m.t0 || Date.now());
  return `<div class="a-head"><span class="dot">${icon("spark")}</span> ${m.queued ? "Đang chờ lượt xử lý" : "Đang xử lý"}
      <span class="muted small" style="margin-left:auto" data-elapsed>${secs(now)}</span></div>
    <div class="thinking">${THINK.map((t, i) =>
    `<div class="row" style="opacity:${i <= step ? 1 : .35}">${i < step ? `<span class="chip ok" style="padding:0 5px">${icon("check")}</span>` : i === step ? '<span class="spinner"></span>' : '<span style="width:14px"></span>'} ${t}${i < step && m.ms ? ` <span class="muted small">${secs(m.ms[i])}</span>` : ""}</div>`).join("")}</div>`;
}

function renderAnswer(r, i) {
  const chips = [
    r.approved ? `<span class="chip ok" title="Câu hỏi nhạy cảm — đã qua người duyệt">${icon("check")} Ban IPO đã duyệt${r.edited ? " · có hiệu đính" : ""}</span>` : "",
    r.mode === "quote" ? '<span class="chip" title="Tài khoản chưa có quyền tổng hợp: chỉ trả câu trích nguyên văn">Chế độ tra cứu</span>' : "",
    r.lang === "en" ? '<span class="chip info">EN</span>' : "",
    r.withdrawn ? `<span class="chip warn" title="Quyền của bạn đã thay đổi sau khi duyệt">${r.withdrawn} ý đã rút lại</span>` : "",
  ].join("");
  const fb = r.audit_seq && !r.refused && !r.pending_review && !r.approved ? `<span class="fb">
      <button class="btn icon ghost sm" data-fb="up" title="Câu trả lời đúng" aria-label="Đúng">👍</button>
      <button class="btn icon ghost sm" data-fb="down" title="Câu trả lời sai" aria-label="Sai">👎</button></span>` : "";
  const head = `<div class="a-head"><span class="dot">${icon("spark")}</span> Trợ lý · ${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}${r.elapsed_ms ? ` · ${secs(r.elapsed_ms)}` : ""}${r.audit_seq ? ` · nhật ký #${r.audit_seq}` : ""} ${chips}<span style="flex:1"></span>${fb}</div>`;
  const trace = `<details class="trace"><summary>${icon("shield")} Chi tiết 4 cổng quyền và các bước (${(r.trace || []).length})</summary><ol class="steps">${(r.trace || []).map((s) => {
    const { step, ok, ms, ...rest } = s;
    const d = Object.entries(rest).filter(([, v]) => v !== null && v !== "" && !(Array.isArray(v) && !v.length)).map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`).join(" · ");
    return `<li><span class="s-dot ${ok ? "" : "bad"}">${ok ? "✓" : "✕"}</span><span>${esc(step)}</span><span class="muted small">${ms} ms</span>${d ? `<span class="s-d">${esc(d)}</span>` : ""}</li>`;
  }).join("")}</ol></details>`;
  if (r.sensitive) return `${head}<div class="sensitive">${icon("users")}<div><b>${esc(r.message)}</b></div></div>`;
  if (r.out_of_scope) return `${head}<div class="sensitive scope">${icon("lock")}<div><b>${esc(r.message)}</b></div></div>`;
  if (r.refused) return `${head}<div class="refused">${icon("info")}<div>${esc(r.message)}</div></div>${trace}`;
  if (r.pending_review) return `${head}<div class="pending"><span class="spinner"></span><div><b>${esc(r.message)}</b>
      <div class="chips" style="margin-top:6px">${(r.topics || []).map((t) => `<span class="chip warn">${esc(t)}</span>`).join("")}</div>
      <div class="muted small">Mã bản nháp #${r.draft_id} · trang này tự cập nhật khi có kết quả duyệt</div></div></div>${trace}`;
  const claims = `<ol class="claims">${r.claims.map((c) => `<li>${esc(c.text)}${c.refs.map((n) => `<button class="ref" data-n="${n}" aria-label="Xem trích dẫn ${n}">${n}</button>`).join("")}
    ${(c.ocr_doubt || []).length ? `<span class="chip warn" title="Bộ đọc OCR thứ hai không đọc ra đúng con số này — hãy đối chiếu ảnh gốc bên dưới">số từ bản scan chưa xác nhận: ${esc(c.ocr_doubt.join(", "))}</span>`
      : c.uncertain ? `<span class="chip warn" title="Điểm NLI thấp">chưa chắc</span>` : ""}</li>`).join("")}</ol>`;
  const cites = `<div class="cites">${r.citations.map((c) => `<div class="cite" id="cite-${i}-${c.n}">
      <div class="cite-top"><span class="cite-n">${c.n}</span>${ftype((c.name.split(".").pop() || "").toLowerCase())}<span class="cite-name" title="${esc(c.name)}">${esc(c.name)}</span></div>
      <div class="cite-loc">${esc(c.locator)}</div>
      <blockquote>${esc(c.quote)}</blockquote>
      ${c.crop ? `<figure class="crop"><img loading="lazy" alt="Vùng tương ứng trên bản scan gốc" src="/crop/${encodeURIComponent(c.item_id)}?t=${encodeURIComponent(TOKEN)}&page=${encodeURIComponent(c.crop.page)}${c.crop.box ? "&box=" + c.crop.box.join(",") : ""}"><figcaption>${c.crop.box ? "Vùng gốc trên bản scan (đã nắn thẳng)" : "Trang scan gốc (đã nắn thẳng)"}</figcaption></figure>` : ""}
      <div class="cite-foot"><span class="chip">${esc(SITE_LABEL[c.site_id] || c.site_id)}</span>${c.ocr ? '<span class="chip info" title="PaddleOCR-VL">văn bản nhận dạng từ bản scan</span>' : ""}
        <span style="flex:1"></span><a href="${c.web_url ? esc(c.web_url) : `/open/${encodeURIComponent(c.item_id)}?t=${encodeURIComponent(TOKEN)}`}" target="_blank" rel="noopener" title="Mở thẳng file (cần đăng nhập SharePoint)">${icon("file")} Mở file ${icon("ext")}</a></div>
      ${c.public ? `<div class="cite-public">${icon("globe")} <a href="${esc(c.public.url)}" target="_blank" rel="noopener" title="Link công khai chỉ xem, không cần đăng nhập">Link public thư mục ${esc(c.public.folder)}</a>
        <span class="muted"> › ${esc(c.public.path.replace(/\//g, " › "))}</span>
        <button class="btn ghost sm" data-copy="${esc(c.public.url)}" title="Sao chép link public">Sao chép</button></div>` : ""}
    </div>`).join("")}</div>`;
  return head + claims + cites + trace;
}

function wireAnswer(el, i) {
  $$("[data-fb]", el).forEach((b) => b.onclick = async () => {
    const m = CHAT[i]; if (!m || !m.r || m.fb) return;
    const note = b.dataset.fb === "down" ? (prompt("Câu trả lời sai ở đâu? (không bắt buộc)") || "") : "";
    try { await post("/api/feedback", { audit_seq: m.r.audit_seq, rating: b.dataset.fb, note }); m.fb = b.dataset.fb;
      $$("[data-fb]", el).forEach((x) => x.classList.toggle("on", x.dataset.fb === m.fb)); toast("Cảm ơn phản hồi của bạn"); }
    catch (e) { toast(e.message, "bad"); }
  });
  $$("[data-copy]", el).forEach((b) => b.onclick = async () => {
    try { await navigator.clipboard.writeText(b.dataset.copy); toast("Đã sao chép link public"); }
    catch { toast("Không sao chép được, hãy bấm chuột phải vào link", "bad"); }
  });
  $$(".crop img", el).forEach((im) => {
    im.onclick = () => im.parentElement.classList.toggle("big");
    im.onerror = () => im.parentElement.remove();   // no permission or page gone: hide quietly
  });
  $$(".ref", el).forEach((b) => b.onclick = () => {
    const c = $(`#cite-${i}-${b.dataset.n}`); if (!c) return;
    c.scrollIntoView({ behavior: "smooth", block: "center" }); c.classList.add("flash"); setTimeout(() => c.classList.remove("flash"), 1400);
  });
}

async function ask(q) {
  if (!q || CHAT.some((m) => !m.r)) return;
  const m = { q, done: 0, ms: [], t0: Date.now() }; CHAT.push(m);
  const input = $("#q"); if (input) { input.value = ""; input.style.height = "auto"; }
  renderThread();
  const timer = setInterval(() => {      // elapsed-time counter only; the steps come from the server
    const e = $(`#ans-${CHAT.indexOf(m)} [data-elapsed]`); if (e && !m.r) e.textContent = secs(Date.now() - m.t0);
  }, 100);
  try {
    m.r = await postStream("/api/chat/stream", { question: q, scope_site: $("#scope-site")?.value || null },
                           (ev) => onProgress(m, ev));
    m.r.elapsed_ms = Date.now() - m.t0;
    if (m.r.pending_review) watchDrafts();
  } catch (e) {
    m.r = { refused: true, message: "Lỗi: " + e.message, trace: [] };
  } finally { clearInterval(timer); renderThread(); }
}

// ------------------------------------------------------------------ sensitive-question drafts (asker)
let DRAFT_TIMER = null;
function draftToAnswer(d) {
  if (d.status === "approved") return { ...d.answer, approved: true, edited: d.edited };
  if (d.status === "rejected") return { refused: true, trace: [], message: "Ban IPO không phát hành câu trả lời cho câu hỏi này."
    + (d.note ? " Ghi chú: " + d.note : "") };
  return null;
}
function watchDrafts() {
  if (DRAFT_TIMER) return;
  DRAFT_TIMER = setInterval(async () => {
    const waiting = CHAT.filter((m) => m.r && m.r.pending_review);
    if (!waiting.length || !ME) { clearInterval(DRAFT_TIMER); DRAFT_TIMER = null; return; }
    let mine; try { mine = await api("/api/my/drafts"); } catch { return; }
    let changed = false;
    for (const m of waiting) {
      const d = mine.find((x) => x.draft_id === m.r.draft_id);
      const a = d && draftToAnswer(d);
      if (a) { m.r = a; changed = true; toast("Câu hỏi của bạn đã có kết quả duyệt"); }
    }
    if (changed && location.hash.startsWith("#/chat")) renderThread();
  }, 8000);
}

async function pageDrafts(page) {
  page.innerHTML = '<div class="card empty">Đang tải…</div>';
  const mine = await api("/api/my/drafts");
  if (!mine.length) { page.innerHTML = '<div class="card empty">Bạn chưa có câu hỏi nào cần duyệt.</div>'; return; }
  const ST = { pending: ["Đang chờ duyệt", "warn"], approved: ["Đã duyệt", "ok"], rejected: ["Không phát hành", "bad"] };
  page.innerHTML = mine.map((d, k) => `<div class="card" style="margin-bottom:14px"><div class="card-h">
      <span class="chip ${ST[d.status][1]}">${ST[d.status][0]}</span><h3 style="flex:1">${esc(d.question)}</h3>
      <span class="muted small">#${d.draft_id} · ${new Date(d.created_at).toLocaleString()}</span></div>
      <div class="card-b"><div class="chips">${d.topics.map((t) => `<span class="chip">${esc(t)}</span>`).join("")}</div>
      ${d.status === "pending" ? '<p class="muted">Ban IPO đang xem xét. Câu trả lời sẽ hiện ở đây sau khi được duyệt.</p>'
        : `<div class="a-card" id="ans-d${k}">${renderAnswer(draftToAnswer(d), "d" + k)}</div>`}</div></div>`).join("");
  mine.forEach((d, k) => { const el = $("#ans-d" + k); if (el) wireAnswer(el, "d" + k); });
}

// ------------------------------------------------------------------ reviewer
let REVIEW_TAB = "pending";
async function pageReview(page) {
  page.innerHTML = `<div class="subtabs" role="tablist">${[["pending", "Chờ duyệt"], ["approved", "Đã duyệt"], ["rejected", "Đã từ chối"]]
    .map(([k, l]) => `<button role="tab" data-t="${k}" class="${REVIEW_TAB === k ? "active" : ""}">${l}</button>`).join("")}</div>
    <div id="rq"><div class="card empty">Đang tải…</div></div>`;
  $$(".subtabs button", page).forEach((b) => b.onclick = () => { REVIEW_TAB = b.dataset.t; pageReview(page); });
  let q;
  try { q = await api("/api/review/drafts?status=" + REVIEW_TAB); }
  catch (e) { $("#rq").innerHTML = `<div class="card empty">${esc(e.message)}</div>`; return; }
  if (!q.length) { $("#rq").innerHTML = '<div class="card empty">Không có bản nháp nào.</div>'; return; }
  $("#rq").innerHTML = q.map((d) => `<div class="card review" data-id="${d.draft_id}" style="margin-bottom:16px">
    <div class="card-h">${avatar(d.asker.name, 28)}<div style="flex:1"><b>${esc(d.asker.name)}</b> <span class="muted small">${esc(d.asker.org)}</span>
      <div class="small">${esc(d.question)}</div></div>
      <div class="chips">${d.topics.map((t) => `<span class="chip warn">${esc(t)}</span>`).join("")}${d.lang === "en" ? '<span class="chip info">EN</span>' : ""}</div></div>
    <div class="card-b">${!d.visible ? `<div class="alert bad">${icon("lock")} ${esc(d.reason)} — bản nháp bị ẩn để không lộ tài liệu ngoài quyền của bạn.</div>`
      : `<p class="muted small" style="margin-top:0">Mỗi ý có thể sửa lời; xóa trắng một ý để bỏ ý đó. Nguồn trích dẫn không thay đổi.</p>
      ${d.answer.claims.map((c, n) => `<label class="field">Ý ${n + 1} <span class="muted small">nguồn [${c.refs.join(", ")}]</span>
        <textarea class="input" rows="2" data-claim="${n}" ${d.status !== "pending" ? "disabled" : ""}>${esc(c.text)}</textarea></label>`).join("")}
      <details class="trace"><summary>${icon("file")} ${d.answer.citations.length} trích dẫn</summary>${d.answer.citations.map((c) =>
        `<div class="cite" style="margin-top:8px"><div class="cite-top"><span class="cite-n">${c.n}</span>${ftype((c.name.split(".").pop() || "").toLowerCase())}<span class="cite-name">${esc(c.name)}</span></div>
        <div class="cite-loc">${esc(c.locator)}</div><blockquote>${esc(c.quote)}</blockquote>
        ${c.web_url ? `<a href="${esc(c.web_url)}" target="_blank" rel="noopener">Mở file ${icon("ext")}</a>` : ""}</div>`).join("")}</details>
      ${d.status === "pending" ? `<div class="inline-form"><input class="input" data-note placeholder="Ghi chú cho người hỏi (khi từ chối) hoặc cho nhật ký" style="flex:1;max-width:none">
        <button class="btn danger" data-act="reject">${icon("x")} Từ chối</button>
        <button class="btn primary" data-act="approve">${icon("check")} Duyệt & phát hành</button></div>`
        : `<p class="muted small">${d.status === "approved" ? "Đã duyệt" : "Đã từ chối"} bởi ${esc(d.reviewer || "")}${d.note ? " · " + esc(d.note) : ""}</p>`}`}
    </div></div>`).join("");
  $$(".review[data-id]", page).forEach((card) => $$("[data-act]", card).forEach((b) => b.onclick = async () => {
    const body = { action: b.dataset.act, note: $("[data-note]", card).value || null };
    if (body.action === "approve") body.claims = $$("[data-claim]", card).map((t) => t.value);
    try { await post(`/api/review/drafts/${card.dataset.id}`, body); toast(body.action === "approve" ? "Đã duyệt và phát hành" : "Đã từ chối"); pageReview(page); }
    catch (e) { toast(e.message, "bad"); }
  }));
}

// ------------------------------------------------------------------ search
let SEARCH_Q = "", SEARCH_RES = null;
function highlight(text, terms) {
  let out = esc(text);
  for (const t of terms || []) {
    if (t.length < 3) continue;
    out = out.replace(new RegExp(`(${t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "gi"), "<mark>$1</mark>");
  }
  return out;
}
async function pageSearch(page) {
  page.innerHTML = `<form class="toolbar" id="sform"><div class="search" style="flex:1;max-width:none">${icon("search")}
      <input class="input" id="sq" placeholder="Ví dụ: hợp đồng EPC Hàm Kiệm, biên bản nghiệm thu công suất, room ngoại…" value="${esc(SEARCH_Q)}"></div>
      <button class="btn primary" type="submit">Tìm</button></form><div id="sres"></div>`;
  const draw = () => {
    const r = SEARCH_RES;
    if (!r) { $("#sres").innerHTML = '<div class="card empty">Nhập từ khóa hoặc mô tả nội dung tài liệu — không cần nhớ tên file.</div>'; return; }
    if (r.refused) { $("#sres").innerHTML = `<div class="card empty">${esc(r.message)}</div>`; return; }
    if (!r.results.length) { $("#sres").innerHTML = '<div class="card empty">Không tìm thấy tài liệu phù hợp trong phạm vi của bạn.</div>'; return; }
    $("#sres").innerHTML = `<p class="muted small">${r.results.length} tài liệu trong phạm vi của bạn</p>` + r.results.map((x) => `<div class="card sr">
      <div class="cite-top">${ftype(x.ext)}<b class="cite-name">${esc(x.name)}</b><span class="chip">${esc(SITE_LABEL[x.site_id] || x.site_id)}</span>
        ${x.ocr ? '<span class="chip info">bản scan</span>' : ""}</div>
      <div class="muted small">${esc([x.site_id, x.path].filter(Boolean).join(" › "))} · ${esc(x.locator)}</div>
      <p class="snip">${highlight(x.snippet, r.terms)}</p>
      <div class="cite-foot">${x.web_url ? `<a href="${esc(x.web_url)}" target="_blank" rel="noopener">${icon("file")} Mở file ${icon("ext")}</a>` : ""}
        ${x.public ? `<a href="${esc(x.public.url)}" target="_blank" rel="noopener">${icon("globe")} Link public thư mục ${esc(x.public.folder)}</a>` : ""}
        <span style="flex:1"></span><button class="btn sm" data-askabout="${esc(x.name)}">${icon("chat")} Hỏi về tài liệu này</button></div></div>`).join("");
    $$("[data-askabout]").forEach((b) => b.onclick = () => { location.hash = "#/chat"; setTimeout(() => { const q = $("#q"); if (q) { q.value = `Tài liệu ${b.dataset.askabout} nói gì về `; q.focus(); } }, 50); });
  };
  $("#sform").onsubmit = async (e) => {
    e.preventDefault(); SEARCH_Q = $("#sq").value.trim(); if (!SEARCH_Q) return;
    $("#sres").innerHTML = '<div class="card empty"><span class="spinner"></span> Đang tìm…</div>';
    try { SEARCH_RES = await api("/api/search?q=" + encodeURIComponent(SEARCH_Q)); } catch (ex) { SEARCH_RES = { refused: true, message: ex.message }; }
    draw();
  };
  draw();
  $("#sq").focus();
}

// ------------------------------------------------------------------ scope
let SCOPE_FILTER = null, SCOPE_Q = "";
function scopeStats(sc) {
  const c = sc.counts;
  return [["all", "Mở được trên SharePoint", sc.sharepoint_total, ""], ["ai_ok", "AI truy xuất được", c.ai_ok || 0, "ok"],
    ["excluded", "Không cho AI", c.excluded || 0, "warn"], ["encrypted", "Mã hóa", c.encrypted || 0, "bad"], ["malware", "Mã độc", c.malware || 0, "bad"],
    ["ai_blocked", "AI đang chặn", c.ai_blocked || 0, "warn"], ["pending", "Đang nạp", c.pending || 0, ""], ["unsupported", "Không đọc được", c.unsupported || 0, ""]];
}
function renderTree(sc, filter, q) {
  q = (q || "").toLowerCase();
  return sc.sites.map((s) => {
    const all = s.folders.flatMap((f) => f.files);
    const ai = all.filter((x) => x.status === "ai_ok").length;
    const folders = s.folders.map((f) => {
      const files = f.files.filter((x) => (!filter || x.status === filter) && (!q || x.name.toLowerCase().includes(q)));
      if (!files.length) return "";
      return `<div class="folder"><div class="folder-h">${icon("folder")} ${esc(f.path || "(gốc)")}</div>${files.map((x) => {
        const [lab, cls] = STATUS[x.status] || [x.status, ""];
        return `<div class="file">${ftype(x.ext)}<span class="name" title="${esc(x.name)}">${esc(x.name)}</span><span class="chip ${cls}">${lab}</span><span class="det">${esc(x.detail || "")}</span></div>`;
      }).join("")}</div>`;
    }).join("");
    if (!folders) return "";
    return `<details class="card site-block" open><summary>${icon("globe")} ${esc(s.name)} <span class="chip">${s.site}</span>
      <span class="muted small" style="font-weight:500">${ai}/${all.length} file AI dùng được</span>
      <span class="bar"><span style="width:${all.length ? Math.round(ai / all.length * 100) : 0}%"></span></span></summary>${folders}</details>`;
  }).join("") || '<div class="card empty">Không có tài liệu phù hợp.</div>';
}

let SCOPE_USER = null;
async function pageScope(page) {
  if (!DIR) await loadDir();
  SCOPE_USER = SCOPE_USER || DIR.users[0]?.oid;
  page.innerHTML = `<div class="toolbar"><label class="field" style="margin:0;flex:1;max-width:420px">Người dùng
      <select class="input" id="scope-user">${DIR.users.map((u) => `<option value="${u.oid}" ${u.oid === SCOPE_USER ? "selected" : ""}>${esc(u.name)} — ${esc(u.org)}</option>`).join("")}</select></label>
      <div class="chips" id="scope-who" style="align-self:flex-end"></div></div>
    <div class="stats" id="stats"></div>
    <div class="toolbar"><div class="search">${icon("search")}<input class="input" id="sq" placeholder="Tìm theo tên file…" value="${esc(SCOPE_Q)}"></div>
    <span class="muted small" id="scope-note"></span></div><div id="tree"><div class="card empty">Đang tải…</div></div>`;
  $("#scope-user").onchange = (e) => { SCOPE_USER = e.target.value; pageScope(page); };
  const sc = await api("/api/scope_of/" + encodeURIComponent(SCOPE_USER));
  $("#scope-who").innerHTML = sc.groups.map((g) => `<span class="chip brand">${esc(GROUP_LABEL[g] || g)}</span>`).join("")
    + sc.roles.map((r) => `<span class="chip info">${esc(ROLE_LABEL[r] || r)}</span>`).join("");
  const draw = () => {
    $("#stats").innerHTML = scopeStats(sc).map(([k, l, v, cls]) => `<button class="stat ${cls} ${(SCOPE_FILTER || "all") === k ? "sel" : ""}" data-k="${k}"><div class="v">${v}</div><div class="l">${l}</div></button>`).join("");
    $$("#stats .stat").forEach((b) => b.onclick = () => { SCOPE_FILTER = b.dataset.k === "all" ? null : b.dataset.k; draw(); });
    $("#tree").innerHTML = renderTree(sc, SCOPE_FILTER, SCOPE_Q);
    $("#scope-note").innerHTML = sc.violations_ai_without_sharepoint.length
      ? `<span class="chip bad">VI PHẠM: AI thấy ${sc.violations_ai_without_sharepoint.length} file SharePoint không cho mở</span>`
      : `${icon("check")} Không có tài liệu nào AI thấy mà SharePoint không cho mở`;
  };
  $("#sq").oninput = (e) => { SCOPE_Q = e.target.value; draw(); };
  draw();
}

// ------------------------------------------------------------------ permissions (admin)
let PERM_TAB = "users", DIR = null, PERM_SITE = "COMMON", PERM_FOLDER = null, USER_Q = "";
const uname = (oid) => DIR?.users.find((u) => u.oid === oid)?.name || oid;
const gname = (gid) => GROUP_LABEL[gid] || gid;
const principal = (g) => g.kind === "group" ? `${icon("users")} ${esc(gname(g.id))}` : g.kind === "user" ? `${icon("user")} ${esc(uname(g.id))}`
  : g.kind === "link_specific" ? `${icon("ext")} Link cho ${esc(uname(g.id))}` : `${icon("globe")} Link ${g.kind === "link_anyone" ? "Anyone" : "tổ chức"} (bị bỏ qua)`;

async function loadDir() { DIR = await api("/api/admin/directory"); return DIR; }

async function change(path, body, okMsg) {
  try {
    const r = await post(path, body);
    const pending = (r.pending_sharepoint || []).filter((p) => p.sharepoint_applies_in > 0).length;
    toast(okMsg + (pending ? ` · SharePoint sẽ áp thay đổi nhóm sau ~${Math.ceil(Math.max(...r.pending_sharepoint.map((p) => p.sharepoint_applies_in)))}s; AI đã áp ngay.` : ""));
    await loadDir();
    return r;
  } catch (e) { toast(e.message, "bad"); throw e; }
}

async function pagePerms(page) {
  page.innerHTML = `<div class="toolbar"><div class="subtabs" style="margin:0;flex:1;border:0" role="tablist">
      ${[["users", "Người dùng"], ["groups", "Nhóm"], ["folders", "Thư mục & tài liệu"], ["sites", "Site & RAC"]].map(([k, l]) => `<button role="tab" data-t="${k}" class="${PERM_TAB === k ? "active" : ""}">${l}</button>`).join("")}</div>
      <button class="btn" id="restore">${icon("refresh")} Khôi phục bản gốc</button></div>
    <div id="perm-body"><div class="card empty">Đang tải…</div></div>`;
  $$(".subtabs button", page).forEach((b) => b.onclick = () => { PERM_TAB = b.dataset.t; pagePerms(page); });
  $("#restore").onclick = () => modal({ title: "Khôi phục phân quyền gốc?", body: "<p>Mọi thay đổi người dùng, nhóm, quyền thư mục/tài liệu và AI_Use sẽ quay về như lúc sinh dữ liệu. Nhật ký vẫn giữ.</p>",
    actions: [{ label: "Hủy" }, { label: "Khôi phục", primary: true, onClick: async () => { await post("/api/admin/restore", {}); toast("Đã khôi phục bản gốc"); await loadDir(); pagePerms(page); } }] });
  await loadDir();
  ({ users: permUsers, groups: permGroups, folders: permFolders, sites: permSites })[PERM_TAB]($("#perm-body"));
}

function permUsers(el) {
  const rows = DIR.users.filter((u) => !USER_Q || (u.name + u.email + u.org).toLowerCase().includes(USER_Q.toLowerCase()));
  el.innerHTML = `<div class="toolbar"><div class="search">${icon("search")}<input class="input" id="uq" placeholder="Tìm người dùng…" value="${esc(USER_Q)}"></div>
    <span class="muted small">${DIR.users.length} tài khoản · ${DIR.users.filter((u) => u.type === "guest").length} khách B2B</span><span style="flex:1"></span>
    <button class="btn primary" id="invite">${icon("plus")} Mời người dùng</button></div>
  <div class="card table-wrap"><table class="t"><thead><tr><th>Người dùng</th><th>Loại</th><th>Nhóm (quyền SharePoint)</th><th>Vai trò AI</th><th>Hoạt động</th></tr></thead><tbody>
  ${rows.map((u) => `<tr data-oid="${u.oid}">
    <td><div class="u-cell">${avatar(u.name)}<div class="who"><b>${esc(u.name)}</b><br><small>${esc(u.email)} · ${esc(u.org)}</small>
      ${DIR.deny_list[u.oid] ? `<br><span class="chip bad">Danh sách chặn: ${esc(DIR.deny_list[u.oid])}</span>` : ""}
      ${DIR.revocations.filter((r) => r.oid === u.oid).map((r) => `<br><span class="chip warn">Đang thu hồi: ${esc(gname(r.group))}</span>`).join("")}</div></div></td>
    <td><span class="chip">${u.type === "guest" ? "Khách B2B" : "Nhân viên"}</span></td>
    <td><div class="chips">${u.groups.map((g) => `<span class="chip brand">${esc(gname(g))}<button data-rm-group="${g}" aria-label="Gỡ khỏi ${esc(gname(g))}">${icon("x")}</button></span>`).join("")}
      <select class="input" data-add-group style="height:26px;width:auto;font-size:12px;padding:0 4px"><option value="">+ Thêm nhóm</option>${DIR.groups.filter((g) => !u.groups.includes(g.id)).map((g) => `<option value="${g.id}">${esc(gname(g.id))}</option>`).join("")}</select></div></td>
    <td><div class="chips">${DIR.roles.map((r) => `<button class="chip ${u.roles.includes(r) ? "info" : ""}" data-role="${r}" aria-pressed="${u.roles.includes(r)}" title="Bật/tắt ${ROLE_LABEL[r]}" style="border:0;cursor:pointer">${u.roles.includes(r) ? icon("check") : ""}${ROLE_LABEL[r] || r}</button>`).join("")}</div></td>
    <td><button class="switch" role="switch" aria-checked="${u.enabled}" data-enabled aria-label="Bật/tắt tài khoản"></button></td></tr>`).join("")}
  </tbody></table></div>`;
  $("#uq").oninput = (e) => { USER_Q = e.target.value; const pos = e.target.selectionStart; permUsers(el); const n = $("#uq"); n.focus(); n.setSelectionRange(pos, pos); };
  $("#invite").onclick = inviteModal;
  $$("tr[data-oid]", el).forEach((tr) => {
    const oid = tr.dataset.oid, u = DIR.users.find((x) => x.oid === oid);
    $$("[data-rm-group]", tr).forEach((b) => b.onclick = async () => { await change(`/api/admin/groups/${b.dataset.rmGroup}/members`, { oid, add: false }, `Đã gỡ ${u.name} khỏi ${gname(b.dataset.rmGroup)}`); permUsers(el); });
    $("[data-add-group]", tr).onchange = async (e) => { if (!e.target.value) return; await change(`/api/admin/groups/${e.target.value}/members`, { oid, add: true }, `Đã thêm ${u.name} vào ${gname(e.target.value)}`); permUsers(el); };
    $$("[data-role]", tr).forEach((b) => b.onclick = async () => {
      const r = b.dataset.role, roles = u.roles.includes(r) ? u.roles.filter((x) => x !== r) : [...u.roles, r];
      await change(`/api/admin/users/${oid}/roles`, { roles }, `Đã cập nhật vai trò của ${u.name}`); permUsers(el);
    });
    $("[data-enabled]", tr).onclick = async () => { await change(`/api/admin/users/${oid}/enabled`, { enabled: !u.enabled }, `${u.enabled ? "Đã tắt" : "Đã bật"} tài khoản ${u.name}`); permUsers(el); };
  });
}

function inviteModal() {
  modal({ title: "Mời người dùng vào Data Room", body: `
    <label class="field">Họ tên<input class="input" id="nu-name" required></label>
    <label class="field">Email<input class="input" id="nu-email" type="email" required></label>
    <label class="field">Tổ chức<input class="input" id="nu-org"></label>
    <label class="field">Loại<select class="input" id="nu-type"><option value="guest">Khách B2B (nhà đầu tư, cố vấn)</option><option value="member">Nhân viên tổ chức phát hành</option></select></label>
    <div class="field">Nhóm<div class="checks">${DIR.groups.map((g) => `<label><input type="checkbox" value="${g.id}" data-nu-group> ${esc(gname(g.id))}</label>`).join("")}</div></div>
    <div class="field">Vai trò AI<div class="checks">${DIR.roles.map((r) => `<label><input type="checkbox" value="${r}" data-nu-role> ${ROLE_LABEL[r]}</label>`).join("")}</div></div>
    <label class="field">Mật khẩu tạm (≥ 8 ký tự)<input class="input" id="nu-pw" type="password" autocomplete="new-password"></label>
    <div class="alert info small">Thêm vào nhóm có hiệu lực ở AI ngay sau đồng bộ, còn SharePoint giả lập áp sau độ trễ (mặc định 60 giây).</div>`,
  actions: [{ label: "Hủy" }, { label: "Mời", primary: true, onClick: async (ov) => {
    try {
      await change("/api/admin/users", {
        name: $("#nu-name", ov).value, email: $("#nu-email", ov).value, org: $("#nu-org", ov).value, type: $("#nu-type", ov).value,
        groups: $$("[data-nu-group]:checked", ov).map((x) => x.value), roles: $$("[data-nu-role]:checked", ov).map((x) => x.value), password: $("#nu-pw", ov).value,
      }, "Đã mời người dùng mới");
      permUsers($("#perm-body"));
    } catch { return false; }
  } }] });
}

function permGroups(el) {
  el.innerHTML = `<div class="grid-2">${DIR.groups.map((g) => `<div class="card" data-gid="${g.id}">
    <div class="card-h">${icon("users")}<h3>${esc(gname(g.id))}</h3><span class="chip">${g.id}</span><span style="flex:1"></span><span class="muted small">${g.members.length} thành viên</span></div>
    <div class="card-b">${g.members.map((m) => `<div class="grant-row">${avatar(uname(m), 26)}<div class="g">${esc(uname(m))}${DIR.revocations.some((r) => r.oid === m && r.group === g.id) ? ' <span class="chip warn">đang thu hồi</span>' : ""}</div>
      <button class="btn sm ghost danger" data-rm="${m}">${icon("x")} Gỡ</button></div>`).join("") || '<div class="muted small">Chưa có thành viên</div>'}
      <div class="inline-form"><select class="input" data-add style="max-width:none;flex:1"><option value="">Chọn người để thêm…</option>${DIR.users.filter((u) => !g.members.includes(u.oid)).map((u) => `<option value="${u.oid}">${esc(u.name)} — ${esc(u.org)}</option>`).join("")}</select>
      <button class="btn primary sm" data-addbtn>${icon("plus")} Thêm</button></div></div></div>`).join("")}</div>`;
  $$("[data-gid]", el).forEach((card) => {
    const gid = card.dataset.gid;
    $$("[data-rm]", card).forEach((b) => b.onclick = async () => { await change(`/api/admin/groups/${gid}/members`, { oid: b.dataset.rm, add: false }, `Đã gỡ ${uname(b.dataset.rm)} khỏi ${gname(gid)}`); permGroups(el); });
    $("[data-addbtn]", card).onclick = async () => { const oid = $("[data-add]", card).value; if (!oid) return; await change(`/api/admin/groups/${gid}/members`, { oid, add: true }, `Đã thêm ${uname(oid)} vào ${gname(gid)}`); permGroups(el); };
  });
}

function grantEditor({ unique, grants, onAdd, onRemove, onInherit, inheritLabel }) {
  return `<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">${unique ? '<span class="chip warn">Quyền riêng (đã tách kế thừa)</span>' : '<span class="chip">Kế thừa từ cấp trên</span>'}
      <span style="flex:1"></span>${unique && onInherit ? `<button class="btn sm" data-inherit>${icon("refresh")} ${inheritLabel || "Khôi phục kế thừa"}</button>` : ""}</div>
    ${grants.map((g, i) => `<div class="grant-row"><div class="g">${principal(g)}<div class="muted small">${esc(g.source || "")}</div></div>
      ${g.kind === "user" || g.kind === "group" ? `<button class="btn sm ghost danger" data-rm-grant="${i}">${icon("x")} Gỡ</button>` : ""}</div>`).join("") || '<div class="muted small">Không ai có quyền.</div>'}
    <div class="inline-form"><select class="input" data-gkind style="width:130px"><option value="group">Nhóm</option><option value="user">Người dùng</option></select>
      <select class="input" data-gid style="flex:1;max-width:none"></select><button class="btn primary sm" data-grant>${icon("plus")} Cấp quyền</button></div>
    <p class="muted small" style="margin:8px 0 0">${icon("info")} Site có RAC: người được cấp còn phải thuộc nhóm RAC của site thì mới mở được (bức tường thứ hai).</p>`;
}
function wireGrantEditor(root, grants, h) {
  const kind = $("[data-gkind]", root), sel = $("[data-gid]", root);
  const fill = () => {
    sel.innerHTML = kind.value === "group" ? DIR.groups.map((g) => `<option value="${g.id}">${esc(gname(g.id))}</option>`).join("")
      : DIR.users.map((u) => `<option value="${u.oid}">${esc(u.name)} — ${esc(u.org)}</option>`).join("");
  };
  kind.onchange = fill; fill();
  $("[data-grant]", root).onclick = () => h.add(kind.value, sel.value);
  $$("[data-rm-grant]", root).forEach((b) => b.onclick = () => { const g = grants[+b.dataset.rmGrant]; h.remove(g.kind, g.id); });
  const inh = $("[data-inherit]", root); if (inh) inh.onclick = h.inherit;
}

async function permFolders(el) {
  el.innerHTML = `<div class="toolbar">${DIR.sites.map((s) => `<button class="btn ${PERM_SITE === s.id ? "primary" : ""} sm" data-site="${s.id}">${esc(s.name)}</button>`).join("")}</div>
    <div class="grid-side"><div class="card"><div class="card-h"><h3>Thư mục</h3></div><div class="list" id="flist" style="padding:6px"></div></div><div id="fdetail"></div></div>`;
  $$("[data-site]", el).forEach((b) => b.onclick = () => { PERM_SITE = b.dataset.site; PERM_FOLDER = null; permFolders(el); });
  const tree = await api("/api/admin/tree/" + PERM_SITE);
  if (!PERM_FOLDER || !tree.folders.some((f) => f.path === PERM_FOLDER)) PERM_FOLDER = tree.folders[0]?.path;
  $("#flist").innerHTML = tree.folders.map((f) => `<button class="${f.path === PERM_FOLDER ? "active" : ""}" data-f="${esc(f.path)}">${icon("folder")}<span style="flex:1">${esc(f.path)}</span>${f.unique ? '<span class="chip warn">riêng</span>' : ""}<span class="muted small">${f.files.length}</span></button>`).join("");
  $$("#flist button").forEach((b) => b.onclick = () => { PERM_FOLDER = b.dataset.f; permFolders(el); });
  const f = tree.folders.find((x) => x.path === PERM_FOLDER);
  if (!f) { $("#fdetail").innerHTML = '<div class="card empty">Site trống</div>'; return; }
  const ST = { indexed: ["Đã lập chỉ mục", "ok"], skipped: ["Bỏ qua", "warn"], error: ["Lỗi", "bad"], pending: ["Chờ nạp", "info"] };
  $("#fdetail").innerHTML = `<div class="card" style="margin-bottom:16px"><div class="card-h">${icon("key")}<h3>Quyền thư mục: ${esc(f.path)}</h3></div><div class="card-b" id="fgrants">${grantEditor({ unique: f.unique, grants: f.grants, onInherit: true })}</div></div>
    <div class="card table-wrap"><table class="t"><thead><tr><th>Tài liệu</th><th>AI_Use</th><th>Quyền</th><th>Trạng thái nạp</th><th></th></tr></thead><tbody>
    ${f.files.map((x) => `<tr data-item="${x.item_id}"><td><div style="display:flex;gap:8px;align-items:center;min-width:260px">${ftype(x.ext)}<span>${esc(x.name)}</span>
        ${x.encrypted ? '<span class="chip bad">mã hóa</span>' : ""}${x.malware ? '<span class="chip bad">mã độc</span>' : ""}</div></td>
      <td><select class="input" data-aiuse style="height:30px;width:130px">${DIR.ai_use.map((v) => `<option ${v === x.ai_use ? "selected" : ""}>${v}</option>`).join("")}</select></td>
      <td>${x.unique ? '<span class="chip warn">riêng</span>' : '<span class="chip">kế thừa</span>'}${x.grants.some((g) => g.kind.startsWith("link_")) ? ' <span class="chip info">có link</span>' : ""}</td>
      <td>${(([l, c]) => `<span class="chip ${c}">${l}</span>`)(ST[x.status] || [x.status, ""])} <span class="muted small">${x.chunks || 0} đoạn</span></td>
      <td><button class="btn sm" data-iperm>${icon("key")} Quyền</button></td></tr>`).join("")}</tbody></table></div>`;
  wireGrantEditor($("#fgrants"), f.grants, {
    add: async (kind, id) => { await change("/api/admin/grants", { target: "folder", site: PERM_SITE, key: f.path, kind, id, add: true }, `Đã cấp quyền thư mục cho ${kind === "group" ? gname(id) : uname(id)}`); permFolders(el); },
    remove: async (kind, id) => { await change("/api/admin/grants", { target: "folder", site: PERM_SITE, key: f.path, kind, id, add: false }, `Đã gỡ quyền thư mục của ${kind === "group" ? gname(id) : uname(id)}`); permFolders(el); },
    inherit: async () => { await change("/api/admin/grants/inherit", { target: "folder", site: PERM_SITE, key: f.path }, "Đã khôi phục kế thừa cho thư mục"); permFolders(el); },
  });
  $$("tr[data-item]", $("#fdetail")).forEach((tr) => {
    const x = f.files.find((y) => y.item_id === tr.dataset.item);
    $("[data-aiuse]", tr).onchange = async (e) => { await change(`/api/admin/items/${x.item_id}/ai_use`, { value: e.target.value }, `AI_Use = ${e.target.value} cho ${x.name}`); permFolders(el); };
    $("[data-iperm]", tr).onclick = () => itemDrawer(x, el);
  });
}

function itemDrawer(x, el) {
  const body = drawer(x.name, `<div class="muted small" style="margin-bottom:10px">${esc(x.item_id)} · ${esc(x.label || "không nhãn")}</div>` + grantEditor({ unique: x.unique, grants: x.grants, onInherit: true }));
  wireGrantEditor(body, x.grants, {
    add: async (kind, id) => { await change("/api/admin/grants", { target: "item", site: PERM_SITE, key: x.item_id, kind, id, add: true }, "Đã cấp quyền tài liệu"); $(".drawer-ov")?.click(); permFolders(el); },
    remove: async (kind, id) => { await change("/api/admin/grants", { target: "item", site: PERM_SITE, key: x.item_id, kind, id, add: false }, "Đã gỡ quyền tài liệu"); $(".drawer-ov")?.click(); permFolders(el); },
    inherit: async () => { await change("/api/admin/grants/inherit", { target: "item", site: PERM_SITE, key: x.item_id }, "Đã khôi phục kế thừa"); $(".drawer-ov")?.click(); permFolders(el); },
  });
}

function permSites(el) {
  el.innerHTML = `<div class="grid-2">${DIR.sites.map((s) => `<div class="card" data-site="${s.id}">
    <div class="card-h">${icon("globe")}<h3>${esc(s.name)}</h3><span class="chip">${s.id}</span><span style="flex:1"></span>${s.rac ? '<span class="chip ok">RAC bật</span>' : '<span class="chip">RAC tắt</span>'}</div>
    <div class="card-b"><p class="muted small" style="margin-top:0">Nhóm có quyền đọc site. Khi RAC bật, đây cũng là bức tường thứ hai: ai không thuộc các nhóm này không mở được gì trong site, kể cả khi có link hoặc quyền riêng.</p>
      <div class="checks">${DIR.groups.map((g) => `<label><input type="checkbox" value="${g.id}" ${s.groups.includes(g.id) ? "checked" : ""}> ${esc(gname(g.id))}</label>`).join("")}</div>
      <div class="inline-form"><button class="btn primary sm" data-save>${icon("check")} Lưu nhóm của site</button></div></div></div>`).join("")}</div>`;
  $$("[data-site]", el).forEach((card) => $("[data-save]", card).onclick = async () => {
    const groups = $$("input:checked", card).map((x) => x.value);
    await change(`/api/admin/sites/${card.dataset.site}/groups`, { groups }, "Đã lưu nhóm của site"); permSites(el);
  });
}

// ------------------------------------------------------------------ matrix
async function pageMatrix(page) {
  page.innerHTML = '<div class="card empty">Đang tải…</div>';
  const m = await api("/api/matrix");
  page.innerHTML = `<p class="muted" style="margin-top:0">Ô màu cam: AI đang chặn trước SharePoint (thu hồi chờ SharePoint áp dụng). Bấm một dòng để xem phạm vi chi tiết.</p>
  <div class="card table-wrap"><table class="t mx"><thead><tr><th>Người dùng</th><th>Nhóm</th>${m.sites.map((s) => `<th style="text-align:center">${esc(s.name)}</th>`).join("")}</tr></thead><tbody>
  ${m.rows.map((r) => `<tr class="click" data-oid="${r.oid}"><td><div class="u-cell">${avatar(r.name)}<div class="who"><b>${esc(r.name)}</b><br><small>${esc(r.org)}</small>
      ${r.enabled ? "" : ' <span class="chip bad">đã tắt</span>'}${r.roles.some((x) => x.endsWith(".AI")) ? "" : ' <span class="chip warn">không có AI</span>'}</div></div></td>
    <td><div class="chips">${r.groups.map((g) => `<span class="chip">${esc(gname(g))}</span>`).join("")}</div></td>
    ${m.sites.map((s) => { const c = r.sites[s.id]; return `<td class="cell ${c.lag ? "lag" : ""}" title="${c.lag ? c.lag + " file AI đang chặn trước SharePoint" : ""}">${c.sharepoint ? `<span class="cellv"><b>${c.ai}</b><span class="muted small">/ ${c.sharepoint}</span><span class="meter"><span style="width:${Math.round(c.ai / c.sharepoint * 100)}%"></span></span></span>` : '<span class="muted">—</span>'}</td>`; }).join("")}</tr>`).join("")}
  </tbody></table></div>`;
  $$("tr[data-oid]", page).forEach((tr) => tr.onclick = async () => {
    const body = drawer("Phạm vi của " + tr.querySelector("b").textContent, '<div class="empty">Đang tải…</div>');
    const sc = await api("/api/scope_of/" + tr.dataset.oid);
    body.innerHTML = `<div class="stats">${scopeStats(sc).slice(0, 4).map(([, l, v, c]) => `<div class="stat ${c}" style="cursor:default"><div class="v">${v}</div><div class="l">${l}</div></div>`).join("")}</div>` + renderTree(sc, null, "");
  });
}

// ------------------------------------------------------------------ scenarios
const SCEN = [
  { name: "remove_from_group", t: "Gỡ khỏi một nhóm", d: "Người thuộc 2 nhóm bị gỡ khỏi một nhóm: SharePoint còn trễ, AI chặn ngay bằng tập thu hồi (người, nhóm).", f: ["oid:inv-ab", "group:DR-INV-A"] },
  { name: "move_group", t: "Chuyển nhóm", d: "Nhóm cũ bị chặn ngay; nhóm mới chỉ mở khi SharePoint xác nhận.", f: ["oid:inv-a2", "from:DR-INV-A", "to:DR-INV-C"] },
  { name: "exclude_file", t: "Đặt một file AI_Use = Excluded", d: "Câu hỏi kế tiếp không dùng được file, nhà đầu tư vẫn mở được." },
  { name: "publish_redacted_version", t: "Thay hợp đồng bằng bản đã biên tập", d: "Đoạn của bản cũ bị vô hiệu ngay; kiểm tra trực tiếp so ctag." },
  { name: "offboard", t: "Offboard một nhà đầu tư", d: "Token còn hạn vẫn bị chặn ở cổng 4.", f: ["oid:inv-b2"] },
  { name: "corrupt_mirror", t: "Tiêm lỗi vào bản chép quyền", d: "Cho B 'đọc' tài liệu Nhóm A trong mirror — kiểm tra trực tiếp vẫn chặn.", f: ["oid:inv-b1"] },
  { name: "pause_entra_feed", t: "Ngắt nguồn Entra", d: "Sau 30 giây mọi câu hỏi bị từ chối (đóng an toàn)." },
  { name: "resume_entra_feed", t: "Khôi phục nguồn Entra", d: "Đồng bộ lại mốc thời gian." },
  { name: "reset", t: "Khôi phục trạng thái ban đầu", d: "Nạp lại tenant gốc và đồng bộ toàn bộ." },
];
async function pageScenarios(page) {
  if (!DIR) await loadDir();
  const sel = (spec) => {
    const [k, v] = spec.split(":");
    const opts = k === "oid" ? DIR.users.map((u) => [u.oid, u.name]) : DIR.groups.map((g) => [g.id, gname(g.id)]);
    return `<select data-p="${k}" aria-label="${k}">${opts.map(([id, n]) => `<option value="${id}" ${id === v ? "selected" : ""}>${esc(n)}</option>`).join("")}</select>`;
  };
  page.innerHTML = `<div class="scen-grid"><div class="card">${SCEN.map((s, i) => `<div class="scen" data-name="${s.name}"><h4>${i + 1}. ${s.t}</h4><p>${s.d}</p>
    <div class="row">${(s.f || []).map(sel).join("")}<button class="btn primary sm">${icon("play")} Chạy</button></div></div>`).join("")}</div>
    <div><div class="card" style="margin-bottom:16px"><div class="card-h"><h3>Kết quả</h3></div><div class="card-b" id="scen-result"><p class="muted" style="margin:0">Chọn một kịch bản để chạy.</p></div></div>
    <div class="card"><div class="card-h"><h3>Trạng thái trực tiếp</h3><span style="flex:1"></span><span class="spinner"></span></div><div class="card-b" id="live"></div></div></div></div>`;
  $$(".scen", page).forEach((card) => $("button", card).onclick = async () => {
    const params = {}; $$("[data-p]", card).forEach((s) => params[s.dataset.p] = s.value);
    try {
      const r = await post("/api/scenario/" + card.dataset.name, { params });
      $("#scen-result").innerHTML = `<h4 style="margin:0 0 6px">${esc(r.title)}</h4><p style="margin:0 0 8px">${esc(r.explain)}</p>${r.try ? `<div class="alert info">${icon("info")} Thử: ${esc(r.try)}</div>` : ""}`;
      toast("Đã chạy: " + r.title); loadDir(); pollStatus();
    } catch (e) { toast(e.message, "bad"); }
  });
  renderLive();
}
function renderLive() {
  const el = $("#live"); if (!el || !STATUS_CACHE) return;
  const s = STATUS_CACHE, age = (k) => Math.round(s.feeds[k] ?? 1e9);
  const pending = s.sharepoint_pending.filter((p) => p.sharepoint_applies_in > 0);
  el.innerHTML = `<div class="kv"><span>Nguồn Entra</span><b class="${s.entra_paused ? "" : ""}">${s.entra_paused ? '<span class="chip bad">ĐANG NGẮT</span>' : '<span class="chip ok">hoạt động</span>'} ${age("entra")}s</b></div>
    <div class="kv"><span>Tài liệu</span><span>${Object.entries(s.items).map(([k, v]) => `${k}: <b>${v}</b>`).join(" · ")}</span></div>
    <h4 style="margin:14px 0 4px">Thay đổi nhóm SharePoint chưa áp dụng</h4>${pending.map((p) => `<div class="kv"><span>${p.op === "remove" ? "Gỡ" : "Thêm"} <b>${esc(uname(p.oid))}</b> ${p.op === "remove" ? "khỏi" : "vào"} ${esc(gname(p.group))}</span><span class="chip warn">còn ${Math.round(p.sharepoint_applies_in)}s</span></div>`).join("") || '<p class="muted small" style="margin:0">Không có</p>'}
    <h4 style="margin:14px 0 4px">Tập thu hồi của AI</h4>${s.revocations.map((r) => `<div class="kv"><span>${esc(uname(r.oid))} · ${esc(gname(r.group))}</span><span class="muted small">tới ${new Date(r.until).toLocaleTimeString()}</span></div>`).join("") || '<p class="muted small" style="margin:0">Trống</p>'}
    <h4 style="margin:14px 0 4px">Danh sách chặn</h4>${s.deny_list.map((d) => `<div class="kv"><span>${esc(uname(d.oid))}</span><span>${esc(d.reason)}</span></div>`).join("") || '<p class="muted small" style="margin:0">Trống</p>'}
    ${s.connector_error ? `<div class="alert bad" style="margin-top:10px">Connector: ${esc(s.connector_error)}</div>` : ""}`;
}

// ------------------------------------------------------------------ audit
async function pageAudit(page) {
  page.innerHTML = `<div class="toolbar"><button class="btn primary" id="verify">${icon("shield")} Kiểm tra chuỗi hash</button><span id="vout"></span><span style="flex:1"></span><button class="btn" id="reload">${icon("refresh")} Tải lại</button></div><div id="alist"><div class="card empty">Đang tải…</div></div>`;
  const KIND = { answer: ["Trả lời", "ok"], refusal: ["Từ chối", "warn"], sign_in: ["Đăng nhập", "info"], permission_change: ["Đổi quyền", "brand"], scenario: ["Kịch bản", ""] };
  const load = async () => {
    const rows = await api("/api/audit?limit=80");
    $("#alist").innerHTML = `<div class="card table-wrap"><table class="t"><thead><tr><th>#</th><th>Thời điểm</th><th>Người</th><th>Loại</th><th>Nội dung</th><th>Hash</th></tr></thead><tbody>${rows.map((r) => {
      const [l, c] = KIND[r.kind] || [r.kind, ""];
      return `<tr><td>${r.seq}</td><td style="white-space:nowrap">${new Date(r.ts).toLocaleString()}</td><td>${esc(r.oid === "admin" ? "Quản trị" : uname(r.oid || ""))}</td><td><span class="chip ${c}">${l}</span></td>
        <td style="max-width:520px"><pre class="payload">${esc(JSON.stringify(r.payload, null, 1))}</pre></td><td class="mono muted small">${r.hash}…</td></tr>`;
    }).join("")}</tbody></table></div>`;
  };
  $("#verify").onclick = async () => { const v = await api("/api/audit/verify"); $("#vout").innerHTML = v.ok ? `<span class="chip ok">${icon("check")} Chuỗi toàn vẹn · ${v.rows} dòng</span>` : `<span class="chip bad">Phát hiện sửa đổi tại dòng #${v.first_bad_seq}</span>`; };
  $("#reload").onclick = load;
  if (!DIR) await loadDir();
  load();
}

// ------------------------------------------------------------------ system
async function pageSystem(page) {
  const s = STATUS_CACHE || await api("/api/status");
  page.innerHTML = `<div class="grid-2">
    <div class="card"><div class="card-h">${icon("activity")}<h3>Nguồn đồng bộ</h3></div><div class="card-b">
      ${Object.entries(s.feeds).map(([k, v]) => `<div class="kv"><span>${k === "entra" ? "Entra ID (delta)" : "SharePoint (delta)"}</span><span class="chip ${v > s.feed_max_age ? "bad" : "ok"}">${Math.round(v)}s trước</span></div>`).join("")}
      <div class="kv"><span>Ngưỡng đóng an toàn</span><b>${s.feed_max_age}s</b></div>
      <div class="kv"><span>Lỗi connector</span><span>${esc(s.connector_error || "Không")}</span></div></div></div>
    <div class="card"><div class="card-h">${icon("spark")}<h3>Model (chạy local)</h3></div><div class="card-b">
      ${Object.entries(s.models).map(([k, v]) => `<div class="kv"><span>${{ llm: "Sinh câu trả lời", embed: "Embedding", rerank: "Xếp hạng lại", nli: "Kiểm căn cứ (NLI)", ocr: "OCR" }[k] || k}</span><span class="mono small">${esc(v)}</span></div>`).join("")}
      <div class="kv"><span>Trạng thái</span><span class="chip ${s.models_ready ? "ok" : "warn"}">${s.models_ready ? "Sẵn sàng" : "Đang nạp"}</span></div>
      <div class="kv"><span>OCR server (MLX)</span><span class="chip ${s.ocr_server ? "ok" : ""}">${s.ocr_server ? "Đang chạy" : "Tắt — chỉ cần khi nạp file mới"}</span></div></div></div>
    <div class="card"><div class="card-h">${icon("grid")}<h3>Chỉ mục</h3></div><div class="card-b">
      <div class="kv"><span>Tổng đoạn hiện hành</span><b>${s.index.chunks}</b></div>
      ${Object.entries(s.index.partitions).map(([k, v]) => `<div class="kv"><span>Phân vùng ${esc(SITE_LABEL[k] || k)}</span><span>${v} đoạn</span></div>`).join("")}</div></div>
    <div class="card"><div class="card-h">${icon("file")}<h3>Tài liệu</h3></div><div class="card-b">
      ${Object.entries(s.items).map(([k, v]) => `<div class="kv"><span>${{ indexed: "Đã lập chỉ mục", skipped: "Bỏ qua (có lý do)", pending: "Chờ nạp", error: "Lỗi" }[k] || k}</span><b>${v}</b></div>`).join("")}
      <div class="kv"><span>Đang nạp nền</span><span>${s.ingest_busy ? "Có" : "Không"}</span></div></div></div>
  </div>`;
}

// ------------------------------------------------------------------ start
initAuth().then(() => { if (MSAL ? MSAL.getActiveAccount() : TOKEN) boot(); else renderLogin(); })
  .catch(() => renderLogin("Không tải được thư viện đăng nhập Microsoft. Kiểm tra kết nối mạng."));
