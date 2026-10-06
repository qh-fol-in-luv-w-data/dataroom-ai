/* Data Room AI demo UI — vanilla JS, no build step. */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

let TOKEN = null, ME = null, USERS = [], SCOPE = null, SCOPE_FILTER = null;
const STATUS_LABEL = {
  ai_ok: ["AI dùng được", "ok"], excluded: ["Không cho AI", "warn"], encrypted: ["Mã hóa", "bad"],
  malware: ["Mã độc", "bad"], pending: ["Đang nạp", "info"], unsupported: ["Không đọc được", ""],
  ai_blocked: ["AI đang chặn", "warn"],
};
const SUGGEST = [
  "Doanh thu năm 2025 của công ty là bao nhiêu?",
  "Tổng công suất các nhà máy của Sao Mai là bao nhiêu MW?",
  "Số lượng cổ phần dự kiến chào bán trong đợt IPO là bao nhiêu?",
  "Phí thu xếp cho nhóm quỹ trong nước là bao nhiêu?",
  "Tỷ giá trần trong cơ chế bảo hiểm tỷ giá là bao nhiêu?",
  "Giá chào bán riêng cho nhà đầu tư chiến lược là bao nhiêu?",
  "Định giá nội bộ của công ty là bao nhiêu?",
  "Đối tác bảo lãnh và hạn mức bảo lãnh là gì?",
  "doanh thu nam 2025 la bao nhieu",
];

async function api(path, opts = {}) {
  const r = await fetch(path, {
    ...opts,
    headers: { "Content-Type": "application/json", ...(TOKEN ? { Authorization: "Bearer " + TOKEN } : {}), ...(opts.headers || {}) },
  });
  const ct = r.headers.get("content-type") || "";
  const data = ct.includes("json") ? await r.json() : await r.text();
  if (!r.ok) throw new Error((data && data.detail) || r.statusText);
  return data;
}

// ------------------------------------------------------------- identity
async function loadUsers() {
  USERS = await api("/api/users");
  const sel = $("#who");
  const groups = { guest: "Nhà đầu tư / cố vấn (khách B2B)", member: "Nhân viên tổ chức phát hành", admin: "Quản trị demo" };
  sel.innerHTML = Object.entries(groups).map(([t, label]) =>
    `<optgroup label="${label}">${USERS.filter((u) => u.type === t).map((u) =>
      `<option value="${u.oid}">${esc(u.name)} — ${esc(u.org)}${u.enabled ? "" : " (đã tắt)"}</option>`).join("")}</optgroup>`).join("");
  const saved = localStorage.getItem("dr-who");
  sel.value = USERS.some((u) => u.oid === saved) ? saved : "inv-a1";
  sel.onchange = () => login(sel.value);
  await login(sel.value);
}

async function login(oid) {
  try {
    const r = await api("/api/login", { method: "POST", body: JSON.stringify({ oid }) });
    TOKEN = r.token; ME = USERS.find((u) => u.oid === oid);
    localStorage.setItem("dr-who", oid);
  } catch (e) {
    TOKEN = null; ME = USERS.find((u) => u.oid === oid);
    $("#who-meta").innerHTML = `<span class="badge bad">${esc(e.message)}</span>`;
    return;
  }
  document.body.classList.toggle("is-admin", oid === "admin");
  $("#who-meta").innerHTML = ME.oid === "admin" ? "Xem ma trận quyền, chạy kịch bản, kiểm tra nhật ký"
    : `Nhóm: ${ME.groups.map((g) => `<span class="badge">${g}</span>`).join("") || "—"} · Vai trò: ${ME.roles.map((r) => `<span class="badge info">${r}</span>`).join("") || '<span class="badge bad">không có quyền AI</span>'}`;
  $("#scope-site").style.display = ME.roles.includes("Staff.AI") ? "" : "none";
  $("#thread").innerHTML = $("#thread").dataset.empty;
  showTab(oid === "admin" ? "matrix" : (currentTab() === "matrix" || currentTab() === "scenarios" || currentTab() === "audit" ? "chat" : currentTab()));
}

// ------------------------------------------------------------- tabs
const currentTab = () => ($(".tabs button.active") || {}).dataset?.tab || "chat";
function showTab(name) {
  $$(".tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  $$(".tab").forEach((t) => t.classList.toggle("active", t.id === "tab-" + name));
  if (name === "scope") loadScope();
  if (name === "matrix") loadMatrix();
  if (name === "scenarios") renderScenarios();
  if (name === "audit") loadAudit();
}
$$(".tabs button").forEach((b) => (b.onclick = () => showTab(b.dataset.tab)));

// ------------------------------------------------------------- chat
function renderSuggest() {
  $("#suggest").innerHTML = SUGGEST.map((q) => `<button type="button">${esc(q)}</button>`).join("");
  $$("#suggest button").forEach((b) => (b.onclick = () => { $("#q").value = b.textContent; $("#ask").requestSubmit(); }));
}

function renderTrace(steps) {
  return `<details class="trace"><summary>Chi tiết các cổng và bước xử lý (${steps.length})</summary>${steps.map((s) => {
    const { step, ok, ms, ...rest } = s;
    return `<div class="step"><span class="${ok ? "dot-ok" : "dot-bad"}">${ok ? "✔" : "✖"}</span><span>${esc(step)}</span><span class="muted">${ms} ms</span>
      <span class="d">${esc(JSON.stringify(rest))}</span></div>`;
  }).join("")}</details>`;
}

function renderAnswer(r) {
  const who = `<div class="who">Trả lời cho <b>${esc(ME.name)}</b>${r.audit_seq ? ` · nhật ký #${r.audit_seq}` : ""}</div>`;
  if (r.refused) return `${who}<div class="refused">${esc(r.message)}</div>${renderTrace(r.trace || [])}`;
  const claims = `<ol class="claims">${r.claims.map((c) => `<li>${esc(c.text)}${c.refs.map((n) => `<sup class="ref" data-n="${n}">[${n}]</sup>`).join("")}${c.uncertain ? '<span class="badge warn" title="NLI cho điểm thấp">chưa chắc (NLI ' + c.nli + ")</span>" : c.nli != null ? `<span class="badge ok" title="Điểm NLI">NLI ${c.nli}</span>` : ""}</li>`).join("")}</ol>`;
  const cites = `<div class="cites">${r.citations.map((c) => `<div class="cite" id="cite-${c.n}"><span class="n">[${c.n}]</span><div>
      <span class="src">${esc(c.name)}</span> <span class="loc">· ${esc(c.locator)}</span> <span class="badge">${esc(c.site_id)}</span>
      ${c.ocr ? '<span class="badge info" title="Văn bản nhận dạng từ bản scan (PaddleOCR-VL)">văn bản nhận dạng từ bản scan</span>' : ""}
      <blockquote>${esc(c.quote)}</blockquote>
      <a href="/open/${encodeURIComponent(c.item_id)}?t=${encodeURIComponent(TOKEN)}" target="_blank">Mở trên SharePoint ↗</a></div></div>`).join("")}</div>`;
  return who + claims + cites + renderTrace(r.trace);
}

$("#ask").onsubmit = async (e) => {
  e.preventDefault();
  const q = $("#q").value.trim();
  if (!q || !TOKEN) return;
  const th = $("#thread");
  if (th.querySelector(".empty")) th.innerHTML = "";
  th.insertAdjacentHTML("beforeend", `<div class="msg-q">${esc(q)}</div>`);
  const box = document.createElement("div");
  box.className = "msg-a";
  box.innerHTML = `<div class="typing">Đang kiểm tra quyền, tìm kiếm và kiểm chứng câu trả lời…</div>`;
  th.appendChild(box); th.scrollTop = th.scrollHeight;
  $("#q").value = ""; $("#send").disabled = true;
  try {
    const r = await api("/api/chat", { method: "POST", body: JSON.stringify({ question: q, scope_site: $("#scope-site").value || null }) });
    box.innerHTML = renderAnswer(r);
    $$("sup.ref", box).forEach((s) => (s.onclick = () => box.querySelector("#cite-" + s.dataset.n)?.scrollIntoView({ behavior: "smooth", block: "center" })));
  } catch (err) {
    box.innerHTML = `<div class="refused">Lỗi: ${esc(err.message)}</div>`;
  } finally {
    $("#send").disabled = false; th.scrollTop = th.scrollHeight;
  }
};

// ------------------------------------------------------------- scope
function renderTree(sc, el, filter) {
  el.innerHTML = sc.sites.map((s) => {
    const folders = s.folders.map((f) => {
      const files = f.files.filter((x) => !filter || x.status === filter);
      if (!files.length) return "";
      return `<div class="folder"><div class="folder-name">📁 ${esc(f.path || "(gốc)")}</div>${files.map((x) => {
        const [lab, cls] = STATUS_LABEL[x.status] || [x.status, ""];
        return `<div class="file"><span class="ext">${esc(x.ext)}</span><span class="name" title="${esc(x.name)}">${esc(x.name)}</span>
          <span class="badge ${cls}">${lab}</span><span class="det">${esc(x.detail || "")}</span></div>`;
      }).join("")}</div>`;
    }).join("");
    const n = s.folders.reduce((a, f) => a + f.files.length, 0);
    const ai = s.folders.reduce((a, f) => a + f.files.filter((x) => x.status === "ai_ok").length, 0);
    return folders ? `<details class="site" open><summary>${esc(s.name)} <span class="badge">${s.site}</span> <span class="muted">· ${ai}/${n} file AI dùng được</span></summary>${folders}</details>` : "";
  }).join("") || `<p class="muted">Không có tài liệu nào.</p>`;
}

async function loadScope() {
  if (!TOKEN || ME.oid === "admin") return;
  $("#scope-tree").innerHTML = `<p class="muted">Đang tải…</p>`;
  SCOPE = await api("/api/scope");
  const c = SCOPE.counts;
  const stats = [["all", "Mở được trên SharePoint", SCOPE.sharepoint_total], ["ai_ok", "AI truy xuất được", c.ai_ok || 0],
    ["excluded", "Không cho AI (AI_Use)", c.excluded || 0], ["encrypted", "Mã hóa", c.encrypted || 0],
    ["malware", "Mã độc", c.malware || 0], ["ai_blocked", "AI đang chặn", c.ai_blocked || 0],
    ["pending", "Đang nạp", c.pending || 0], ["unsupported", "Không đọc được", c.unsupported || 0]];
  $("#scope-summary").innerHTML = stats.map(([k, l, v]) => `<div class="stat ${(SCOPE_FILTER || "all") === k ? "sel" : ""}" data-k="${k}"><div class="v">${v}</div><div class="l">${l}</div></div>`).join("")
    + (SCOPE.violations_ai_without_sharepoint.length ? `<div class="stat"><div class="v" style="color:var(--bad)">${SCOPE.violations_ai_without_sharepoint.length}</div><div class="l">VI PHẠM: AI thấy mà SharePoint không</div></div>` : "");
  $$("#scope-summary .stat[data-k]").forEach((s) => (s.onclick = () => { SCOPE_FILTER = s.dataset.k === "all" ? null : s.dataset.k; loadScope(); }));
  if (!$("#scope-site").options.length || $("#scope-site").options.length === 1) {
    $("#scope-site").innerHTML = `<option value="">Mọi site được phép</option>` + SCOPE.sites.map((s) => `<option value="${s.site}">${esc(s.name)}</option>`).join("");
  }
  renderTree(SCOPE, $("#scope-tree"), SCOPE_FILTER);
}

// ------------------------------------------------------------- matrix
async function loadMatrix() {
  const m = await api("/api/matrix");
  $("#matrix").innerHTML = `<table><tr><th>Người dùng</th><th>Nhóm</th>${m.sites.map((s) => `<th>${esc(s.name)}</th>`).join("")}</tr>${m.rows.map((r) =>
    `<tr class="click" data-oid="${r.oid}"><td><b>${esc(r.name)}</b><br><span class="muted">${esc(r.org)}</span>${r.enabled ? "" : ' <span class="badge bad">đã tắt</span>'}${r.roles.length ? "" : ' <span class="badge warn">không có quyền AI</span>'}</td>
     <td>${r.groups.map((g) => `<span class="badge">${g}</span>`).join(" ")}</td>
     ${m.sites.map((s) => { const c = r.sites[s.id]; return `<td class="cell ${c.sharepoint ? "" : "zero"} ${c.lag ? "lag" : ""}" title="${c.lag ? c.lag + " file AI đang chặn trước SharePoint" : ""}">${c.sharepoint ? `<b>${c.ai}</b> / ${c.sharepoint}` : "—"}</td>`; }).join("")}</tr>`).join("")}</table>`;
  $$("#matrix tr.click").forEach((tr) => (tr.onclick = async () => {
    const sc = await api("/api/scope_of/" + tr.dataset.oid);
    $("#matrix-detail").innerHTML = `<h3>Phạm vi của ${esc(USERS.find((u) => u.oid === tr.dataset.oid).name)}</h3><div></div>`;
    renderTree(sc, $("#matrix-detail div"), null);
  }));
}

// ------------------------------------------------------------- scenarios
const userOpts = (sel) => USERS.filter((u) => u.type !== "admin").map((u) => `<option value="${u.oid}" ${u.oid === sel ? "selected" : ""}>${esc(u.name)}</option>`).join("");
const groupOpts = (sel) => ["DR-INV-A", "DR-INV-B", "DR-INV-C", "ADVISERS", "STAFF"].map((g) => `<option ${g === sel ? "selected" : ""}>${g}</option>`).join("");
const SCEN = [
  { name: "remove_from_group", t: "1. Gỡ khỏi một nhóm (người thuộc 2 nhóm)", d: "SharePoint còn trễ, AI chặn ngay bằng tập thu hồi theo (người, nhóm).",
    f: () => `<select data-p="oid">${userOpts("inv-ab")}</select><select data-p="group">${groupOpts("DR-INV-A")}</select>` },
  { name: "move_group", t: "2. Chuyển nhóm", d: "Tài liệu nhóm cũ bị chặn ngay; nhóm mới chỉ mở khi SharePoint xác nhận.",
    f: () => `<select data-p="oid">${userOpts("inv-a2")}</select> từ <select data-p="from">${groupOpts("DR-INV-A")}</select> sang <select data-p="to">${groupOpts("DR-INV-C")}</select>` },
  { name: "exclude_file", t: "3. Đặt một file thành AI_Use = Excluded", d: "Câu hỏi kế tiếp không dùng được file, dù nhà đầu tư vẫn mở được." },
  { name: "publish_redacted_version", t: "4. Thay hợp đồng bằng bản đã biên tập", d: "Đoạn của bản cũ bị vô hiệu ngay; kiểm tra trực tiếp so ctag." },
  { name: "offboard", t: "5. Offboard một nhà đầu tư", d: "Token cũ còn hạn vẫn bị chặn ở cổng 4.", f: () => `<select data-p="oid">${userOpts("inv-b2")}</select>` },
  { name: "corrupt_mirror", t: "6. Làm hỏng bản chép quyền (tiêm lỗi)", d: "Cho B 'đọc' tài liệu nhóm A trong mirror — kiểm tra trực tiếp vẫn chặn.", f: () => `<select data-p="oid">${userOpts("inv-b1")}</select>` },
  { name: "pause_entra_feed", t: "7. Ngắt nguồn Entra (sự cố)", d: "Sau 30 giây hệ thống từ chối mọi câu hỏi (đóng an toàn)." },
  { name: "resume_entra_feed", t: "7b. Khôi phục nguồn Entra", d: "" },
  { name: "reset", t: "8. Khôi phục trạng thái ban đầu", d: "Nạp lại tenant gốc và đồng bộ toàn bộ." },
];
function renderScenarios() {
  $("#scen-list").innerHTML = SCEN.map((s) => `<div class="scen" data-name="${s.name}"><h4>${s.t}</h4>${s.d ? `<p>${s.d}</p>` : ""}<div class="row">${s.f ? s.f() : ""}<button>Chạy</button></div></div>`).join("");
  $$("#scen-list .scen").forEach((card) => ($("button", card).onclick = async () => {
    const params = {};
    $$("[data-p]", card).forEach((el) => (params[el.dataset.p] = el.value));
    try {
      const r = await api("/api/scenario/" + card.dataset.name, { method: "POST", body: JSON.stringify({ params }) });
      $("#scen-result").innerHTML = `<h3>${esc(r.title)}</h3><p>${esc(r.explain)}</p>${r.try ? `<p><b>Thử:</b> ${esc(r.try)}</p>` : ""}`;
    } catch (e) { $("#scen-result").innerHTML = `<h3>Lỗi</h3><p>${esc(e.message)}</p>`; }
    pollStatus();
  }));
}

// ------------------------------------------------------------- status
async function pollStatus() {
  if (!TOKEN) return;
  let s;
  try { s = await api("/api/status"); } catch { return; }
  const age = (k) => s.feeds[k] ?? 1e9;
  const pill = (txt, cls) => `<span class="pill ${cls}">${txt}</span>`;
  $("#pills").innerHTML = [
    pill(`Entra delta ${age("entra") > 1e8 ? "—" : Math.round(age("entra")) + "s"}`, age("entra") > s.feed_max_age ? "bad" : "ok"),
    pill(`SharePoint delta ${age("drive") > 1e8 ? "—" : Math.round(age("drive")) + "s"}`, age("drive") > s.feed_max_age ? "bad" : "ok"),
    pill(`${s.index.chunks} đoạn chỉ mục`, ""),
    pill(s.models_ready ? "Model sẵn sàng" : "Đang nạp model…", s.models_ready ? "ok" : "warn"),
    pill(s.ocr_server ? "OCR PaddleOCR-VL ✓" : "OCR server tắt", s.ocr_server ? "ok" : ""),
    s.ingest_busy ? pill("Đang nạp tài liệu…", "warn") : "",
  ].join("");
  if (currentTab() === "scenarios") {
    const now = Date.now() / 1000;
    $("#live").innerHTML = `
      <div class="live-row"><span>Nguồn Entra</span><b class="${s.entra_paused ? "dot-bad" : "dot-ok"}">${s.entra_paused ? "ĐANG NGẮT" : "hoạt động"} · ${Math.round(age("entra"))}s</b></div>
      <div class="live-row"><span>Tài liệu theo trạng thái</span><span>${Object.entries(s.items).map(([k, v]) => `${k}: ${v}`).join(" · ")}</span></div>
      <h4>Thay đổi nhóm SharePoint chưa áp dụng</h4>${s.sharepoint_pending.filter((p) => p.sharepoint_applies_in > 0).map((p) => `<div class="live-row"><span>${p.op === "remove" ? "Gỡ" : "Thêm"} ${p.oid} ${p.op === "remove" ? "khỏi" : "vào"} ${p.group}</span><b class="dot-bad">còn ${Math.round(p.sharepoint_applies_in)}s</b></div>`).join("") || '<p class="muted">Không có</p>'}
      <h4>Tập thu hồi của AI (người, nhóm)</h4>${s.revocations.map((r) => `<div class="live-row"><span>${r.oid} · ${r.group}</span><span class="muted">giữ tới ${new Date(r.until).toLocaleTimeString()}</span></div>`).join("") || '<p class="muted">Trống</p>'}
      <h4>Danh sách chặn</h4>${s.deny_list.map((d) => `<div class="live-row"><span>${d.oid}</span><span>${esc(d.reason)}</span></div>`).join("") || '<p class="muted">Trống</p>'}
      ${s.connector_error ? `<p class="dot-bad">Connector: ${esc(s.connector_error)}</p>` : ""}`;
  }
}

// ------------------------------------------------------------- audit
async function loadAudit() {
  const rows = await api("/api/audit?limit=60");
  $("#audit").innerHTML = `<table><tr><th>#</th><th>Thời điểm</th><th>Người</th><th>Loại</th><th>Nội dung</th><th>Hash</th></tr>${rows.map((r) =>
    `<tr><td>${r.seq}</td><td>${new Date(r.ts).toLocaleString()}</td><td>${esc(r.oid || "")}</td><td><span class="badge">${r.kind}</span></td>
     <td><pre class="payload">${esc(JSON.stringify(r.payload, null, 1))}</pre></td><td class="muted">${r.hash}…</td></tr>`).join("")}</table>`;
}
$("#verify-chain").onclick = async () => {
  const v = await api("/api/audit/verify");
  $("#verify-out").innerHTML = v.ok ? `<span class="badge ok">Chuỗi toàn vẹn · ${v.rows} dòng</span>` : `<span class="badge bad">Phát hiện sửa đổi tại dòng #${v.first_bad_seq}</span>`;
};
$("#reload-audit").onclick = loadAudit;

// ------------------------------------------------------------- boot
$("#thread").dataset.empty = $("#thread").innerHTML;
renderSuggest();
loadUsers().then(pollStatus);
setInterval(pollStatus, 2000);
