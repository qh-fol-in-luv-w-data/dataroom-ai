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
  panel: '<rect x="3" y="3" width="18" height="18" rx="2"/><line x1="9" y1="3" x2="9" y2="21"/>',
  edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
  arrowUp: '<line x1="12" y1="19" x2="12" y2="5"/><polyline points="5 12 12 5 19 12"/>',
  chevron: '<polyline points="6 9 12 15 18 9"/>',
  copy: '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
  thumbUp: '<path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.3a2 2 0 0 0 2-1.7l1.4-9a2 2 0 0 0-2-2.3z"/><path d="M7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/>',
  thumbDown: '<path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.7a2 2 0 0 0-2 1.7l-1.4 9a2 2 0 0 0 2 2.3z"/><path d="M17 2h2.7A2.3 2.3 0 0 1 22 4v7a2.3 2.3 0 0 1-2.3 2H17"/>',
};
const icon = (n, cls = "") => `<svg class="i ${cls}" viewBox="0 0 24 24" aria-hidden="true">${ICONS[n] || ""}</svg>`;
const COLORS = ["#0e6b5c", "#3b5bdb", "#c4501b", "#6941c6", "#107c41", "#b42318", "#0e9384", "#2e5aac", "#9e3a8c", "#475467"];
// Brand mark (shield with a spark): one inline SVG, used on the login page and in the sidebar.
const LOGO_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="M12 8l1 2.6 2.6 1-2.6 1L12 15l-1-2.4-2.6-1 2.6-1z"/></svg>';
const avatar = (name, size = 32) => {
  const ini = String(name || "?").trim().split(/\s+/).slice(-2).map((w) => w[0]).join("").toUpperCase();
  let h = 0; for (const ch of String(name)) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return `<span class="avatar" aria-hidden="true" style="width:${size}px;height:${size}px;background:${COLORS[h % COLORS.length]}">${esc(ini)}</span>`;
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
  t.className = "toast " + kind; t.setAttribute("role", kind === "bad" ? "alert" : "status");
  t.innerHTML = icon(kind === "bad" ? "info" : "check") + "<span></span>"; t.lastChild.textContent = msg;
  const gone = () => t.remove();
  t.onclick = gone;
  $("#toasts").appendChild(t);
  setTimeout(gone, kind === "bad" ? 6000 : 4000);
}

// Keyboard + focus handling shared by modal() and drawer(): Esc closes, Tab stays inside, focus returns.
const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),summary,[tabindex]:not([tabindex="-1"])';
function trapFocus(root, close) {
  const back = document.activeElement;
  const onKey = (e) => {
    if (e.key === "Escape") { e.stopPropagation(); close(); return; }
    if (e.key !== "Tab") return;
    const f = $$(FOCUSABLE, root).filter((x) => x.offsetParent !== null);
    if (!f.length) { e.preventDefault(); return; }
    const first = f[0], last = f[f.length - 1];
    if (e.shiftKey && (document.activeElement === first || !root.contains(document.activeElement))) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && (document.activeElement === last || !root.contains(document.activeElement))) { e.preventDefault(); first.focus(); }
  };
  document.addEventListener("keydown", onKey, true);
  return () => { document.removeEventListener("keydown", onKey, true); if (back && back.isConnected) back.focus?.(); };
}

function modal({ title, body, actions = [], wide = false }) {
  const ov = document.createElement("div");
  ov.className = "overlay";
  ov.innerHTML = `<div class="modal" role="dialog" aria-modal="true" aria-label="${esc(title)}" ${wide ? 'style="max-width:720px"' : ""}>
    <div class="card-h"><h3>${esc(title)}</h3><span style="flex:1"></span><button class="btn icon ghost" data-close aria-label="Đóng">${icon("x")}</button></div>
    <div class="card-b">${body}</div>
    ${actions.length ? `<div class="modal-f">${actions.map((a, i) => `<button class="btn ${a.primary ? "primary" : ""}" data-act="${i}">${esc(a.label)}</button>`).join("")}</div>` : ""}</div>`;
  let release = () => {};
  const close = () => { release(); ov.remove(); };
  ov.addEventListener("mousedown", (e) => { if (e.target === ov) close(); });
  ov.addEventListener("click", (e) => { if (e.target.closest("[data-close]")) close(); });
  actions.forEach((a, i) => ov.querySelector(`[data-act="${i}"]`).onclick = async () => { if ((await a.onClick?.(ov)) !== false) close(); });
  document.body.appendChild(ov);
  release = trapFocus(ov.firstElementChild, close);
  ov.querySelector("input,select,textarea,button:not([data-close])")?.focus();
  return ov;
}

function drawer(title, html) {
  $(".drawer")?.remove(); $(".drawer-ov")?.remove();
  const ov = document.createElement("div"); ov.className = "overlay drawer-ov"; ov.style.background = "var(--overlay-soft)";
  const d = document.createElement("aside"); d.className = "drawer"; d.setAttribute("role", "dialog"); d.setAttribute("aria-modal", "true"); d.setAttribute("aria-label", title);
  d.innerHTML = `<div class="card-h"><h3>${esc(title)}</h3><span style="flex:1"></span><button class="btn icon ghost" aria-label="Đóng">${icon("x")}</button></div><div class="card-b"></div>`;
  let release = () => {};
  const close = () => { release(); d.remove(); ov.remove(); };
  ov.onclick = close; d.querySelector(".card-h button").onclick = close;
  document.body.append(ov, d);
  release = trapFocus(d, close);
  d.querySelector(".card-b").innerHTML = html;
  d.querySelector(".card-h button").focus();
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

// Open a cited file: the backend checks this account's access with SharePoint first and only then
// returns a link (Microsoft 365: the file's own URL, which SharePoint checks against the same SSO
// login again; demo: a single-use ticket to the view-only viewer). No public or shareable link is ever shown.
async function openFile(id) {
  const w = window.open("", "_blank");
  if (w) { w.opener = null; w.document.title = "Đang kiểm tra quyền…";
    w.document.body.setAttribute("style", "font:15px system-ui,sans-serif;display:grid;place-items:center;height:100vh;margin:0;color:#667085");
    w.document.body.textContent = "Đang kiểm tra quyền truy cập…"; }
  try {
    const r = await post(`/api/files/${encodeURIComponent(id)}/link`, {});
    if (w) w.location.replace(r.url); else location.assign(r.url);
  } catch (e) { if (w) w.close(); toast(e.message, "bad"); }
}
document.addEventListener("click", (e) => {
  const b = e.target.closest && e.target.closest("[data-open]");
  if (b) { e.preventDefault(); openFile(b.dataset.open); }
});

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
  CHAT = []; CONVS = []; CUR = null;
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
      <div class="login-logo"><span class="logo-mark">${LOGO_SVG}</span> Data Room AI</div>
      <div>
        <h1>Trợ lý AI cho Data Room IPO, đúng quyền của từng nhà đầu tư.</h1>
        <p class="lead">CT Group · Data Room phục vụ thẩm định đợt chào bán lần đầu</p>
        <div class="login-points">
          <div>${icon("shield")}<span><b>4 cổng phân quyền</b>RLS, hỏi lại SharePoint, tập thu hồi, kiểm danh tính — sai ở đâu cũng đóng an toàn.</span></div>
          <div>${icon("spark")}<span><b>Trả lời có trích dẫn nguyên văn</b>Mọi ý được kiểm chứng với tài liệu gốc trước khi hiển thị.</span></div>
          <div>${icon("lock")}<span><b>Chạy hoàn toàn on-prem</b>Model, OCR và dữ liệu ở trên máy này; không gửi ra ngoài.</span></div>
        </div>
      </div>
      <div class="login-foot">Bản demo · dữ liệu giả lập · không dùng cho giao dịch thật</div>
    </section>
    <main class="login-panel" id="main-login">
      <div class="login-card">
        <div class="login-brand-m"><span class="logo-mark">${LOGO_SVG}</span> Data Room AI</div>
        <h2>Đăng nhập</h2>
        <div class="muted">Dùng tài khoản được mời vào Data Room (Entra ID giả lập).</div>
        <form id="login-form" novalidate>
          ${message ? `<div class="alert info">${esc(message)}</div>` : ""}
          <div class="alert bad hidden" id="login-err" role="alert"></div>
          <label class="field">Email<input class="input" id="email" type="email" autocomplete="username" required placeholder="ten@congty.com" aria-describedby="login-err"></label>
          <label class="field">Mật khẩu
            <span class="pw-wrap"><input class="input" id="password" type="password" autocomplete="current-password" required aria-describedby="login-err">
            <button type="button" class="btn ghost sm" id="pw-toggle" aria-label="Hiện mật khẩu" aria-pressed="false">${icon("eye")}</button></span></label>
          <button class="btn primary" id="login-btn" type="submit" style="height:40px">Đăng nhập</button>
        </form>
        <details class="demo-acc">
          <summary>Tài khoản demo</summary>
          <p class="small muted" style="margin:8px 0 0">Chọn một tài khoản để điền sẵn email. Mật khẩu demo nằm trong file <span class="mono">data/tenant/DEMO_ACCOUNTS.md</span>.</p>
          <div class="demo-list" id="demo-list"><div class="muted small">Đang tải…</div></div>
        </details>
      </div>
    </main>
  </div>`;
  $("#pw-toggle").onclick = () => {
    const p = $("#password"), show = p.type === "password"; p.type = show ? "text" : "password";
    $("#pw-toggle").setAttribute("aria-pressed", String(show)); $("#pw-toggle").setAttribute("aria-label", show ? "Ẩn mật khẩu" : "Hiện mật khẩu");
  };
  $("#login-form").onsubmit = async (e) => {
    e.preventDefault();
    const btn = $("#login-btn"), err = $("#login-err");
    err.classList.add("hidden"); btn.disabled = true; btn.innerHTML = '<span class="spinner" aria-hidden="true"></span> Đang đăng nhập…';
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
      <div class="login-logo"><span class="logo-mark">${LOGO_SVG}</span> Data Room AI</div>
      <div><h1>Trợ lý AI cho Data Room IPO, đúng quyền của từng nhà đầu tư.</h1>
        <p class="lead">Đăng nhập bằng tài khoản được mời vào Data Room trên SharePoint.</p></div>
      <div class="login-foot">Quyền truy cập do SharePoint và Entra ID quyết định</div>
    </section>
    <main class="login-panel" id="main-login"><div class="login-card">
      <div class="login-brand-m"><span class="logo-mark">${LOGO_SVG}</span> Data Room AI</div>
      <h2>Đăng nhập</h2>
      <div class="muted">Dùng tài khoản Microsoft (Entra ID) mà Ban IPO đã mời. Có thể được yêu cầu xác thực đa yếu tố.</div>
      ${message ? `<div class="alert info" style="margin-top:16px">${esc(message)}</div>` : ""}
      <button class="btn primary" id="ms-login" style="height:42px;width:100%;margin-top:20px">${icon("lock")} Đăng nhập bằng tài khoản Microsoft</button>
    </div></main>
  </div>`;
  $("#ms-login").onclick = () => MSAL.loginRedirect({ scopes: [AUTH.scope] });
  $("#ms-login").focus();
}

// ------------------------------------------------------------------ shell + router
const NAV = [
  { sec: "Tài liệu", items: [
    { id: "search", label: "Tìm hồ sơ", icon: "search", who: "user" },
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
  chat: ["Hỏi đáp", ""],
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
const visibleNav = (i) => i.who === "admin" ? isAdmin()
  : i.who === "reviewer" ? !isAdmin() && (ME.roles || []).includes("Reviewer") : !isAdmin();

// ------------------------------------------------------------------ conversations (this session only)
// Kept in memory, never in browser storage: answers quote confidential documents, and a stored copy
// would outlive a permission change and stay on shared computers.
let CONVS = [];            // [{id, title, items: [message]}], newest first
let CHAT = [];             // messages of the open conversation
let CUR = null;
function newConversation() {
  if (CHAT.some((m) => !m.r)) return;
  CUR = null; CHAT = [];
  closePanel();
  if (!location.hash.startsWith("#/chat")) location.hash = "#/chat"; else pageChat($("#page"));
  updateRecent();
}
function openConversation(id) {
  const c = CONVS.find((x) => x.id === id); if (!c || CHAT.some((m) => !m.r)) return;
  CUR = c.id; CHAT = c.items;
  closePanel();
  if (!location.hash.startsWith("#/chat")) location.hash = "#/chat"; else pageChat($("#page"));
  updateRecent();
  $("#sidebar").classList.remove("open");
}
function updateRecent() {
  const el = $("#sb-recent"); if (!el) return;
  el.innerHTML = CONVS.length ? CONVS.map((c) => `<button data-c="${c.id}" class="${c.id === CUR ? "active" : ""}" title="${esc(c.title)}"${c.id === CUR ? ' aria-current="true"' : ""}>
      <span>${esc(c.title)}</span></button>`).join("")
    : '<div class="sb-empty">Các cuộc trò chuyện trong phiên này sẽ hiện ở đây</div>';
  $$("button", el).forEach((b) => b.onclick = () => openConversation(b.dataset.c));
}

// Sidebar state: desktop = collapsible column, <= 900px = off-canvas drawer (class "open" + scrim).
// A closed sidebar is made inert so Tab never walks into hidden links.
const MOBILE_MQ = window.matchMedia("(max-width: 900px)");
let SHELL_KEYS = false;
function syncSidebar() {
  const sb = $("#sidebar"), sh = $("#shell"); if (!sb || !sh) return;
  const open = MOBILE_MQ.matches ? sb.classList.contains("open") : !sh.classList.contains("sb-collapsed");
  sb.inert = !open; sb.setAttribute("aria-hidden", String(!open));
  $("#menu")?.setAttribute("aria-expanded", String(MOBILE_MQ.matches && open));
  $("#sb-open")?.setAttribute("aria-expanded", String(open));
  $("#sb-toggle")?.setAttribute("aria-expanded", String(open));
}
function closeSidebarDrawer(refocus) {
  const sb = $("#sidebar"); if (!sb || !sb.classList.contains("open")) return;
  sb.classList.remove("open"); syncSidebar(); if (refocus) $("#menu")?.focus();
}
function setTheme(t) {
  document.documentElement.dataset.theme = t; store.set("dr-theme", t);
  const b = $("#theme"); if (!b) return;
  b.innerHTML = icon(t === "dark" ? "sun" : "moon"); b.setAttribute("aria-pressed", String(t === "dark"));
  const label = t === "dark" ? "Chuyển sang giao diện sáng" : "Chuyển sang giao diện tối";
  b.title = label; b.setAttribute("aria-label", label);
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", t === "dark" ? "#1d1d1b" : "#faf9f5");
}

function renderShell() {
  const dark = document.documentElement.dataset.theme === "dark";
  $("#app").innerHTML = `
  <a class="skip-link" href="#page">Bỏ qua đến nội dung chính</a>
  <div class="shell ${store.get("dr-sb") === "0" ? "sb-collapsed" : ""}" id="shell">
    <aside class="sidebar" id="sidebar" aria-label="Thanh bên">
      <div class="sb-brand"><span class="sb-logo">${LOGO_SVG}</span><div><b>Data Room AI</b><small>CT Group · IPO</small></div>
        <button class="btn icon ghost sb-toggle" id="sb-toggle" title="Thu gọn thanh bên (Ctrl+B)" aria-label="Thu gọn thanh bên" aria-controls="sidebar" aria-expanded="true">${icon("panel")}</button></div>
      ${isAdmin() ? "" : `<button class="sb-new" id="new-chat" title="Cuộc trò chuyện mới (Ctrl+Shift+O)">${icon("edit")}<span>Cuộc trò chuyện mới</span></button>`}
      <nav class="sb-nav" aria-label="Điều hướng">${NAV.map((s) => {
        const items = s.items.filter(visibleNav);
        return items.length ? `<div class="sb-sec">${s.sec}</div>` + items.map((i) =>
          `<a href="#/${i.id}" data-id="${i.id}"><span class="sb-ico">${icon(i.icon)}</span><span>${i.label}</span></a>`).join("") : "";
      }).join("")}
        ${isAdmin() ? "" : '<div class="sb-sec">Gần đây</div><div class="sb-recent" id="sb-recent"></div>'}</nav>
      <div class="sb-user">${avatar(ME.name, 32)}<div class="who"><b>${esc(ME.name)}</b><small>${esc(roleLabel())}</small></div>
        <button class="btn icon ghost" id="theme" aria-pressed="${dark}"></button>
        <button class="btn icon ghost" id="logout" title="Đăng xuất" aria-label="Đăng xuất">${icon("logout")}</button></div>
    </aside>
    <div class="sb-scrim" id="sb-scrim"></div>
    <div class="main">
      <header class="topbar" id="topbar">
        <button class="btn icon ghost menu-btn" id="menu" aria-label="Mở menu" aria-controls="sidebar" aria-expanded="false">${icon("menu")}</button>
        <button class="btn icon ghost sb-open" id="sb-open" title="Mở thanh bên (Ctrl+B)" aria-label="Mở thanh bên" aria-controls="sidebar">${icon("panel")}</button>
        <div class="tb-title"><h1 id="page-title"></h1><div class="sub" id="page-sub"></div></div>
        <span class="spacer"></span>
        <div class="pills" id="pills" role="status" aria-label="Trạng thái hệ thống"></div>
      </header>
      <main id="page" tabindex="-1"></main>
    </div>
    <aside class="panel" id="panel" aria-label="Nguồn và kiểm chứng"></aside>
  </div>`;
  $("#logout").onclick = () => logout();
  const nc = $("#new-chat"); if (nc) nc.onclick = newConversation;
  updateRecent();
  setTheme(dark ? "dark" : "light");
  const sb = $("#sidebar");
  $("#menu").onclick = () => { sb.classList.toggle("open"); syncSidebar(); if (sb.classList.contains("open")) ($("a.active", sb) || $("a,button", sb))?.focus(); };
  $("#sb-scrim").onclick = () => closeSidebarDrawer(true);
  const toggle = () => {
    const c = $("#shell").classList.toggle("sb-collapsed"); store.set("dr-sb", c ? "0" : "1"); syncSidebar();
    (c ? $("#sb-open") : $("#sb-toggle"))?.focus();
  };
  $("#sb-toggle").onclick = toggle; $("#sb-open").onclick = toggle;
  $("#theme").onclick = () => setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
  // any code that adds/removes "open" (e.g. picking a conversation) keeps inert/aria in step
  new MutationObserver(syncSidebar).observe(sb, { attributes: true, attributeFilter: ["class"] });
  MOBILE_MQ.addEventListener?.("change", syncSidebar);
  syncSidebar();
  if (!SHELL_KEYS) {
    SHELL_KEYS = true;
    document.addEventListener("keydown", (e) => {
      if (!ME || !$("#shell")) return;
      if (e.key === "Escape") {
        if ($(".overlay")) return;            // an open modal/drawer handles its own Esc
        if ($("#sidebar").classList.contains("open")) { closeSidebarDrawer(true); return; }
        closePanel();
      }
      if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key.toLowerCase() === "o" && !isAdmin()) { e.preventDefault(); newConversation(); }
      if ((e.metaKey || e.ctrlKey) && !e.shiftKey && !e.altKey && e.key.toLowerCase() === "b" && !MOBILE_MQ.matches) { e.preventDefault(); $("#shell").classList.contains("sb-collapsed") ? $("#sb-open").click() : $("#sb-toggle").click(); }
    });
  }
}

function route() {
  if (!ME) return;
  const def = isAdmin() ? "perms" : "chat";
  let id = (location.hash.replace(/^#\/?/, "") || def).split("?")[0];
  const navIds = NAV.flatMap((s) => s.items).filter(visibleNav).map((i) => i.id);
  const allowed = isAdmin() ? navIds : ["chat", ...navIds];
  if (!allowed.includes(id)) { id = def; history.replaceState(null, "", "#/" + id); }
  else if (!location.hash) history.replaceState(null, "", "#/" + id);   // an answer is drawn only on #/chat
  $$(".sb-nav a").forEach((a) => { const on = a.dataset.id === id; a.classList.toggle("active", on); if (on) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current"); });
  closeSidebarDrawer();
  closePanel();
  const [t, sub] = TITLES[id];
  $("#page-title").textContent = id === "chat" ? chatTitle() : t; $("#page-sub").textContent = sub;
  $("#topbar").classList.toggle("chat-top", id === "chat");
  document.title = `${id === "chat" ? chatTitle() : t} · Data Room AI`;
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

// ------------------------------------------------------------------ status pills (admin)
async function pollStatus() {
  if (!TOKEN || !ME || !isAdmin()) return;
  try { STATUS_CACHE = await api("/api/status"); } catch { return; }
  const s = STATUS_CACHE, age = (k) => s.feeds[k] ?? 1e9;
  const p = (txt, cls, title = "") => `<span class="chip ${cls}" title="${esc(title)}"><i class="dot" aria-hidden="true"></i>${txt}</span>`;
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
const SUGGEST = [   // [label, question, group needed (null = everyone), staff only]
  ["Tài chính", "Doanh thu thuần năm 2025 của Sao Mai là bao nhiêu?", null],
  ["Tổng hợp", "Tóm tắt các nội dung chính của bản cáo bạch", null],
  ["Liệt kê", "Sao Mai có những nhà máy nào, công suất bao nhiêu?", null],
  ["Thỏa thuận", "Phí thu xếp áp dụng cho nhóm quỹ trong nước là bao nhiêu?", "DR-INV-A"],
  ["Thỏa thuận", "Tỷ lệ room ngoại dành riêng cho Nhóm B là bao nhiêu?", "DR-INV-B"],
  ["Thỏa thuận", "Nhà đầu tư chiến lược được đề cử bao nhiêu thành viên HĐQT?", "DR-INV-C"],
  ["Nội bộ", "Khoản dự phòng tranh chấp với nhà thầu là bao nhiêu?", null, true],
  ["Nguyên văn", "Trích nguyên văn điều khoản thanh toán trong hợp đồng mua bán điện", null],
  ["English", "What was Sao Mai's net revenue in 2025?", null],
];
const mySuggestions = () => {
  const staff = (ME.roles || []).includes("Staff.AI");
  return SUGGEST.filter(([, , grp, staffOnly]) => staff ? true : !staffOnly && (!grp || (ME.groups || []).includes(grp))).slice(0, 6);
};
const MODE_LABEL = { fact: "Trả lời nhanh", summary: "Tổng hợp", compare: "So sánh", list: "Liệt kê", full: "Nguyên văn" };
// live status line while answering: server step name -> what the user reads
const STAGE_TEXT = { search: "Đang tìm trong tài liệu bạn được phép xem", live: "Đang hỏi lại SharePoint bằng tài khoản của bạn",
  llm: "Đang đọc tài liệu và soạn câu trả lời", context: "Đang hiểu câu hỏi theo ngữ cảnh cuộc trò chuyện", verify: "Đang kiểm chứng trích dẫn và con số", queue: "Đang chờ lượt xử lý" };
const STEP_TEXT = [["Cổng 4", "Đã xác nhận danh tính và quyền dùng AI"], ["Cổng 1+3", "Đã lọc tài liệu theo quyền của bạn"],
  ["Lớp đầu vào", "Đã kiểm tra an toàn câu hỏi"], ["Câu hỏi nối tiếp", "Đã hiểu câu hỏi theo ngữ cảnh"], ["Tổng hợp cuộc trò chuyện", "Đã gom các nội dung đã trao đổi"],
  ["Phân loại", "Đã xác định kiểu câu trả lời"], ["Tìm kiếm", "Đã tìm tài liệu liên quan"],
  ["Đọc toàn bộ", "Đã mở tài liệu được nêu tên"], ["Rerank", "Đã xếp hạng đoạn liên quan nhất"],
  ["Cổng 2 – kiểm tra trực tiếp", "SharePoint đã xác nhận quyền mở từng file"], ["Chọn câu", "Đã chọn câu liên quan"],
  ["LLM", "Đã soạn câu trả lời"], ["Kiểm chứng", "Đã đối chiếu trích dẫn nguyên văn"], ["Kiểm tra đúng trọng tâm", "Đã kiểm tra đúng trọng tâm"],
  ["NLI", "Đã chấm độ khớp ý"], ["Chỉ mục dữ kiện", "Đã tra cứu trực tiếp trong tài liệu"],
  ["Phát hiện tài liệu ghi số liệu khác", "Đã đối chiếu số liệu với tài liệu khác"], ["Cổng 2 + 4", "Đã kiểm tra quyền lần cuối"]];
function onProgress(m, ev) {
  if (ev.stage) m.now = STAGE_TEXT[ev.stage] || m.now;
  if (ev.step) {
    const t = STEP_TEXT.find(([p]) => ev.step.startsWith(p));
    m.steps.push({ text: t ? t[1] : ev.step, ms: Date.now() - m.t0, ok: ev.ok });
  }
  const el = $("#ans-" + CHAT.indexOf(m)); if (el && !m.r) el.innerHTML = renderThinking(m);
}
const chatTitle = () => (CONVS.find((c) => c.id === CUR) || {}).title || "Cuộc trò chuyện mới";
const greeting = () => { const h = new Date().getHours(); return h < 11 ? "Chào buổi sáng" : h < 14 ? "Chào buổi trưa" : h < 18 ? "Chào buổi chiều" : "Chào buổi tối"; };

function composerHTML(canAI, hero) {
  return `<form class="composer-box ${hero ? "hero-box" : ""}" id="ask">
      <label class="sr-only" for="q">Câu hỏi</label>
      <textarea id="q" rows="${hero ? 2 : 1}" placeholder="${canAI ? "Hỏi về tài liệu trong Data Room…" : "Tài khoản của bạn chưa được cấp quyền dùng trợ lý AI"}" ${canAI ? "" : "disabled"}></textarea>
      <div class="cb-row">
        ${ME.roles.includes("Staff.AI") ? `<select id="scope-site" class="cb-select" title="Giới hạn phạm vi tìm"><option value="">Mọi site được phép</option>${(ME.sites || []).map((s) => `<option value="${s.id}">${esc(s.name)}</option>`).join("")}</select>` : '<span class="cb-hint">Tự chọn trả lời nhanh, tổng hợp, so sánh, liệt kê hay nguyên văn theo câu hỏi</span>'}
        <span class="spacer"></span>
        <button class="send" id="send" type="submit" aria-label="Gửi" ${canAI ? "" : "disabled"}>${icon("arrowUp")}</button>
      </div>
    </form>`;
}

function pageChat(page) {
  const canAI = ME.roles.some((r) => r === "Investor.AI" || r === "Staff.AI");
  $("#page-title").textContent = chatTitle();
  if (!CHAT.length) {
    page.innerHTML = `<div class="chat empty-chat"><div class="welcome">
        <div class="wl-mark">${icon("spark")}</div>
        <h2>${greeting()}, ${esc(ME.name.split(" ").slice(-1)[0])}</h2>
        <p>Hỏi về tài liệu trong Data Room bằng tiếng Việt (có dấu hoặc không dấu) hoặc tiếng Anh. Mọi câu trả lời chỉ dùng tài liệu bạn có quyền xem và luôn kèm trích dẫn.</p>
        ${composerHTML(canAI, true)}
        ${canAI ? `<div class="suggest-h">Thử hỏi</div><div class="suggest">${mySuggestions().map(([tag, s]) => `<button type="button" data-q="${esc(s)}"><small>${tag}</small><span>${esc(s)}</span></button>`).join("")}</div>`
          : '<div class="notice bad">' + icon("lock") + '<div>Tài khoản của bạn chưa được cấp quyền dùng trợ lý AI. Vui lòng liên hệ Ban IPO.</div></div>'}
      </div></div>`;
    $$(".suggest button", page).forEach((b) => b.onclick = () => ask(b.dataset.q));
  } else {
    page.innerHTML = `<div class="chat">
      <div class="thread" id="thread"><div class="thread-inner" id="thread-inner"></div></div>
      <div class="composer"><div class="composer-inner">${composerHTML(canAI, false)}
        <div class="disclaimer">Trợ lý chỉ dùng tài liệu bạn có quyền xem trên SharePoint. Hãy đối chiếu trích dẫn trước khi ra quyết định.</div>
      </div></div></div>`;
    renderThread();
  }
  const q = $("#q");
  const grow = () => { q.style.height = "auto"; q.style.height = Math.min(q.scrollHeight, 220) + "px"; };
  q.addEventListener("input", grow);
  q.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); $("#ask").requestSubmit(); } });
  $("#ask").onsubmit = (e) => { e.preventDefault(); ask(q.value.trim()); };
  if (canAI) q.focus();
}

function renderThread() {
  const inner = $("#thread-inner");
  if (!inner) return;
  inner.innerHTML = CHAT.map((m, i) => `<div class="msg-user" id="q-${i}"><div class="bubble">${esc(m.q)}</div></div>
    <div class="msg-ai" id="ans-${i}">${m.r ? renderAnswer(m.r, i) : renderThinking(m)}</div>`).join("");
  CHAT.forEach((m, i) => { if (m.r) wireAnswer($("#ans-" + i), i); });
  const th = $("#thread"); if (th) th.scrollTop = th.scrollHeight;
}

const secs = (ms) => (ms / 1000).toFixed(1).replace(".", ",") + " s";
function renderThinking(m) {
  const now = Date.now() - (m.t0 || Date.now());
  const idx = CHAT.indexOf(m);
  const last = m.steps.length ? m.steps[m.steps.length - 1] : null;
  return `<details class="thinking progress" ${m.open === false ? "" : "open"} ontoggle="CHAT[${idx}] && (CHAT[${idx}].open = this.open)">
      <summary role="status" aria-live="polite"><span class="pulse"></span><span class="shimmer">${esc(m.now || "Đang kiểm tra quyền truy cập")}</span>
        <span class="muted small th-elapsed" data-elapsed>${secs(now)}</span>${icon("chevron", "chev")}</summary>
      <ol class="think-steps">${m.steps.map((s, k) => `<li class="${s.ok === false ? "bad" : ""}">${icon(s.ok === false ? "x" : "check")}<span>${esc(s.text)}</span><span class="muted small">${secs(s.ms)}</span></li>`).join("")}${
        last ? `<li class="doing"><span class="pulse sm"></span><span>${esc(m.now || "Đang xử lý")}…</span></li>` : ""}</ol>
    </details>`;
}

const CONFLICT_RE = /^Lưu ý: tài liệu khác ghi\s*/;
const isConflict = (c) => CONFLICT_RE.test(c.text || "");
const FACT_STEP = "Chỉ mục dữ kiện: trả lời bằng tra cứu";
const FOLLOWUPS = ["Trích nguyên văn đoạn liên quan", "Giải thích chi tiết hơn", "Còn tài liệu nào khác nói về nội dung này không?"];

// One reading of an answer: prose for one claim, bullets for several, quotes for full text.
function answerBody(r, i, animate) {
  let w = 0;
  const words = (t) => animate ? t.split(/(\s+)/).map((x) => x.trim() ? `<span class="w" style="animation-delay:${Math.min(900, (w++) * 18)}ms">${esc(x)}</span>` : x).join("") : esc(t);
  const refs = (c) => c.refs.map((n) => `<button class="ref" data-n="${n}" title="${esc((r.citations.find((x) => x.n === n) || {}).name || "")}" aria-label="Nguồn ${n}">${n}</button>`).join("");
  const flag = (c) => {
    const n = (c.refs || [])[0], cit = r.citations.find((x) => x.n === n);
    const go = (label, cls) => n ? `<button type="button" class="flag ${cls}" data-n="${n}" title="Mở nguồn${cit && cit.crop ? " và ảnh trang gốc" : ""} để đối chiếu">${label}</button>` : `<span class="flag ${cls}">${label}</span>`;
    return (c.ocr_doubt || []).length ? " " + go(`${icon("eye")} số đọc từ ảnh, nên kiểm tra: ${esc(c.ocr_doubt.join(", "))}`, "ocr")
      : c.uncertain ? ' <span class="flag" title="Điểm khớp ý thấp — hãy đọc câu trích">chưa chắc, nên kiểm tra</span>' : "";
  };
  const normal = r.claims.filter((c) => !isConflict(c)), conflicts = r.claims.filter(isConflict);
  const warn = conflicts.length ? `<div class="conflict" role="note"><svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg><div><b>Tài liệu khác ghi số liệu khác</b>
      ${conflicts.map((c) => `<p>${esc(c.text.replace(CONFLICT_RE, "").replace(/^./, (x) => x.toUpperCase()))}${refs(c)}</p>`).join("")}
      <small>Hãy đối chiếu các nguồn trước khi dùng số liệu.</small></div></div>` : "";
  let main;
  if (r.verbatim) main = `<div class="quotes">${normal.map((c) => `<blockquote>${words(c.text.replace(/^“|”$/g, ""))}${refs(c)}${flag(c)}</blockquote>`).join("")}</div>`;
  else if (normal.length === 1) main = `<p class="prose">${words(normal[0].text)}${refs(normal[0])}${flag(normal[0])}</p>`;
  else if (normal.length) main = `<ul class="prose">${normal.map((c) => `<li>${words(c.text)}${refs(c)}${flag(c)}</li>`).join("")}</ul>`;
  else main = "";
  return main + warn;
}

function renderAnswer(r, i) {
  const notice = (cls, ic, text) => `<div class="notice ${cls}">${icon(ic)}<div>${esc(text)}</div></div>`;
  const meta = [r.mode && MODE_LABEL[r.mode], r.lang === "en" ? "English" : "", r.elapsed_ms ? secs(r.elapsed_ms) : "",
    r.audit_seq ? `nhật ký #${r.audit_seq}` : ""].filter(Boolean).join(" · ");
  const traceBtn = (r.trace || []).length ? `<button class="act" data-trace title="Các bước kiểm tra quyền và kiểm chứng">${icon("shield")}<span>Chi tiết kiểm tra</span></button>` : "";
  if (r.sensitive) return notice("warm", "users", r.message) + `<div class="actions">${traceBtn}<span class="meta">${esc(meta)}</span></div>`;
  if (r.out_of_scope) return notice("cool", "lock", r.message) + `<div class="actions">${traceBtn}<span class="meta">${esc(meta)}</span></div>`;
  if (r.refused) return `<p class="prose muted-prose">${esc(r.message)}</p><div class="actions">${traceBtn}<span class="meta">${esc(meta)}</span></div>`;
  if (r.pending_review) return notice("warm", "users", r.message) + `<div class="muted small">Mã bản nháp #${r.draft_id} · trang này tự cập nhật khi có kết quả duyệt</div>`;
  const m = typeof i === "number" ? CHAT[i] : null;
  const animate = !!(m && m.fresh);
  const chips = [r.approved ? `<span class="chip ok">${icon("check")} Ban IPO đã duyệt${r.edited ? " · có hiệu đính" : ""}</span>` : "",
    r.withdrawn ? `<span class="chip warn" title="Quyền của bạn đã thay đổi sau khi duyệt">${r.withdrawn} ý đã rút lại</span>` : "",
    (r.trace || []).some((s) => String(s.step).startsWith(FACT_STEP)) ? `<span class="chip brand" title="Số liệu được tra thẳng từ chỉ mục dữ kiện của tài liệu, không do mô hình AI viết lại">${icon("search")} Tra cứu trực tiếp từ tài liệu</span>` : "",
    r.recap ? `<span class="chip">${icon("check")} Tổng hợp từ cuộc trò chuyện</span>` : "",
    r.standalone_question && !r.recap ? `<span class="chip" title="Câu hỏi nối tiếp được hiểu theo ngữ cảnh">Hiểu là: ${esc(r.standalone_question)}</span>` : ""].join("");
  const sources = `<div class="sources"><span class="src-label">Nguồn</span>${r.citations.map((c) =>
    `<button class="src" data-n="${c.n}" title="${esc(c.name)} · ${esc(c.locator)}"><b>${c.n}</b>${ftype((c.name.split(".").pop() || "").toLowerCase())}<span>${esc(c.name)}</span></button>`).join("")}</div>`;
  const fb = r.audit_seq && !r.approved ? `<button class="act ${m && m.fb === "up" ? "on" : ""}" data-fb="up" title="Câu trả lời đúng" aria-label="Đúng">${icon("thumbUp")}</button>
      <button class="act ${m && m.fb === "down" ? "on" : ""}" data-fb="down" title="Câu trả lời sai" aria-label="Sai">${icon("thumbDown")}</button>` : "";
  const follow = m && m === CHAT[CHAT.length - 1] && !r.approved && (r.citations || []).length
    ? `<div class="followups"><span class="src-label">Hỏi tiếp</span>${FOLLOWUPS.map((q) => `<button type="button" data-q="${esc(q)}">${esc(q)}</button>`).join("")}</div>` : "";
  return `${chips ? `<div class="chips">${chips}</div>` : ""}<div class="answer ${animate ? "reveal" : ""}">${answerBody(r, i, animate)}</div>
    ${r.notice ? notice("warm small-notice", "users", r.notice) : ""}${sources}
    <div class="actions"><button class="act labeled" data-copy title="Sao chép câu trả lời kèm nguồn" aria-label="Sao chép câu trả lời">${icon("copy")}<span>Sao chép</span></button>${fb}${traceBtn}<span class="meta">${esc(meta)}</span></div>${follow}`;
}

// ------------------------------------------------------------------ sources / checks panel
let PANEL = null;    // {i, tab, n}
function closePanel() { PANEL = null; const p = $("#panel"); if (p) { p.innerHTML = ""; } $("#shell")?.classList.remove("panel-open"); }
function openPanel(i, tab, n) {
  const m = typeof i === "number" ? CHAT[i] : null;
  if (!m || !m.r) return;
  PANEL = { i, tab, n };
  const r = m.r, p = $("#panel");
  const tabs = `<div class="pn-tabs">${(r.citations || []).length ? `<button data-tab="src" class="${tab === "src" ? "active" : ""}">Nguồn (${r.citations.length})</button>` : ""}
    <button data-tab="trace" class="${tab === "trace" ? "active" : ""}">Các bước kiểm tra (${(r.trace || []).length})</button>
    <span class="spacer"></span><button class="btn icon ghost" id="pn-close" aria-label="Đóng">${icon("x")}</button></div>`;
  const src = (r.citations || []).map((c) => `<div class="pn-src ${c.n === n ? "focus" : ""}" id="pn-${c.n}">
      <div class="cite-top"><span class="cite-n">${c.n}</span>${ftype((c.name.split(".").pop() || "").toLowerCase())}<span class="cite-name" title="${esc(c.name)}">${esc(c.name)}</span></div>
      <div class="cite-loc">${esc(SITE_LABEL[c.site_id] || c.site_id)} · ${esc(c.locator)}${c.ocr ? " · bản scan (OCR)" : ""}</div>
      <blockquote>${esc(c.quote)}</blockquote>
      ${c.crop ? `<figure class="crop"><img loading="lazy" alt="Vùng tương ứng trên bản scan gốc" src="/crop/${encodeURIComponent(c.item_id)}?ticket=${encodeURIComponent(c.crop.ticket || "")}&page=${encodeURIComponent(c.crop.page)}${c.crop.box ? "&box=" + c.crop.box.join(",") : ""}"><figcaption>${c.crop.box ? "Vùng gốc trên bản scan (đã nắn thẳng)" : "Trang scan gốc (đã nắn thẳng)"}</figcaption></figure>` : ""}
      <button class="btn sm" data-open="${esc(c.item_id)}" title="Hệ thống kiểm tra quyền của tài khoản bạn rồi mới cho xem file (chỉ xem, không tải về)">${icon("file")} Xem file ${icon("ext")}</button>
    </div>`).join("");
  const trace = `<ol class="steps">${(r.trace || []).map((s) => {
    const { step, ok, ms, ...rest } = s;
    const d = Object.entries(rest).filter(([, v]) => v !== null && v !== "" && !(Array.isArray(v) && !v.length)).map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`).join(" · ");
    return `<li><span class="s-dot ${ok ? "" : "bad"}">${ok ? "✓" : "✕"}</span><span>${esc(step)}</span><span class="muted small">${ms} ms</span>${d ? `<span class="s-d">${esc(d)}</span>` : ""}</li>`;
  }).join("")}</ol>`;
  p.innerHTML = tabs + `<div class="pn-body">${tab === "src" ? src : trace}</div>`;
  $("#shell").classList.add("panel-open");
  $("#pn-close").onclick = closePanel;
  $$(".pn-tabs [data-tab]", p).forEach((b) => b.onclick = () => openPanel(i, b.dataset.tab, n));
  $$(".crop img", p).forEach((im) => { im.onclick = () => im.parentElement.classList.toggle("big"); im.onerror = () => im.parentElement.remove(); });
  if (tab === "src" && n) { const el = $("#pn-" + n); if (el) el.scrollIntoView({ block: "start", behavior: "smooth" }); }
}

function answerText(r) {
  const body = r.claims.map((c) => (r.claims.length > 1 ? "• " : "") + c.text + c.refs.map((n) => ` [${n}]`).join("")).join("\n");
  const src = r.citations.map((c) => `[${c.n}] ${c.name} — ${c.locator}`).join("\n");
  return body + (src ? "\n\nNguồn:\n" + src : "");
}

function wireAnswer(el, i) {
  if (!el) return;
  const m = typeof i === "number" ? CHAT[i] : null;
  $$("[data-fb]", el).forEach((b) => b.onclick = async () => {
    if (!m || !m.r || m.fb) return;
    const note = b.dataset.fb === "down" ? (prompt("Câu trả lời sai ở đâu? (không bắt buộc)") || "") : "";
    try { await post("/api/feedback", { audit_seq: m.r.audit_seq, rating: b.dataset.fb, note }); m.fb = b.dataset.fb;
      $$("[data-fb]", el).forEach((x) => x.classList.toggle("on", x.dataset.fb === m.fb)); toast("Cảm ơn phản hồi của bạn"); }
    catch (e) { toast(e.message, "bad"); }
  });
  $$("[data-copy]", el).forEach((b) => b.onclick = async () => {
    try { await navigator.clipboard.writeText(answerText(m.r)); b.innerHTML = icon("check") + "<span>Đã chép</span>"; setTimeout(() => { b.innerHTML = icon("copy") + "<span>Sao chép</span>"; }, 1400); }
    catch { toast("Không sao chép được", "bad"); }
  });
  $$("[data-q]", el).forEach((b) => b.onclick = () => ask(b.dataset.q));
  $$(".ref, .src, .flag[data-n]", el).forEach((b) => b.onclick = () => openPanel(i, "src", Number(b.dataset.n)));
  $$("[data-trace]", el).forEach((b) => b.onclick = () => openPanel(i, "trace"));
  if (m && m.fresh) setTimeout(() => { m.fresh = false; }, 1200);
}

async function ask(q, extra = {}) {      // extra: { item_id } for the summary of a picked document
  if (!q || CHAT.some((m) => !m.r)) return;
  if (!CUR) {                                   // first question opens a conversation
    const c = { id: "c" + Date.now(), title: q.length > 60 ? q.slice(0, 57) + "…" : q, items: CHAT };
    CONVS.unshift(c); CUR = c.id; updateRecent();
    $("#page-title").textContent = c.title;
  }
  const m = { q, steps: [], t0: Date.now(), now: "Đang kiểm tra quyền truy cập" }; CHAT.push(m);
  if (!$("#thread")) pageChat($("#page")); else { const input = $("#q"); if (input) { input.value = ""; input.style.height = "auto"; } renderThread(); }
  const send = $("#send"); if (send) send.disabled = true;
  const timer = setInterval(() => {      // elapsed-time counter only; the steps come from the server
    const e = $(`#ans-${CHAT.indexOf(m)} [data-elapsed]`); if (e && !m.r) e.textContent = secs(Date.now() - m.t0);
  }, 100);
  try {
    m.r = await postStream("/api/chat/stream", { question: q, scope_site: $("#scope-site")?.value || null,
                                                 conversation_id: CUR, ...extra },
                           (ev) => onProgress(m, ev));
    m.r.elapsed_ms = Date.now() - m.t0;
    m.fresh = true;
    if (m.r.pending_review) watchDrafts();
  } catch (e) {
    m.r = { refused: true, message: "Không gửi được câu hỏi: " + e.message, trace: [] };
  } finally {
    clearInterval(timer);
    if (CHAT.includes(m) && location.hash.startsWith("#/chat")) renderThread();
    const s2 = $("#send"); if (s2) s2.disabled = false;
    $("#q")?.focus();
  }
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

// ---- admin & review helpers (part 4)
const fmtTime = (iso) => { try { return new Date(iso).toLocaleString("vi-VN"); } catch { return iso || ""; } };
// Confirmation dialog for anything destructive: says exactly what changes, runs onOk only after the click.
function confirmDo({ title, lines = [], label = "Xác nhận", danger = true, onOk }) {
  const ov = modal({ title, body: `<ul class="cf-list">${lines.map((l) => `<li>${l}</li>`).join("")}</ul>`,
    actions: [{ label: "Hủy" }, { label, primary: true, onClick: async () => { try { await onOk(); } catch { return false; } } }] });
  if (danger) ov.querySelector('[data-act="1"]')?.classList.add("danger-fill");
  return ov;
}

// ------------------------------------------------------------------ sensitive-question drafts (asker)
async function pageDrafts(page) {
  page.innerHTML = '<div class="card empty">Đang tải…</div>';
  const mine = await api("/api/my/drafts");
  if (!mine.length) {
    page.innerHTML = `<div class="card empty rv-empty">${icon("shield")}<b>Bạn chưa có câu hỏi nào cần duyệt.</b>
      <span>Câu hỏi thuộc chủ đề nhạy cảm sẽ được gửi cho Ban IPO và hiện ở đây cùng trạng thái duyệt.</span></div>`; return;
  }
  const ST = { pending: ["Đang chờ duyệt", "warn"], approved: ["Đã duyệt", "ok"], rejected: ["Không phát hành", "bad"] };
  const cnt = (s) => mine.filter((d) => d.status === s).length;
  let flt = "all";
  const draw = () => {
    const rows = mine.map((d, k) => [d, k]).filter(([d]) => flt === "all" || d.status === flt);
    page.innerHTML = `<div class="rv-summary" role="tablist">
        <button role="tab" data-f="all" class="${flt === "all" ? "active" : ""}"><b>${mine.length}</b> Tất cả</button>
        ${Object.entries(ST).map(([k, [l, c]]) => `<button role="tab" data-f="${k}" class="${flt === k ? "active" : ""}"><b class="${c}">${cnt(k)}</b> ${l}</button>`).join("")}</div>
      ${rows.map(([d, k]) => `<div class="card rv-draft" style="margin-bottom:14px"><div class="card-h">
        <span class="chip ${ST[d.status][1]}">${ST[d.status][0]}</span><h3 style="flex:1">${esc(d.question)}</h3>
        <span class="muted small">#${d.draft_id} · ${fmtTime(d.created_at)}</span></div>
        <div class="card-b"><div class="chips">${d.topics.map((t) => `<span class="chip">${esc(t)}</span>`).join("")}</div>
        ${d.status === "pending" ? `<p class="muted">${icon("info")} Ban IPO đang xem xét. Câu trả lời sẽ hiện ở đây sau khi được duyệt.</p>`
          : `<div class="a-card" id="ans-d${k}">${renderAnswer(draftToAnswer(d), "d" + k)}</div>`}</div></div>`).join("") || '<div class="card empty">Không có câu hỏi ở trạng thái này.</div>'}`;
    $$("[data-f]", page).forEach((b) => b.onclick = () => { flt = b.dataset.f; draw(); });
    rows.forEach(([d, k]) => { const el = $("#ans-d" + k); if (el) wireAnswer(el, "d" + k); });
  };
  draw();
}

// ------------------------------------------------------------------ reviewer
let REVIEW_TAB = "pending";
async function pageReview(page) {
  const TABS = [["pending", "Chờ duyệt"], ["approved", "Đã duyệt"], ["rejected", "Đã từ chối"]];
  page.innerHTML = `<div class="subtabs" role="tablist">${TABS.map(([k, l]) => `<button role="tab" data-t="${k}" class="${REVIEW_TAB === k ? "active" : ""}">${l} <span class="chip" data-cnt="${k}">…</span></button>`).join("")}</div>
    <div id="rq"><div class="card empty">Đang tải…</div></div>`;
  $$(".subtabs button", page).forEach((b) => b.onclick = () => { REVIEW_TAB = b.dataset.t; pageReview(page); });
  // counts per status (the queue API is per status; the other tabs load in the background)
  TABS.filter(([k]) => k !== REVIEW_TAB).forEach(([k]) => api("/api/review/drafts?status=" + k)
    .then((r) => { const c = $(`[data-cnt="${k}"]`, page); if (c) c.textContent = r.length; }).catch(() => {}));
  let q;
  try { q = await api("/api/review/drafts?status=" + REVIEW_TAB); }
  catch (e) { $("#rq").innerHTML = `<div class="card empty">${esc(e.message)}</div>`; return; }
  const own = $(`[data-cnt="${REVIEW_TAB}"]`, page); if (own) own.textContent = q.length;
  if (!q.length) { $("#rq").innerHTML = `<div class="card empty rv-empty">${icon("check")}<b>${REVIEW_TAB === "pending" ? "Không còn bản nháp nào chờ duyệt." : "Chưa có bản nháp nào ở mục này."}</b></div>`; return; }
  const ext = (n) => (n.split(".").pop() || "").toLowerCase();
  const SL = { pending: ["Chờ duyệt", "warn"], approved: ["Đã duyệt", "ok"], rejected: ["Đã từ chối", "bad"] };
  $("#rq").innerHTML = q.map((d) => `<div class="card review" data-id="${d.draft_id}" style="margin-bottom:16px">
    <div class="card-h">${avatar(d.asker.name, 28)}<div style="flex:1"><b>${esc(d.asker.name)}</b> <span class="muted small">${esc(d.asker.org)} · #${d.draft_id} · ${fmtTime(d.created_at)}</span></div>
      <div class="chips">${d.topics.map((t) => `<span class="chip warn">${esc(t)}</span>`).join("")}${d.lang === "en" ? '<span class="chip info">EN</span>' : ""}
      <span class="chip ${SL[d.status][1]}">${SL[d.status][0]}</span></div></div>
    ${!d.visible ? `<div class="card-b"><div class="alert bad">${icon("lock")} ${esc(d.reason)} — bản nháp bị ẩn để không lộ tài liệu ngoài quyền của bạn.</div></div>`
    : `<div class="rv-cols">
      <section class="rv-col"><h4>1. Câu hỏi</h4><div class="rv-q">${esc(d.question)}</div>
        <p class="muted small">Người hỏi: ${esc(d.asker.name)}${d.asker.org ? " — " + esc(d.asker.org) : ""}</p></section>
      <section class="rv-col"><h4>2. Bản nháp trả lời</h4>
        <p class="muted small" style="margin-top:0">${d.status === "pending" ? "Mỗi ý có thể sửa lời; xóa trắng một ý để bỏ ý đó. Nguồn trích dẫn không đổi." : "Nội dung đã chốt."}</p>
        ${d.answer.claims.map((c, n) => `<label class="field">Ý ${n + 1} <span class="muted small">nguồn [${c.refs.join(", ")}]</span>
          <textarea class="input" rows="3" data-claim="${n}" data-orig="${esc(c.text)}" ${d.status !== "pending" ? "disabled" : ""}>${esc(c.text)}</textarea></label>`).join("")}</section>
      <section class="rv-col"><h4>3. Nguồn trích dẫn <span class="chip">${d.answer.citations.length}</span></h4>
        ${d.answer.citations.map((c) => `<div class="cite"><div class="cite-top"><span class="cite-n">${c.n}</span>${ftype(ext(c.name))}<span class="cite-name">${esc(c.name)}</span></div>
          <div class="cite-loc">${esc(c.locator)}</div><blockquote>${esc(c.quote)}</blockquote>
          <button class="linkbtn" data-open="${esc(c.item_id)}">Xem file ${icon("ext")}</button></div>`).join("") || '<p class="muted small">Không có trích dẫn.</p>'}</section></div>
    <div class="rv-foot">${d.status === "pending" ? `<input class="input" data-note placeholder="Ghi chú (tùy chọn khi duyệt; bắt buộc khi từ chối)" aria-label="Ghi chú" style="flex:1;max-width:none">
        <span class="chip warn hidden" data-edited>${icon("edit")} Đã chỉnh sửa</span>
        <button class="btn ghost hidden" data-undo>${icon("refresh")} Hoàn tác sửa</button>
        <button class="btn danger" data-act="reject">${icon("x")} Từ chối…</button>
        <button class="btn primary" data-act="approve">${icon("check")} Duyệt & phát hành</button>`
      : `<span class="muted small">${d.status === "approved" ? "Đã duyệt" : "Đã từ chối"} bởi ${esc(d.reviewer || "")}${d.note ? " · Ghi chú: " + esc(d.note) : ""}</span>`}</div>`}
    </div>`).join("");
  $$(".review[data-id]", page).forEach((card) => {
    if (!$("[data-act]", card)) return;
    const draft = q.find((x) => String(x.draft_id) === card.dataset.id);
    const areas = $$("[data-claim]", card);
    const edited = () => areas.some((t) => t.value !== t.dataset.orig);
    const sync = () => {
      const e = edited();
      $("[data-edited]", card).classList.toggle("hidden", !e); $("[data-undo]", card).classList.toggle("hidden", !e);
      $('[data-act="approve"]', card).innerHTML = `${icon("check")} ${e ? "Duyệt bản đã sửa" : "Duyệt nguyên văn"}`;
    };
    areas.forEach((t) => t.oninput = sync);
    $("[data-undo]", card).onclick = () => { areas.forEach((t) => t.value = t.dataset.orig); sync(); };
    sync();
    const send = async (body, okMsg) => {
      try { await post(`/api/review/drafts/${card.dataset.id}`, body); toast(okMsg); pageReview(page); }
      catch (e) { toast(e.message, "bad"); throw e; }
    };
    $('[data-act="approve"]', card).onclick = () => {
      const claims = areas.map((t) => t.value);
      if (!claims.some((c) => c.trim())) return toast("Cần giữ lại ít nhất một ý để phát hành. Nếu không phát hành, hãy chọn Từ chối.", "bad");
      const kept = claims.filter((c) => c.trim()).length;
      confirmDo({ title: "Duyệt và phát hành?", danger: false, label: "Duyệt & phát hành", lines: [
        `Câu trả lời (${kept}/${claims.length} ý${edited() ? ", có chỉnh sửa lời" : ", nguyên văn"}) sẽ hiện ngay cho <b>${esc(draft.asker.name)}</b>.`,
        "Nguồn trích dẫn giữ nguyên. Quyết định được ghi vào nhật ký." ],
        onOk: () => send({ action: "approve", note: $("[data-note]", card).value || null, claims }, "Đã duyệt và phát hành") });
    };
    $('[data-act="reject"]', card).onclick = () => {
      const ov = modal({ title: "Từ chối phát hành?", body: `<p>Người hỏi <b>${esc(draft.asker.name)}</b> sẽ nhận thông báo “Ban IPO không phát hành câu trả lời” kèm lý do bên dưới.</p>
        <label class="field">Lý do từ chối (bắt buộc)<textarea class="input" id="rj-reason" rows="3" maxlength="500">${esc($("[data-note]", card).value)}</textarea></label>
        <p class="small" id="rj-err" style="color:var(--bad);min-height:18px;margin:6px 0 0"></p>`,
        actions: [{ label: "Hủy" }, { label: "Từ chối phát hành", primary: true, onClick: async (o) => {
          const reason = $("#rj-reason", o).value.trim();
          if (!reason) { $("#rj-err", o).textContent = "Vui lòng nhập lý do từ chối."; $("#rj-reason", o).focus(); return false; }
          try { await send({ action: "reject", note: reason }, "Đã từ chối"); } catch { return false; }
        } }] });
      ov.querySelector('[data-act="1"]').classList.add("danger-fill");
    };
  });
}

// ------------------------------------------------------------------ search
let SEARCH_Q = "", SEARCH_SITE = "", SEARCH_KIND = "", SEARCH_RES = null;
const KIND_LABEL = { pdf: "PDF", word: "Word", excel: "Excel", slide: "PowerPoint", email: "Email", image: "Ảnh" };
function highlight(text, terms) {
  let out = esc(text);
  for (const t of terms || []) {
    if (t.length < 3) continue;
    out = out.replace(new RegExp(`(${esc(t).replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "gi"), "<mark>$1</mark>");
  }
  return out;
}
const fmtSize = (b) => !b ? "" : b < 1024 ? b + " B" : b < 1048576 ? Math.round(b / 1024) + " KB" : (b / 1048576).toFixed(1) + " MB";
// A summary of one picked document, in a new conversation (same contract as before: ask(label, { item_id, lang })).
// The summary is in the interface language (<html lang>, Vietnamese until the UI is bilingual);
// the browser language is not used: many Vietnamese users browse with an English browser.
function summariseFile(itemId, name) {
  const lang = (document.documentElement.lang || "vi").toLowerCase().startsWith("en") ? "en" : "vi";
  const label = lang === "en" ? `Summary of: ${name}` : `Tóm tắt tài liệu: ${name}`;
  newConversation(); setTimeout(() => ask(label, { item_id: itemId, lang }), 50);
}
async function pageSearch(page) {
  // arriving from the viewer's "Tóm tắt tài liệu" button: #/search?summary=<item_id>&name=<file name>
  const hq = new URLSearchParams(location.hash.split("?")[1] || "");
  if (hq.get("summary")) {
    const id = hq.get("summary"), nm = hq.get("name") || "";
    history.replaceState(null, "", "#/search");
    if (ME.features?.doc_summary) { summariseFile(id, nm); return; }
    toast("Tài khoản của bạn chưa được dùng tính năng tóm tắt tài liệu", "bad");
  }
  const chip = (attr, v, label, cur) => `<button type="button" class="fchip ${v === cur ? "on" : ""}" data-${attr}="${esc(v)}" aria-pressed="${v === cur}">${esc(label)}</button>`;
  page.innerHTML = `<form class="sform" id="sform"><div class="toolbar" style="margin-bottom:8px"><div class="search" style="flex:1;max-width:none">${icon("search")}
      <input class="input" id="sq" autocomplete="off" aria-label="Tìm tài liệu" placeholder="Từ khóa, mô tả nội dung hoặc một phần tên file — ví dụ: biên bản họp HĐQT, thoa-thuan…" value="${esc(SEARCH_Q)}"></div>
      <button class="btn primary" type="submit">Tìm</button></div>
    <div class="fchips" role="group" aria-label="Site"><span class="fl">Site</span>${chip("fsite", "", "Tất cả", SEARCH_SITE)}${(ME.sites || []).map((s) => chip("fsite", s.id, s.name, SEARCH_SITE)).join("")}</div>
    <div class="fchips" role="group" aria-label="Loại file"><span class="fl">Loại file</span>${chip("fkind", "", "Tất cả", SEARCH_KIND)}${Object.entries(KIND_LABEL).map(([k, v]) => chip("fkind", k, v, SEARCH_KIND)).join("")}</div>
  </form><div id="sres" aria-live="polite"></div>`;
  const run = async () => {
    SEARCH_Q = $("#sq").value.trim();
    if (!SEARCH_Q && !SEARCH_SITE && !SEARCH_KIND) { SEARCH_RES = null; draw(); return; }
    const qs = new URLSearchParams({ q: SEARCH_Q });
    if (SEARCH_SITE) qs.set("site", SEARCH_SITE);
    if (SEARCH_KIND) qs.set("kind", SEARCH_KIND);
    $("#sres").innerHTML = '<div class="card empty"><span class="spinner"></span> Đang tìm…</div>';
    try { SEARCH_RES = await api("/api/search?" + qs); } catch (ex) { SEARCH_RES = { refused: true, message: ex.message }; }
    draw();
  };
  const draw = () => {
    const r = SEARCH_RES;
    $$(".fchip[data-fsite]").forEach((b) => { const on = b.dataset.fsite === SEARCH_SITE; b.classList.toggle("on", on); b.setAttribute("aria-pressed", on); });
    $$(".fchip[data-fkind]").forEach((b) => { const on = b.dataset.fkind === SEARCH_KIND; b.classList.toggle("on", on); b.setAttribute("aria-pressed", on); });
    const empty = (ic, t, sub) => `<div class="card empty sr-empty">${icon(ic)}<b>${esc(t)}</b>${sub ? `<span>${esc(sub)}</span>` : ""}</div>`;
    if (!r) { $("#sres").innerHTML = empty("search", "Tìm tài liệu trong phạm vi của bạn", "Nhập từ khóa, mô tả nội dung hoặc một phần tên file — không cần nhớ chính xác tên. Hoặc chọn site / loại file để xem danh sách."); return; }
    if (r.refused) { $("#sres").innerHTML = empty("lock", r.message || "Không thể tìm kiếm", "Bạn chỉ thấy tài liệu trong phạm vi được cấp quyền."); return; }
    if (!r.results.length) { $("#sres").innerHTML = empty("folder", "Không tìm thấy tài liệu phù hợp trong phạm vi của bạn", "Thử từ khóa ngắn hơn, bỏ bớt bộ lọc, hoặc mô tả nội dung thay vì tên file. Tài liệu ngoài phạm vi truy cập sẽ không hiển thị."); return; }
    $("#sres").innerHTML = `<p class="muted small sr-count"><b>${r.results.length}</b> tài liệu trong phạm vi của bạn <span class="kbd-hint">· ↑ ↓ chọn, Enter để xem</span></p><div class="sr-list" role="list">` + r.results.map((x) => {
      const crumb = String(x.path || "").split(/[\\/]/).filter(Boolean);
      const meta = [x.label, x.locator, fmtSize(x.size)].filter(Boolean);
      return `<div class="card sr" role="listitem" tabindex="0" data-row="${esc(x.item_id)}" aria-label="${esc(x.name)}">
      <div class="cite-top">${ftype(x.ext)}<b class="cite-name">${highlight(x.name, r.terms)}</b><span class="chip">${esc(x.site_name || SITE_LABEL[x.site_id] || x.site_id)}</span>
        ${(x.match || []).includes("name") ? '<span class="chip brand">khớp tên</span>' : ""}${x.ocr ? '<span class="chip info">bản scan</span>' : ""}</div>
      <div class="sr-crumb muted small">${icon("folder")}${crumb.length ? crumb.map((c) => `<span>${esc(c)}</span>`).join("") : "<span>(gốc)</span>"}${meta.length ? `<em>${esc(meta.join(" · "))}</em>` : ""}</div>
      ${x.snippet ? `<p class="snip">${highlight(x.snippet, r.terms)}</p>` : ""}
      <div class="cite-foot"><button class="btn sm primary" data-open="${esc(x.item_id)}" title="Chỉ xem, không tải về">${icon("eye")} Xem file</button>
        ${ME.features?.doc_summary ? `<button class="btn sm" data-summary="${esc(x.item_id)}" data-name="${esc(x.name)}">${icon("spark")} Tóm tắt tài liệu</button>` : ""}
        <button class="btn sm ghost" data-askabout="${esc(x.name)}">${icon("chat")} Hỏi về tài liệu này</button></div></div>`;
    }).join("") + "</div>";
    $$("[data-askabout]").forEach((b) => b.onclick = () => { location.hash = "#/chat"; setTimeout(() => { const q = $("#q"); if (q) { q.value = `Tài liệu ${b.dataset.askabout} nói gì về `; q.focus(); } }, 50); });
    $$("[data-summary]").forEach((b) => b.onclick = () => summariseFile(b.dataset.summary, b.dataset.name));
  };
  $("#sform").onsubmit = (e) => { e.preventDefault(); run(); };
  $$(".fchip[data-fsite]").forEach((b) => b.onclick = () => { SEARCH_SITE = b.dataset.fsite; run(); });
  $$(".fchip[data-fkind]").forEach((b) => b.onclick = () => { SEARCH_KIND = b.dataset.fkind; run(); });
  // keyboard: ↓ from the box into the list, ↑/↓ between results, Enter opens (view only), Esc back to the box
  page.onkeydown = (e) => {
    const rows = $$(".sr[data-row]", page), i = rows.indexOf(document.activeElement);
    if (e.key === "ArrowDown" && (i >= 0 || document.activeElement === $("#sq")) && rows.length) { e.preventDefault(); rows[Math.min(rows.length - 1, i + 1)].focus(); }
    else if (e.key === "ArrowUp" && i >= 0) { e.preventDefault(); if (i === 0) $("#sq").focus(); else rows[i - 1].focus(); }
    else if (e.key === "Enter" && i >= 0 && e.target === rows[i]) { e.preventDefault(); openFile(rows[i].dataset.row); }
    else if (e.key === "Escape" && i >= 0) $("#sq").focus();
  };
  draw();
  $("#sq").focus();
}

// ------------------------------------------------------------------ scope
let SCOPE_FILTER = null, SCOPE_Q = "", SCOPE_OPEN = {};   // SCOPE_OPEN: site/folder key -> open? (kept across redraws)
function scopeStats(sc) {
  const c = sc.counts;
  return [["all", "Mở được trên SharePoint", sc.sharepoint_total, ""], ["ai_ok", "AI truy xuất được", c.ai_ok || 0, "ok"],
    ["excluded", "Không cho AI", c.excluded || 0, "warn"], ["encrypted", "Mã hóa", c.encrypted || 0, "bad"], ["malware", "Mã độc", c.malware || 0, "bad"],
    ["ai_blocked", "AI đang chặn", c.ai_blocked || 0, "warn"], ["pending", "Đang nạp", c.pending || 0, ""], ["unsupported", "Không đọc được", c.unsupported || 0, ""]];
}
function renderTree(sc, filter, q) {
  q = (q || "").toLowerCase();
  const searching = !!(filter || q);                         // while filtering, show what matched: everything open
  const isOpen = (key, dflt) => searching ? true : (key in SCOPE_OPEN ? SCOPE_OPEN[key] : dflt);
  return sc.sites.map((s) => {
    const all = s.folders.flatMap((f) => f.files);
    const ai = all.filter((x) => x.status === "ai_ok").length;
    let shown = 0;
    const folders = s.folders.map((f, fi) => {
      const files = f.files.filter((x) => (!filter || x.status === filter) && (!q || x.name.toLowerCase().includes(q)));
      if (!files.length) return "";
      shown += files.length;
      const fai = f.files.filter((x) => x.status === "ai_ok").length;
      const key = s.site + "/" + (f.path || "");
      const depth = Math.min(4, Math.max(0, (f.path || "").split(/[\\/]/).filter(Boolean).length - 1));
      return `<details class="folder" data-key="${esc(key)}" ${isOpen(key, fi < 3) ? "open" : ""} style="--d:${depth}"><summary class="folder-h">${icon("chevron", "chev")}${icon("folder")} <span class="fp">${esc(f.path || "(gốc)")}</span>
        <span class="cnt" title="File AI dùng được / tổng số file trong thư mục">${fai}/${f.files.length}</span></summary>${files.map((x) => {
        const [lab, cls] = STATUS[x.status] || [x.status, ""];
        return `<div class="file">${ftype(x.ext)}<span class="name" title="${esc(x.name)}">${esc(x.name)}</span><span class="chip ${cls}">${lab}</span><span class="det">${esc(x.detail || "")}</span></div>`;
      }).join("")}</details>`;
    }).join("");
    if (!folders) return "";
    const key = "site:" + s.site;
    return `<details class="card site-block" data-key="${esc(key)}" ${isOpen(key, true) ? "open" : ""}><summary>${icon("chevron", "chev")}${icon("globe")} ${esc(s.name)} <span class="chip">${s.site}</span>
      <span class="muted small" style="font-weight:500">${ai}/${all.length} file AI dùng được${searching ? ` · ${shown} khớp` : ""}</span>
      <span class="bar"><span style="width:${all.length ? Math.round(ai / all.length * 100) : 0}%"></span></span></summary>${folders}</details>`;
  }).join("") || '<div class="card empty">Không có tài liệu phù hợp với bộ lọc hiện tại.</div>';
}

let SCOPE_USER = null;
async function pageScope(page) {
  if (!DIR) await loadDir();
  SCOPE_USER = SCOPE_USER || DIR.users[0]?.oid;
  page.innerHTML = `<div class="toolbar"><label class="field" style="margin:0;flex:1;max-width:420px">Người dùng
      <select class="input" id="scope-user">${DIR.users.map((u) => `<option value="${u.oid}" ${u.oid === SCOPE_USER ? "selected" : ""}>${esc(u.name)} — ${esc(u.org)}</option>`).join("")}</select></label>
      <div class="chips" id="scope-who" style="align-self:flex-end"></div></div>
    <div class="stats" id="stats"></div>
    <div class="toolbar"><div class="search">${icon("search")}<input class="input" id="sq" placeholder="Tìm theo tên file…" aria-label="Tìm theo tên file" value="${esc(SCOPE_Q)}"></div>
    <button class="btn sm" id="scope-exp" type="button">Mở hết</button><button class="btn sm" id="scope-col" type="button">Thu gọn hết</button>
    <span class="muted small" id="scope-note"></span></div><div id="tree"><div class="card empty">Đang tải…</div></div>`;
  $("#scope-user").onchange = (e) => { SCOPE_USER = e.target.value; SCOPE_OPEN = {}; pageScope(page); };
  const sc = await api("/api/scope_of/" + encodeURIComponent(SCOPE_USER));
  $("#scope-who").innerHTML = sc.groups.map((g) => `<span class="chip brand">${esc(GROUP_LABEL[g] || g)}</span>`).join("")
    + sc.roles.map((r) => `<span class="chip info">${esc(ROLE_LABEL[r] || r)}</span>`).join("");
  const draw = () => {
    $("#stats").innerHTML = scopeStats(sc).map(([k, l, v, cls]) => `<button class="stat ${cls} ${(SCOPE_FILTER || "all") === k ? "sel" : ""}" data-k="${k}" aria-pressed="${(SCOPE_FILTER || "all") === k}"><div class="v">${v}</div><div class="l">${l}</div></button>`).join("");
    $$("#stats .stat").forEach((b) => b.onclick = () => { SCOPE_FILTER = b.dataset.k === "all" ? null : b.dataset.k; draw(); });
    $("#tree").innerHTML = renderTree(sc, SCOPE_FILTER, SCOPE_Q);
    $$("#tree details[data-key]").forEach((d) => d.addEventListener("toggle", () => { SCOPE_OPEN[d.dataset.key] = d.open; }));
    $("#scope-note").innerHTML = sc.violations_ai_without_sharepoint.length
      ? `<span class="chip bad">VI PHẠM: AI thấy ${sc.violations_ai_without_sharepoint.length} file SharePoint không cho mở</span>`
      : `${icon("check")} Không có tài liệu nào AI thấy mà SharePoint không cho mở`;
  };
  const setAll = (v) => { $$("#tree details[data-key]").forEach((d) => { d.open = v; SCOPE_OPEN[d.dataset.key] = v; }); };
  $("#scope-exp").onclick = () => setAll(true);
  $("#scope-col").onclick = () => setAll(false);
  $("#sq").oninput = (e) => { SCOPE_Q = e.target.value; draw(); };
  draw();
}

// ------------------------------------------------------------------ permissions (admin)
let PERM_TAB = "users", DIR = null, PERM_SITE = "COMMON", PERM_FOLDER = null, USER_Q = "", USER_TYPE = "", USER_GROUP = "";
let MX_SITE = "", MX_Q = "", MX_UNIQUE = false, MX_DEPTH = 1;
const MX_CAP = 300;
const uname = (oid) => DIR?.users.find((u) => u.oid === oid)?.name || oid;
const gname = (gid) => GROUP_LABEL[gid] || DIR?.groups.find((g) => g.id === gid)?.name || gid;
const gshort = (gid) => (GROUP_LABEL[gid] ? GROUP_LABEL[gid].replace(/^Nhóm /, "") : String(gid).split("-").pop());
const principal = (g) => g.kind === "group" ? `${icon("users")} ${esc(gname(g.id))}` : g.kind === "user" ? `${icon("user")} ${esc(uname(g.id))}`
  : g.kind === "link_specific" ? `${icon("ext")} Link cho ${esc(uname(g.id))}` : `${icon("globe")} Link ${g.kind === "link_anyone" ? "Anyone" : "tổ chức"} (bị bỏ qua)`;
const SP_NOTE = "AI chặn ngay; SharePoint áp thay đổi sau một khoảng trễ (mặc định 60 giây).";

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
      ${[["users", "Người dùng"], ["groups", "Nhóm"], ["pmatrix", "Ma trận thư mục × nhóm"], ["folders", "Thư mục & tài liệu"], ["sites", "Site & RAC"]].map(([k, l]) => `<button role="tab" data-t="${k}" class="${PERM_TAB === k ? "active" : ""}">${l}</button>`).join("")}</div>
      <button class="btn" id="restore">${icon("refresh")} Khôi phục bản gốc</button></div>
    <div id="perm-body"><div class="card empty">Đang tải…</div></div>`;
  $$(".subtabs button", page).forEach((b) => b.onclick = () => { PERM_TAB = b.dataset.t; pagePerms(page); });
  $("#restore").onclick = () => confirmDo({ title: "Khôi phục phân quyền gốc?", label: "Khôi phục bản gốc", lines: [
    "Mọi thay đổi <b>người dùng, nhóm, quyền thư mục/tài liệu và AI_Use</b> sẽ quay về như lúc sinh dữ liệu.",
    "Người được mời thêm, nhóm đã đổi và quyền riêng đã cấp sẽ mất.", "Nhật ký vẫn được giữ nguyên." ],
    onOk: async () => { await post("/api/admin/restore", {}).catch((e) => { toast(e.message, "bad"); throw e; }); toast("Đã khôi phục bản gốc"); await loadDir(); pagePerms(page); } });
  try { await loadDir(); } catch (e) { $("#perm-body").innerHTML = `<div class="card empty">${esc(e.message)}</div>`; return; }
  ({ users: permUsers, groups: permGroups, pmatrix: permMatrix, folders: permFolders, sites: permSites })[PERM_TAB]($("#perm-body"));
}

// ---- matrix: folders (rows) x groups (columns), read / no access, inherited vs unique
async function permMatrix(el) {
  el.innerHTML = '<div class="card empty">Đang tải ma trận…</div>';
  let trees;
  try { trees = await Promise.all(DIR.sites.map((s) => api("/api/admin/tree/" + s.id))); }
  catch (e) { el.innerHTML = `<div class="card empty">${esc(e.message)}</div>`; return; }
  if (!MX_SITE || !DIR.sites.some((s) => s.id === MX_SITE)) MX_SITE = "";
  const draw = () => {
    const q = MX_Q.trim().toLowerCase();
    // rows = folders cut at depth MX_DEPTH (0 = every folder that holds files); a parent row aggregates the folders under it
    const map = new Map();
    DIR.sites.forEach((s, i) => {
      if (MX_SITE && s.id !== MX_SITE) return;
      trees[i].folders.forEach((f) => {
        if (q && !f.path.toLowerCase().includes(q)) return;
        if (MX_UNIQUE && !f.unique) return;
        const seg = f.path.split("/"), key = MX_DEPTH ? seg.slice(0, MX_DEPTH).join("/") : f.path, id = s.id + "\u0000" + key;
        if (!map.has(id)) map.set(id, { s, key, leaves: [] });
        map.get(id).leaves.push(f);
      });
    });
    const all = [...map.values()].sort((x, y) => x.key.localeCompare(y.key, "vi", { numeric: true }));
    const rows = all.slice(0, MX_CAP), multi = DIR.sites.length > 1;
    const cell = (r, g) => {
      const n = r.leaves.filter((f) => f.grants.some((x) => x.kind === "group" && x.id === g.id)).length, tot = r.leaves.length;
      const nm = esc(gname(g.id));
      if (n && r.s.rac && !r.s.groups.includes(g.id)) return `<span class="mx-badge rac" title="${nm}: có quyền thư mục nhưng không thuộc nhóm RAC của site, nên bị chặn">${icon("lock")} RAC</span>`;
      if (n === tot) return `<span class="mx-badge ok" title="${nm}: đọc được${tot > 1 ? " mọi thư mục con (" + tot + ")" : ""}">${icon("check")} Đọc</span>`;
      if (n) return `<span class="mx-badge part" title="${nm}: đọc được ${n}/${tot} thư mục con">${n}/${tot}</span>`;
      return `<span class="mx-badge no" title="${nm}: không có quyền">—</span>`;
    };
    el.innerHTML = `<div class="toolbar">
        <div class="search">${icon("search")}<input class="input" id="mx-q" placeholder="Lọc thư mục…" value="${esc(MX_Q)}" aria-label="Lọc thư mục"></div>
        ${multi ? `<select class="input" id="mx-site" aria-label="Site" style="max-width:220px"><option value="">Tất cả site</option>${DIR.sites.map((s) => `<option value="${esc(s.id)}" ${s.id === MX_SITE ? "selected" : ""}>${esc(s.name)}</option>`).join("")}</select>` : ""}
        <select class="input" id="mx-depth" aria-label="Cấp thư mục" style="max-width:190px">${[[1, "Thư mục cấp 1 (01–07)"], [2, "Tới cấp 2"], [3, "Tới cấp 3"], [0, "Từng thư mục chứa file"]].map(([v, l]) => `<option value="${v}" ${MX_DEPTH === v ? "selected" : ""}>${l}</option>`).join("")}</select>
        <label class="mx-check"><input type="checkbox" id="mx-uniq" ${MX_UNIQUE ? "checked" : ""}> Chỉ quyền riêng</label>
        <span style="flex:1"></span><span class="muted small">${all.length > rows.length ? `Hiển thị ${rows.length}/${all.length} dòng — lọc để thu hẹp` : `${all.length} dòng`}</span></div>
      <div class="mx-legend"><span class="mx-badge ok">${icon("check")} Đọc</span> nhóm đọc được
        <span class="mx-badge part">2/3</span> chỉ một phần thư mục con
        <span class="mx-badge no">—</span> không có quyền
        <span class="mx-badge rac">${icon("lock")} RAC</span> có quyền nhưng nhóm không thuộc site (RAC chặn)
        <span class="chip warn">riêng</span> có thư mục đã tách kế thừa · <span class="chip">kế thừa</span> toàn bộ theo cấp trên. Bấm một dòng để sửa quyền.</div>
      ${rows.length ? `<div class="card tw-scroll"><table class="t mx-perm"><thead><tr><th>Thư mục</th>${DIR.groups.map((g) => `<th class="c" title="${esc(gname(g.id))}"><b>${esc(gshort(g.id))}</b><div class="mx-gn">${esc(gname(g.id))}</div></th>`).join("")}<th class="c">Người dùng riêng</th></tr></thead><tbody>
        ${rows.map((r, k) => { const uq = r.leaves.filter((f) => f.unique).length, users = new Set(r.leaves.flatMap((f) => f.grants.filter((x) => x.kind === "user").map((x) => x.id)));
          return `<tr class="click" data-k="${k}"><td><div class="mx-folder">${icon("folder")}<span title="${esc(r.key)}">${esc(r.key)}</span>
            ${uq ? `<span class="chip warn">riêng${r.leaves.length > 1 ? " " + uq + "/" + r.leaves.length : ""}</span>` : '<span class="chip">kế thừa</span>'}
            ${r.leaves.length > 1 ? `<span class="muted small">${r.leaves.length} thư mục con</span>` : ""}${multi ? `<span class="muted small">${esc(r.s.name)}</span>` : ""}</div></td>
          ${DIR.groups.map((g) => `<td class="c ${uq ? "uq" : ""}">${cell(r, g)}</td>`).join("")}
          <td class="c">${users.size ? `<span class="chip info" title="${[...users].map((x) => esc(uname(x))).join(", ")}">+${users.size}</span>` : '<span class="muted">—</span>'}</td></tr>`; }).join("")}
        </tbody></table></div>` : '<div class="card empty">Không có thư mục nào khớp bộ lọc.</div>'}`;
    $("#mx-q").oninput = (e) => { MX_Q = e.target.value; const p = e.target.selectionStart; draw(); const n = $("#mx-q"); n.focus(); n.setSelectionRange(p, p); };
    $("#mx-site")?.addEventListener("change", (e) => { MX_SITE = e.target.value; draw(); });
    $("#mx-depth").onchange = (e) => { MX_DEPTH = +e.target.value; draw(); };
    $("#mx-uniq").onchange = (e) => { MX_UNIQUE = e.target.checked; draw(); };
    $$("tr[data-k]", el).forEach((tr) => tr.onclick = () => {
      const r = rows[+tr.dataset.k];
      PERM_SITE = r.s.id; PERM_FOLDER = (r.leaves.find((f) => f.unique) || r.leaves[0]).path; PERM_TAB = "folders"; pagePerms($("#page"));
    });
  };
  draw();
}

function permUsers(el) {
  const ql = USER_Q.trim().toLowerCase();
  const rows = DIR.users.filter((u) => (!ql || (u.name + u.email + u.org).toLowerCase().includes(ql))
    && (!USER_TYPE || (USER_TYPE === "off" ? !u.enabled : u.type === USER_TYPE)) && (!USER_GROUP || u.groups.includes(USER_GROUP)));
  el.innerHTML = `<div class="toolbar"><div class="search">${icon("search")}<input class="input" id="uq" placeholder="Tìm tên, email, tổ chức…" value="${esc(USER_Q)}" aria-label="Tìm người dùng"></div>
    <select class="input" id="ut" aria-label="Lọc theo loại" style="max-width:170px"><option value="">Mọi loại</option><option value="guest" ${USER_TYPE === "guest" ? "selected" : ""}>Khách B2B</option><option value="member" ${USER_TYPE === "member" ? "selected" : ""}>Nhân viên</option><option value="off" ${USER_TYPE === "off" ? "selected" : ""}>Đã tắt</option></select>
    <select class="input" id="ug" aria-label="Lọc theo nhóm" style="max-width:200px"><option value="">Mọi nhóm</option>${DIR.groups.map((g) => `<option value="${esc(g.id)}" ${USER_GROUP === g.id ? "selected" : ""}>${esc(gshort(g.id) + " — " + gname(g.id))}</option>`).join("")}</select>
    <span class="muted small">${rows.length}/${DIR.users.length} tài khoản · ${DIR.users.filter((u) => u.type === "guest").length} khách B2B · ${DIR.users.filter((u) => !u.enabled).length} đã tắt</span><span style="flex:1"></span>
    <button class="btn primary" id="invite">${icon("plus")} Mời người dùng</button></div>
  ${rows.length ? `<div class="card tw-scroll"><table class="t"><thead><tr><th>Người dùng</th><th>Loại</th><th>Nhóm (quyền SharePoint)</th><th>Vai trò AI</th><th>Hoạt động</th></tr></thead><tbody>
  ${rows.map((u) => `<tr data-oid="${esc(u.oid)}" class="${u.enabled ? "" : "row-off"}">
    <td><div class="u-cell">${avatar(u.name)}<div class="who"><b>${esc(u.name)}</b><br><small>${esc(u.email)} · ${esc(u.org)}</small>
      ${DIR.deny_list[u.oid] ? `<br><span class="chip bad">Danh sách chặn: ${esc(DIR.deny_list[u.oid])}</span>` : ""}
      ${DIR.revocations.filter((r) => r.oid === u.oid).map((r) => `<br><span class="chip warn">Đang thu hồi: ${esc(gname(r.group))}</span>`).join("")}</div></div></td>
    <td><span class="chip">${u.type === "guest" ? "Khách B2B" : "Nhân viên"}</span></td>
    <td><div class="chips">${u.groups.map((g) => `<span class="chip brand" title="${esc(gname(g))}">${esc(gname(g))}<button data-rm-group="${esc(g)}" aria-label="Gỡ khỏi ${esc(gname(g))}">${icon("x")}</button></span>`).join("")}
      <select class="input" data-add-group aria-label="Thêm nhóm" style="height:26px;width:auto;font-size:12px;padding:0 4px"><option value="">+ Thêm nhóm</option>${DIR.groups.filter((g) => !u.groups.includes(g.id)).map((g) => `<option value="${esc(g.id)}">${esc(gname(g.id))}</option>`).join("")}</select></div></td>
    <td><div class="chips">${DIR.roles.map((r) => `<button class="chip ${u.roles.includes(r) ? "info" : ""}" data-role="${esc(r)}" aria-pressed="${u.roles.includes(r)}" title="Bật/tắt ${esc(ROLE_LABEL[r] || r)}" style="border:0;cursor:pointer">${u.roles.includes(r) ? icon("check") : ""}${esc(ROLE_LABEL[r] || r)}</button>`).join("")}</div></td>
    <td><div class="sw-cell"><button class="switch" role="switch" aria-checked="${u.enabled}" data-enabled aria-label="Bật/tắt tài khoản ${esc(u.name)}"></button><span class="small ${u.enabled ? "muted" : ""}" style="${u.enabled ? "" : "color:var(--bad)"}">${u.enabled ? "Đang bật" : "Đã tắt"}</span></div></td></tr>`).join("")}
  </tbody></table></div>` : `<div class="card empty rv-empty">${icon("users")}<b>Không có tài khoản nào khớp bộ lọc.</b></div>`}`;
  $("#uq").oninput = (e) => { USER_Q = e.target.value; const pos = e.target.selectionStart; permUsers(el); const n = $("#uq"); n.focus(); n.setSelectionRange(pos, pos); };
  $("#ut").onchange = (e) => { USER_TYPE = e.target.value; permUsers(el); };
  $("#ug").onchange = (e) => { USER_GROUP = e.target.value; permUsers(el); };
  $("#invite").onclick = inviteModal;
  $$("tr[data-oid]", el).forEach((tr) => {
    const oid = tr.dataset.oid, u = DIR.users.find((x) => x.oid === oid);
    $$("[data-rm-group]", tr).forEach((b) => b.onclick = () => {
      const g = b.dataset.rmGroup;
      confirmDo({ title: "Gỡ khỏi nhóm?", label: "Gỡ khỏi nhóm", lines: [
        `Gỡ <b>${esc(u.name)}</b> khỏi nhóm <b>${esc(gname(g))}</b>.`,
        `Người này mất quyền đọc mọi thư mục/tài liệu cấp cho nhóm này. ${SP_NOTE}` ],
        onOk: async () => { await change(`/api/admin/groups/${g}/members`, { oid, add: false }, `Đã gỡ ${u.name} khỏi ${gname(g)}`); permUsers(el); } });
    });
    $("[data-add-group]", tr).onchange = async (e) => { if (!e.target.value) return; try { await change(`/api/admin/groups/${e.target.value}/members`, { oid, add: true }, `Đã thêm ${u.name} vào ${gname(e.target.value)}`); } catch {} permUsers(el); };
    $$("[data-role]", tr).forEach((b) => b.onclick = async () => {
      const r = b.dataset.role, on = u.roles.includes(r), roles = on ? u.roles.filter((x) => x !== r) : [...u.roles, r];
      const apply = async () => { await change(`/api/admin/users/${oid}/roles`, { roles }, `Đã cập nhật vai trò của ${u.name}`); permUsers(el); };
      if (on) confirmDo({ title: "Tắt vai trò AI?", label: "Tắt vai trò", lines: [`Tắt vai trò <b>${esc(ROLE_LABEL[r] || r)}</b> của <b>${esc(u.name)}</b>.`, "Tính năng tương ứng bị chặn ở lần hỏi kế tiếp."], onOk: apply });
      else { try { await apply(); } catch {} }
    });
    $("[data-enabled]", tr).onclick = async () => {
      const apply = async () => { await change(`/api/admin/users/${oid}/enabled`, { enabled: !u.enabled }, `${u.enabled ? "Đã tắt" : "Đã bật"} tài khoản ${u.name}`); permUsers(el); };
      if (u.enabled) confirmDo({ title: "Tắt tài khoản?", label: "Tắt tài khoản", lines: [`Tắt tài khoản của <b>${esc(u.name)}</b> (${esc(u.email)}).`,
        "Người này không đăng nhập hay hỏi AI được nữa; dữ liệu và nhóm được giữ nguyên. Bật lại bất kỳ lúc nào."], onOk: apply });
      else { try { await apply(); } catch {} }
    };
  });
}

function inviteModal() {
  modal({ title: "Mời người dùng vào Data Room", body: `
    <label class="field">Họ tên<input class="input" id="nu-name" required></label>
    <label class="field">Email<input class="input" id="nu-email" type="email" required></label>
    <label class="field">Tổ chức<input class="input" id="nu-org"></label>
    <label class="field">Loại<select class="input" id="nu-type"><option value="guest">Khách B2B (nhà đầu tư, cố vấn)</option><option value="member">Nhân viên tổ chức phát hành</option></select></label>
    <div class="field">Nhóm<div class="checks">${DIR.groups.map((g) => `<label><input type="checkbox" value="${esc(g.id)}" data-nu-group> ${esc(gname(g.id))}</label>`).join("")}</div></div>
    <div class="field">Vai trò AI<div class="checks">${DIR.roles.map((r) => `<label><input type="checkbox" value="${esc(r)}" data-nu-role> ${esc(ROLE_LABEL[r] || r)}</label>`).join("")}</div></div>
    <label class="field">Mật khẩu tạm (≥ 8 ký tự)<input class="input" id="nu-pw" type="password" autocomplete="new-password"></label>
    <p class="small" id="nu-err" style="color:var(--bad);min-height:18px;margin:6px 0"></p>
    <div class="alert info small">Thêm vào nhóm có hiệu lực ở AI ngay sau đồng bộ, còn SharePoint giả lập áp sau độ trễ (mặc định 60 giây).</div>`,
  actions: [{ label: "Hủy" }, { label: "Mời", primary: true, onClick: async (ov) => {
    const err = (m) => { $("#nu-err", ov).textContent = m; return false; };
    const name = $("#nu-name", ov).value.trim(), email = $("#nu-email", ov).value.trim(), pw = $("#nu-pw", ov).value;
    if (!name) return err("Vui lòng nhập họ tên.");
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) return err("Email không hợp lệ.");
    if (pw.length < 8) return err("Mật khẩu tạm cần tối thiểu 8 ký tự.");
    try {
      await change("/api/admin/users", {
        name, email, org: $("#nu-org", ov).value, type: $("#nu-type", ov).value,
        groups: $$("[data-nu-group]:checked", ov).map((x) => x.value), roles: $$("[data-nu-role]:checked", ov).map((x) => x.value), password: pw,
      }, "Đã mời người dùng mới");
      permUsers($("#perm-body"));
    } catch (e) { return err(e.message); }
  } }] });
}

function permGroups(el) {
  el.innerHTML = `<div class="grid-2">${DIR.groups.map((g) => `<div class="card" data-gid="${esc(g.id)}">
    <div class="card-h">${icon("users")}<h3>${esc(gname(g.id))}</h3><span class="chip">${esc(g.id)}</span><span style="flex:1"></span><span class="muted small">${g.members.length} thành viên</span></div>
    <div class="card-b">${g.members.map((m) => `<div class="grant-row">${avatar(uname(m), 26)}<div class="g">${esc(uname(m))}${DIR.revocations.some((r) => r.oid === m && r.group === g.id) ? ' <span class="chip warn">đang thu hồi</span>' : ""}</div>
      <button class="btn sm ghost danger" data-rm="${esc(m)}" aria-label="Gỡ ${esc(uname(m))} khỏi ${esc(gname(g.id))}">${icon("x")} Gỡ</button></div>`).join("") || '<div class="muted small">Chưa có thành viên</div>'}
      <div class="inline-form"><select class="input" data-add aria-label="Thêm thành viên" style="max-width:none;flex:1"><option value="">Chọn người để thêm…</option>${DIR.users.filter((u) => !g.members.includes(u.oid)).map((u) => `<option value="${esc(u.oid)}">${esc(u.name)} — ${esc(u.org)}</option>`).join("")}</select>
      <button class="btn primary sm" data-addbtn>${icon("plus")} Thêm</button></div></div></div>`).join("")}</div>`;
  $$("[data-gid]", el).forEach((card) => {
    const gid = card.dataset.gid;
    $$("[data-rm]", card).forEach((b) => b.onclick = () => confirmDo({ title: "Gỡ thành viên khỏi nhóm?", label: "Gỡ khỏi nhóm", lines: [
      `Gỡ <b>${esc(uname(b.dataset.rm))}</b> khỏi nhóm <b>${esc(gname(gid))}</b>.`,
      `Người này mất quyền đọc mọi thư mục/tài liệu cấp cho nhóm. ${SP_NOTE}` ],
      onOk: async () => { await change(`/api/admin/groups/${gid}/members`, { oid: b.dataset.rm, add: false }, `Đã gỡ ${uname(b.dataset.rm)} khỏi ${gname(gid)}`); permGroups(el); } }));
    $("[data-addbtn]", card).onclick = async () => { const oid = $("[data-add]", card).value; if (!oid) return toast("Hãy chọn người cần thêm.", "bad"); try { await change(`/api/admin/groups/${gid}/members`, { oid, add: true }, `Đã thêm ${uname(oid)} vào ${gname(gid)}`); } catch {} permGroups(el); };
  });
}

function grantEditor({ unique, grants, onAdd, onRemove, onInherit, inheritLabel }) {
  return `<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">${unique ? '<span class="chip warn">Quyền riêng (đã tách kế thừa)</span>' : '<span class="chip">Kế thừa từ cấp trên</span>'}
      <span style="flex:1"></span>${unique && onInherit ? `<button class="btn sm" data-inherit>${icon("refresh")} ${inheritLabel || "Khôi phục kế thừa"}</button>` : ""}</div>
    ${grants.map((g, i) => `<div class="grant-row"><div class="g">${principal(g)}<div class="muted small">${esc(g.source || "")}</div></div>
      ${g.kind === "user" || g.kind === "group" ? `<button class="btn sm ghost danger" data-rm-grant="${i}">${icon("x")} Gỡ</button>` : ""}</div>`).join("") || '<div class="muted small">Không ai có quyền.</div>'}
    <div class="inline-form"><select class="input" data-gkind aria-label="Loại đối tượng" style="width:130px"><option value="group">Nhóm</option><option value="user">Người dùng</option></select>
      <select class="input" data-gid aria-label="Đối tượng" style="flex:1;max-width:none"></select><button class="btn primary sm" data-grant>${icon("plus")} Cấp quyền</button></div>
    <p class="muted small" style="margin:8px 0 0">${icon("info")} Site có RAC: người được cấp còn phải thuộc nhóm RAC của site thì mới mở được (bức tường thứ hai).</p>`;
}
// h = { add, remove, inherit, what } ; remove and inherit always go through a confirmation that states what changes.
function wireGrantEditor(root, grants, h) {
  const kind = $("[data-gkind]", root), sel = $("[data-gid]", root);
  const fill = () => {
    sel.innerHTML = kind.value === "group" ? DIR.groups.map((g) => `<option value="${esc(g.id)}">${esc(gname(g.id))}</option>`).join("")
      : DIR.users.map((u) => `<option value="${esc(u.oid)}">${esc(u.name)} — ${esc(u.org)}</option>`).join("");
  };
  kind.onchange = fill; fill();
  const what = h.what || "mục này";
  $("[data-grant]", root).onclick = () => h.add(kind.value, sel.value);
  $$("[data-rm-grant]", root).forEach((b) => b.onclick = () => {
    const g = grants[+b.dataset.rmGrant], who = g.kind === "group" ? gname(g.id) : uname(g.id);
    confirmDo({ title: "Gỡ quyền?", label: "Gỡ quyền", lines: [`Gỡ quyền đọc <b>${esc(what)}</b> của ${g.kind === "group" ? "nhóm" : "người dùng"} <b>${esc(who)}</b>.`,
      "Việc gỡ tách quyền riêng khỏi cấp trên (nếu đang kế thừa) và có hiệu lực ở AI ngay." ], onOk: () => h.remove(g.kind, g.id) });
  });
  const inh = $("[data-inherit]", root);
  if (inh) inh.onclick = () => confirmDo({ title: "Khôi phục kế thừa?", label: "Khôi phục kế thừa", lines: [
    `Xóa <b>toàn bộ quyền riêng</b> của <b>${esc(what)}</b>.`, "Từ giờ quyền lấy theo thư mục/cấp trên; những ai chỉ có quyền riêng sẽ mất quyền truy cập." ], onOk: h.inherit });
}

async function permFolders(el) {
  if (!DIR.sites.some((s) => s.id === PERM_SITE)) { PERM_SITE = DIR.sites[0]?.id; PERM_FOLDER = null; }
  el.innerHTML = `<div class="toolbar">${DIR.sites.map((s) => `<button class="btn ${PERM_SITE === s.id ? "primary" : ""} sm" data-site="${esc(s.id)}">${esc(s.name)}</button>`).join("")}</div>
    <div class="grid-side"><div class="card"><div class="card-h"><h3>Thư mục</h3></div><div class="list" id="flist" style="padding:6px"></div></div><div id="fdetail"></div></div>`;
  $$("[data-site]", el).forEach((b) => b.onclick = () => { PERM_SITE = b.dataset.site; PERM_FOLDER = null; permFolders(el); });
  let tree;
  try { tree = await api("/api/admin/tree/" + PERM_SITE); } catch (e) { $("#fdetail").innerHTML = `<div class="card empty">${esc(e.message)}</div>`; return; }
  if (!PERM_FOLDER || !tree.folders.some((f) => f.path === PERM_FOLDER)) PERM_FOLDER = tree.folders[0]?.path;
  $("#flist").innerHTML = tree.folders.map((f) => `<button class="${f.path === PERM_FOLDER ? "active" : ""}" data-f="${esc(f.path)}">${icon("folder")}<span style="flex:1">${esc(f.path)}</span>${f.unique ? '<span class="chip warn">riêng</span>' : ""}<span class="muted small">${f.files.length}</span></button>`).join("") || '<div class="empty">Site trống</div>';
  $$("#flist button").forEach((b) => b.onclick = () => { PERM_FOLDER = b.dataset.f; permFolders(el); });
  const f = tree.folders.find((x) => x.path === PERM_FOLDER);
  if (!f) { $("#fdetail").innerHTML = '<div class="card empty">Site trống</div>'; return; }
  const ST = { indexed: ["Đã lập chỉ mục", "ok"], skipped: ["Bỏ qua", "warn"], error: ["Lỗi", "bad"], pending: ["Chờ nạp", "info"] };
  $("#fdetail").innerHTML = `<div class="card" style="margin-bottom:16px"><div class="card-h">${icon("key")}<h3>Quyền thư mục: ${esc(f.path)}</h3></div><div class="card-b" id="fgrants">${grantEditor({ unique: f.unique, grants: f.grants, onInherit: true })}</div></div>
    <div class="card tw-scroll"><table class="t"><thead><tr><th>Tài liệu</th><th>AI_Use</th><th>Quyền</th><th>Trạng thái nạp</th><th></th></tr></thead><tbody>
    ${f.files.map((x) => `<tr data-item="${esc(x.item_id)}"><td><div style="display:flex;gap:8px;align-items:center;min-width:260px">${ftype(x.ext)}<span>${esc(x.name)}</span>
        ${x.encrypted ? '<span class="chip bad">mã hóa</span>' : ""}${x.malware ? '<span class="chip bad">mã độc</span>' : ""}</div></td>
      <td><select class="input" data-aiuse aria-label="AI_Use" style="height:30px;width:130px">${DIR.ai_use.map((v) => `<option ${v === x.ai_use ? "selected" : ""}>${esc(v)}</option>`).join("")}</select></td>
      <td>${x.unique ? '<span class="chip warn">riêng</span>' : '<span class="chip">kế thừa</span>'}${x.grants.some((g) => g.kind.startsWith("link_")) ? ' <span class="chip info">có link</span>' : ""}</td>
      <td>${(([l, c]) => `<span class="chip ${c}">${l}</span>`)(ST[x.status] || [x.status, ""])} <span class="muted small">${x.chunks || 0} đoạn</span></td>
      <td><button class="btn sm" data-iperm>${icon("key")} Quyền</button></td></tr>`).join("") || '<tr><td colspan="5" class="empty">Thư mục không có tài liệu.</td></tr>'}</tbody></table></div>`;
  wireGrantEditor($("#fgrants"), f.grants, {
    what: "thư mục " + f.path,
    add: async (kind, id) => { try { await change("/api/admin/grants", { target: "folder", site: PERM_SITE, key: f.path, kind, id, add: true }, `Đã cấp quyền thư mục cho ${kind === "group" ? gname(id) : uname(id)}`); } catch {} permFolders(el); },
    remove: async (kind, id) => { await change("/api/admin/grants", { target: "folder", site: PERM_SITE, key: f.path, kind, id, add: false }, `Đã gỡ quyền thư mục của ${kind === "group" ? gname(id) : uname(id)}`); permFolders(el); },
    inherit: async () => { await change("/api/admin/grants/inherit", { target: "folder", site: PERM_SITE, key: f.path }, "Đã khôi phục kế thừa cho thư mục"); permFolders(el); },
  });
  $$("tr[data-item]", $("#fdetail")).forEach((tr) => {
    const x = f.files.find((y) => y.item_id === tr.dataset.item);
    $("[data-aiuse]", tr).onchange = async (e) => {
      const v = e.target.value, apply = async () => { try { await change(`/api/admin/items/${x.item_id}/ai_use`, { value: v }, `AI_Use = ${v} cho ${x.name}`); } catch {} permFolders(el); };
      if (v === "Excluded" || x.ai_use === "Excluded" || v === "OnPremOnly") confirmDo({ title: "Đổi AI_Use?", label: "Đổi AI_Use", lines: [`Đặt AI_Use của <b>${esc(x.name)}</b> từ <b>${esc(x.ai_use)}</b> thành <b>${esc(v)}</b>.`, "AI sẽ ngừng dùng tài liệu này khi trả lời từ câu hỏi kế tiếp."], onOk: apply });
      else apply();
    };
    $("[data-iperm]", tr).onclick = () => itemDrawer(x, el);
  });
}

function itemDrawer(x, el) {
  const body = drawer(x.name, `<div class="muted small" style="margin-bottom:10px">${esc(x.item_id)} · ${esc(x.label || "không nhãn")}</div>` + grantEditor({ unique: x.unique, grants: x.grants, onInherit: true }));
  wireGrantEditor(body, x.grants, {
    what: "tài liệu " + x.name,
    add: async (kind, id) => { try { await change("/api/admin/grants", { target: "item", site: PERM_SITE, key: x.item_id, kind, id, add: true }, "Đã cấp quyền tài liệu"); } catch { return; } $(".drawer-ov")?.click(); permFolders(el); },
    remove: async (kind, id) => { await change("/api/admin/grants", { target: "item", site: PERM_SITE, key: x.item_id, kind, id, add: false }, "Đã gỡ quyền tài liệu"); $(".drawer-ov")?.click(); permFolders(el); },
    inherit: async () => { await change("/api/admin/grants/inherit", { target: "item", site: PERM_SITE, key: x.item_id }, "Đã khôi phục kế thừa"); $(".drawer-ov")?.click(); permFolders(el); },
  });
}

function permSites(el) {
  el.innerHTML = `<div class="grid-2">${DIR.sites.map((s) => `<div class="card" data-site="${esc(s.id)}">
    <div class="card-h">${icon("globe")}<h3>${esc(s.name)}</h3><span class="chip">${esc(s.id)}</span><span style="flex:1"></span>${s.rac ? '<span class="chip ok">RAC bật</span>' : '<span class="chip">RAC tắt</span>'}</div>
    <div class="card-b"><p class="muted small" style="margin-top:0">Nhóm có quyền đọc site. Khi RAC bật, đây cũng là bức tường thứ hai: ai không thuộc các nhóm này không mở được gì trong site, kể cả khi có link hoặc quyền riêng.</p>
      <div class="checks">${DIR.groups.map((g) => `<label><input type="checkbox" value="${esc(g.id)}" ${s.groups.includes(g.id) ? "checked" : ""}> ${esc(gname(g.id))}</label>`).join("")}</div>
      <div class="inline-form"><button class="btn primary sm" data-save>${icon("check")} Lưu nhóm của site</button></div></div></div>`).join("")}</div>`;
  $$("[data-site]", el).forEach((card) => $("[data-save]", card).onclick = async () => {
    const s = DIR.sites.find((x) => x.id === card.dataset.site), groups = $$("input:checked", card).map((x) => x.value);
    const removed = s.groups.filter((g) => !groups.includes(g)), added = groups.filter((g) => !s.groups.includes(g));
    if (!removed.length && !added.length) return toast("Chưa có thay đổi nào để lưu.");
    const apply = async () => { await change(`/api/admin/sites/${s.id}/groups`, { groups }, "Đã lưu nhóm của site"); permSites(el); };
    const lines = [...added.map((g) => `Thêm nhóm <b>${esc(gname(g))}</b> vào site ${esc(s.name)}.`), ...removed.map((g) => `Bỏ nhóm <b>${esc(gname(g))}</b> khỏi site ${esc(s.name)}: nhóm này không còn đọc được gì trong site${s.rac ? " (RAC bật, kể cả khi có link hoặc quyền riêng)" : ""}.`)];
    if (removed.length) confirmDo({ title: "Lưu nhóm của site?", label: "Lưu thay đổi", lines, onOk: apply });
    else { try { await apply(); } catch {} }
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
  const DESTRUCTIVE = { reset: "Nạp lại tenant gốc: mọi thay đổi người dùng, nhóm, quyền và AI_Use sẽ mất.", offboard: "Người được chọn bị offboard: tài khoản bị chặn.",
    pause_entra_feed: "Sau khoảng 30 giây mọi câu hỏi của mọi người bị từ chối (đóng an toàn).", corrupt_mirror: "Tiêm lỗi vào bản chép quyền của tenant." };
  $$(".scen", page).forEach((card) => $("button", card).onclick = () => {
    const params = {}; $$("[data-p]", card).forEach((s) => params[s.dataset.p] = s.value);
    const run = async () => {
    try {
      const r = await post("/api/scenario/" + card.dataset.name, { params });
      $("#scen-result").innerHTML = `<h4 style="margin:0 0 6px">${esc(r.title)}</h4><p style="margin:0 0 8px">${esc(r.explain)}</p>${r.try ? `<div class="alert info">${icon("info")} Thử: ${esc(r.try)}</div>` : ""}`;
      toast("Đã chạy: " + r.title); loadDir(); pollStatus();
    } catch (e) { toast(e.message, "bad"); }
    };
    if (DESTRUCTIVE[card.dataset.name]) confirmDo({ title: "Chạy kịch bản này?", label: "Chạy kịch bản", lines: [DESTRUCTIVE[card.dataset.name]], onOk: run });
    else run();
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
let AUD = { kind: "", who: "", q: "", limit: 200 };
const AUD_KIND = { answer: ["Trả lời", "ok"], refusal: ["Từ chối", "warn"], sign_in: ["Đăng nhập", "info"], permission_change: ["Đổi quyền", "brand"], scenario: ["Kịch bản", ""],
  feedback: ["Đánh giá", ""], file_link: ["Mở link file", ""], file_view: ["Xem file", ""], rate_limited: ["Giới hạn tốc độ", "warn"] };
// one readable "action" + "target" per audit row; the raw payload stays available under "Chi tiết"
function auditSummary(r) {
  const p = r.payload || {};
  if (r.kind === "permission_change") {
    const g = (id) => id ? gname(id) : "", u = (id) => id ? uname(id) : "";
    const A = {
      user_enabled: [p.enabled ? "Bật tài khoản" : "Tắt tài khoản", u(p.oid)],
      user_roles: ["Đổi vai trò AI", `${u(p.oid)}: ${(p.roles || []).map((x) => ROLE_LABEL[x] || x).join(", ") || "không có vai trò"}`],
      group_member: [p.add ? "Thêm vào nhóm" : "Gỡ khỏi nhóm", `${u(p.oid)} ${p.add ? "→" : "←"} ${g(p.group)}`],
      user_created: ["Mời người dùng", `${p.email || u(p.oid)}${(p.groups || []).length ? " · " + p.groups.map(g).join(", ") : ""}`],
      grant: [p.add ? "Cấp quyền" : "Gỡ quyền", `${p.kind === "group" ? g(p.id) : u(p.id)} · ${p.target === "item" ? "tài liệu" : "thư mục"} ${p.key || ""}`],
      restore_inheritance: ["Khôi phục kế thừa", `${p.target === "item" ? "tài liệu" : "thư mục"} ${p.key || ""}`],
      site_groups: ["Đổi nhóm của site", `${p.site}: ${(p.groups || []).map(g).join(", ") || "không nhóm"}`],
      ai_use: ["Đổi AI_Use", `${p.item_id || ""} = ${p.value || ""}`],
    };
    return A[p.action] || [p.action || "Đổi quyền", ""];
  }
  if (r.kind === "scenario") return ["Chạy kịch bản", p.title || p.name || ""];
  if (r.kind === "sign_in") return ["Đăng nhập", p.email || ""];
  const t = ["question", "query", "reason", "message", "title", "item_id", "email"].map((k) => p[k]).find((v) => typeof v === "string" && v);
  return [(AUD_KIND[r.kind] || [r.kind])[0], t ? (t.length > 140 ? t.slice(0, 140) + "…" : t) : ""];
}
const auditWho = (r) => r.oid === "admin" ? "Quản trị" : (r.oid ? uname(r.oid) : "Hệ thống");

async function pageAudit(page) {
  page.innerHTML = `<div class="toolbar"><button class="btn primary" id="verify">${icon("shield")} Kiểm tra chuỗi hash</button><span id="vout"></span><span style="flex:1"></span><button class="btn" id="reload">${icon("refresh")} Tải lại</button></div>
    <div id="afilters"></div><div id="alist"><div class="card empty">Đang tải…</div></div>`;
  let rows = [];
  const draw = () => {
    const kinds = [...new Set(rows.map((r) => r.kind))], whos = [...new Set(rows.map(auditWho))].sort();
    const q = AUD.q.trim().toLowerCase();
    const vis = rows.filter((r) => (!AUD.kind || r.kind === AUD.kind) && (!AUD.who || auditWho(r) === AUD.who)
      && (!q || (auditWho(r) + " " + auditSummary(r).join(" ") + " " + JSON.stringify(r.payload || {})).toLowerCase().includes(q)));
    $("#afilters").innerHTML = `<div class="toolbar"><div class="search">${icon("search")}<input class="input" id="aq" placeholder="Tìm trong nhật ký…" value="${esc(AUD.q)}" aria-label="Tìm trong nhật ký"></div>
      <select class="input" id="ak" aria-label="Loại" style="max-width:180px"><option value="">Mọi loại</option>${kinds.map((k) => `<option value="${esc(k)}" ${AUD.kind === k ? "selected" : ""}>${esc((AUD_KIND[k] || [k])[0])}</option>`).join("")}</select>
      <select class="input" id="aw" aria-label="Người" style="max-width:200px"><option value="">Mọi người</option>${whos.map((w) => `<option value="${esc(w)}" ${AUD.who === w ? "selected" : ""}>${esc(w)}</option>`).join("")}</select>
      <select class="input" id="al" aria-label="Số dòng" style="max-width:150px">${[80, 200, 500].map((n) => `<option value="${n}" ${AUD.limit === n ? "selected" : ""}>${n} dòng gần nhất</option>`).join("")}</select>
      <span class="muted small">${vis.length}/${rows.length} dòng</span></div>`;
    $("#aq").oninput = (e) => { AUD.q = e.target.value; const p = e.target.selectionStart; draw(); const n = $("#aq"); n.focus(); n.setSelectionRange(p, p); };
    $("#ak").onchange = (e) => { AUD.kind = e.target.value; draw(); };
    $("#aw").onchange = (e) => { AUD.who = e.target.value; draw(); };
    $("#al").onchange = (e) => { AUD.limit = +e.target.value; load(); };
    $("#alist").innerHTML = vis.length ? `<div class="card tw-scroll"><table class="t aud"><thead><tr><th>#</th><th>Thời điểm</th><th>Ai</th><th>Hành động</th><th>Đối tượng</th><th>Hash</th></tr></thead><tbody>${vis.map((r) => {
      const [l, c] = AUD_KIND[r.kind] || [r.kind, ""], [act, target] = auditSummary(r);
      return `<tr><td class="muted">${r.seq}</td><td style="white-space:nowrap">${fmtTime(r.ts)}</td><td>${esc(auditWho(r))}</td>
        <td><span class="chip ${c}">${esc(l)}</span>${r.kind === "permission_change" || r.kind === "scenario" ? ` <b>${esc(act)}</b>` : ""}</td>
        <td class="aud-t">${esc(target)}<details><summary class="small muted">Chi tiết</summary><pre class="payload">${esc(JSON.stringify(r.payload, null, 1))}</pre></details></td>
        <td class="mono muted small">${esc(r.hash)}…</td></tr>`;
    }).join("")}</tbody></table></div>` : `<div class="card empty rv-empty">${icon("list")}<b>Không có dòng nhật ký nào khớp bộ lọc.</b></div>`;
  };
  const load = async () => {
    try { rows = await api("/api/audit?limit=" + AUD.limit); draw(); }
    catch (e) { $("#alist").innerHTML = `<div class="card empty">${esc(e.message)}</div>`; }
  };
  $("#verify").onclick = async () => {
    try { const v = await api("/api/audit/verify"); $("#vout").innerHTML = v.ok ? `<span class="chip ok">${icon("check")} Chuỗi toàn vẹn · ${v.rows} dòng</span>` : `<span class="chip bad">Phát hiện sửa đổi tại dòng #${v.first_bad_seq}</span>`; }
    catch (e) { toast(e.message, "bad"); }
  };
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
