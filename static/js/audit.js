/* ==========================================================================
   سجل النشاط — من فعل ماذا ومتى: الدخول والخروج ومحاولات الوصول والتعديلات
   ========================================================================== */

let ENTRIES = [];
let NEXT_BEFORE = null;
let IS_LOADING = false;
let USERS_POPULATED = false;
let EVENTS_POPULATED = false;
let SEARCH_TIMER = null;

function formatAuditTime(ts) {
  if (!ts) return "<span class='muted'>—</span>";
  const parts = String(ts).split("T");
  const dayStr = parts[0] || "";
  const timeStr = (parts[1] || "").slice(0, 8);
  return `${fmt(dayStr)}<div class="sub muted" dir="ltr">${esc(timeStr)}</div>`;
}

function formatAuditUser(e) {
  const name = esc(e.display_name || e.username || "—");
  const username = e.username ? `<span class="muted font-mono" dir="ltr">@${esc(e.username)}</span>` : "";
  const role = e.role
    ? `<span class="role-badge role-badge-sm role-${esc(e.role)}">${esc(e.role_label || e.role)}</span>`
    : "";
  return `<div class="audit-user-cell">
    <span class="audit-user-name">${name}</span>
    <div class="audit-user-meta">${username} ${role}</div>
  </div>`;
}

function formatAuditEvent(e) {
  let chipClass = "w";
  if (e.event === "login_ok") {
    chipClass = "on";
  } else if (e.event === "login_failed" || e.event === "access_denied") {
    chipClass = "err";
  }
  return `<span class="chip ${chipClass}">${esc(e.event_label || e.event || "—")}</span>`;
}

function formatAuditDetails(e) {
  const action = esc(e.action_label || "—");
  const methodPath = (e.method || e.path)
    ? `<div class="sub muted audit-method-path" dir="ltr"><code>${esc((e.method || "").toUpperCase())} ${esc(e.path || "")}</code></div>`
    : "";
  return `<div class="audit-details-cell">${action}${methodPath}</div>`;
}

function formatAuditIp(e) {
  if (!e.ip) return "<span class='muted'>—</span>";
  return `<span class="audit-ip font-mono" dir="ltr">${esc(e.ip)}</span>`;
}

function auditRow(e) {
  return `<tr>
    <td class="wrap">${formatAuditTime(e.ts)}</td>
    <td>${formatAuditUser(e)}</td>
    <td>${formatAuditEvent(e)}</td>
    <td class="wrap">${formatAuditDetails(e)}</td>
    <td>${formatAuditIp(e)}</td>
  </tr>`;
}

function render(isError = false) {
  const wrap = $("#auditWrap");
  const loadMoreWrap = $("#auditLoadMoreWrap");

  if (isError) {
    wrap.innerHTML = emptyState({
      icon: "alert",
      title: "تعذر تحميل سجل النشاط",
      hint: "حدث خطأ أثناء الاتصال بالخادم. يرجى مراجعة الاتصال وإعادة المحاولة.",
      action: '<button type="button" class="btn" id="auditRetryBtn">إعادة المحاولة</button>'
    });
    loadMoreWrap.classList.add("hidden");
    const retryBtn = $("#auditRetryBtn");
    if (retryBtn) retryBtn.onclick = () => loadEntries(false);
    return;
  }

  if (!ENTRIES.length) {
    const hasFilters = $("#auditSearch").value.trim() ||
      $("#auditUser").value ||
      $("#auditEvent").value ||
      $("#auditFrom").value ||
      $("#auditTo").value;

    wrap.innerHTML = emptyState({
      icon: hasFilters ? "search" : "inbox",
      title: hasFilters ? "لا توجد نتائج مطابقة" : "لا توجد سجلات نشاط مسجلة",
      hint: hasFilters ? "حاول تعديل شروط التصفية أو البحث." : "تُسجَّل هنا كل العمليات الأمنية وتعديلات البيانات تلقائيًا."
    });
    loadMoreWrap.classList.add("hidden");
    return;
  }

  wrap.innerHTML = `
    <div class="table-scroll">
      ${mtable(["الوقت", "المستخدم", "الحدث", "التفاصيل", "عنوان IP"], ENTRIES.map(auditRow))}
    </div>
    <div class="count">عدد السجلات المعروضة: ${ENTRIES.length}</div>
  `;

  if (NEXT_BEFORE) {
    loadMoreWrap.classList.remove("hidden");
    const loadMoreBtn = $("#auditLoadMoreBtn");
    if (loadMoreBtn) {
      loadMoreBtn.disabled = false;
      loadMoreBtn.textContent = "تحميل المزيد";
    }
  } else {
    loadMoreWrap.classList.add("hidden");
  }
}

function populateDropdowns(data) {
  if (!USERS_POPULATED && Array.isArray(data.users)) {
    const userSel = $("#auditUser");
    const curVal = userSel.value;
    const opts = ['<option value="">كل المستخدمين</option>'];
    for (const u of data.users) {
      opts.push(`<option value="${esc(u)}">${esc(u)}</option>`);
    }
    userSel.innerHTML = opts.join("");
    userSel.value = curVal;
    USERS_POPULATED = true;
  }

  if (!EVENTS_POPULATED && Array.isArray(data.events)) {
    const eventSel = $("#auditEvent");
    const curVal = eventSel.value;
    const opts = ['<option value="">كل الأحداث</option>'];
    for (const ev of data.events) {
      opts.push(`<option value="${esc(ev.key)}">${esc(ev.label || ev.key)}</option>`);
    }
    eventSel.innerHTML = opts.join("");
    eventSel.value = curVal;
    EVENTS_POPULATED = true;
  }
}

async function loadEntries(append = false) {
  if (IS_LOADING) return;
  IS_LOADING = true;

  const loadMoreBtn = $("#auditLoadMoreBtn");
  if (append && loadMoreBtn) {
    loadMoreBtn.disabled = true;
    loadMoreBtn.textContent = "جاري التحميل…";
  } else {
    $("#auditWrap").innerHTML = skeleton("rows", 10);
    $("#auditLoadMoreWrap").classList.add("hidden");
  }

  const q = new URLSearchParams();
  const searchVal = ($("#auditSearch")?.value || "").trim();
  const userVal = $("#auditUser")?.value || "";
  const eventVal = $("#auditEvent")?.value || "";
  const fromVal = $("#auditFrom")?.value || "";
  const toVal = $("#auditTo")?.value || "";

  if (searchVal) q.set("q", searchVal);
  if (userVal) q.set("user", userVal);
  if (eventVal) q.set("event", eventVal);
  if (fromVal) q.set("from", fromVal);
  if (toVal) q.set("to", toVal);
  if (append && NEXT_BEFORE) q.set("before", NEXT_BEFORE);
  q.set("limit", "100");

  const d = await api(`/api/audit?${q.toString()}`);
  IS_LOADING = false;

  if (!d) {
    if (!append) render(true);
    else if (loadMoreBtn) {
      loadMoreBtn.disabled = false;
      loadMoreBtn.textContent = "تحميل المزيد";
    }
    return;
  }

  populateDropdowns(d);

  if (append) {
    ENTRIES = ENTRIES.concat(d.entries || []);
  } else {
    ENTRIES = d.entries || [];
  }
  NEXT_BEFORE = d.next_before || null;

  render();
}

// ── ربط أحداث الفلاتر والبحث ──
$("#auditUser").onchange = () => loadEntries(false);
$("#auditEvent").onchange = () => loadEntries(false);
$("#auditFrom").onchange = () => loadEntries(false);
$("#auditTo").onchange = () => loadEntries(false);

$("#auditSearch").addEventListener("input", () => {
  clearTimeout(SEARCH_TIMER);
  SEARCH_TIMER = setTimeout(() => {
    loadEntries(false);
  }, 350);
});

$("#auditClearFilters").onclick = () => {
  $("#auditSearch").value = "";
  $("#auditUser").value = "";
  $("#auditEvent").value = "";
  $("#auditFrom").value = "";
  $("#auditTo").value = "";
  loadEntries(false);
};

const loadMoreBtn = $("#auditLoadMoreBtn");
if (loadMoreBtn) {
  loadMoreBtn.onclick = () => loadEntries(true);
}

loadEntries(false);
