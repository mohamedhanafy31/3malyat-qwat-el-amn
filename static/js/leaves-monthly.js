/* تحديث كشف الراحات الشهرية — صف لكل ضابط نظامه شهري/نصف شهري، وتاريخ
   بداية واحد بس. النوع والمدة معروفين مسبقًا من نظام راحته. */
let ROSTER = [], WEEKLY_ROSTER = [];
const suspendedTypes = () => META.rest_suspension?.types || [];

/* بانر وقف الراحات — مشترك الشكل مع الرئيسية وصفحة الراحات */
function suspensionBanner(types) {
  if (!types.length) return "";
  return `<div class="alert-card susp-banner"><div class="alert-head"><span class="alert-ico">⛔</span>
    <strong>الراحات موقوفة: ${types.map(esc).join("، ")}</strong>
    <span class="muted">الضباط اللي نظامهم من الأنواع دي مايتسجّلش لهم كشف لحد «فتح الراحات» من صفحة الراحات.</span>
  </div></div>`;
}

function statusChip(row) {
  const c = row.current;
  if (row.status === "active") {
    return `<span class="chip rest">جارية الآن</span><div class="sub">حتى ${fmt(c.end)}</div>`;
  }
  if (row.status === "upcoming") {
    return `<span class="chip soon">قادمة</span><div class="sub">من ${fmt(c.start)}</div>`;
  }
  if (row.status === "suspended") {
    return `<span class="chip err">موقوفة</span><div class="sub">أمر وقف من ${fmt(c.since)}</div>`;
  }
  return `<span class="chip done">تم</span><div class="sub">محتاج تاريخ جديد</div>`;
}

function rosterRow(row) {
  const prefill = row.status === "upcoming" ? row.current.start : "";
  const blocked = suspendedTypes().includes(row.rest_system);
  return `<tr data-id="${esc(row.id)}">
    <td class="name">${esc(row.name)}<div class="sub">${esc(row.role)}</div></td>
    <td><span class="chip ${row.rest_system === "شهرية" ? "m" : "h"}">${esc(row.rest_system)}</span></td>
    <td>${statusChip(row)}</td>
    <td>
      <input type="date" class="select roster-date" value="${esc(prefill)}"
        data-id="${esc(row.id)}" ${blocked ? "disabled" : ""}>
      <div class="sub roster-hint" id="hint-${esc(row.id)}"></div>
    </td>
    <td class="wrap roster-error" id="err-${esc(row.id)}"></td>
  </tr>`;
}

function updateRowHint(id) {
  const input = document.querySelector(`.roster-date[data-id="${CSS.escape(id)}"]`);
  const hint = $(`#hint-${id}`);
  if (!input || !hint) return;
  const row = ROSTER.find(r => r.id === id);
  const start = input.value;
  if (!start || !row) { hint.textContent = ""; return }
  const n = DURATIONS()[row.rest_system] || 1;
  const end = addDays(start, n - 1);
  hint.textContent = `${n} يوم — حتى ${fmt(end)}، العودة ${fmt(addDays(end, 1))}`;
}

function render() {
  const wrap = $("#rosterWrap");
  if (!ROSTER) { wrap.innerHTML = `<div class="empty">جارٍ التحميل...</div>`; return }
  $("#suspensionBar").innerHTML = suspensionBanner(suspendedTypes());
  wrap.innerHTML = tableBlock(
    ["الضابط", "نظام الراحة", "الحالة الحالية", "تاريخ الراحة الجديد", ""],
    ROSTER.map(rosterRow),
    `عدد الضباط: ${ROSTER.length}`,
    "لا يوجد ضباط بنظام راحة شهري أو نصف شهري.");
  // الصفوف دي بتتولّد من جديد كل render() — لازم ترقية يدوية كل مرة،
  // بعكس حقول التاريخ الثابتة في الـmodals اللي بترقّى مرة واحدة بس
  // في core.js وقت تحميل الصفحة.
  upgradeDateInputs(wrap);
  // data-action مقصورة على الضغط (زي core.js's click listener) — تغيير
  // تاريخ مش ضغطة، فلازم oninput مباشر زي lvStart في leave-form.js
  $$(".roster-date").forEach(input => {
    input.oninput = () => updateRowHint(input.dataset.id);
    updateRowHint(input.dataset.id);
  });

  renderWeekly();
}

function weeklyLeaveChip(leave) {
  const label = leave.origin === "auto_weekly" ? "تلقائية"
    : leave.origin === "weekly_extra" ? "إضافية" : "مسجّلة";
  const cls = leave.origin === "weekly_extra" ? "soon" : "w";
  return `<span class="chip ${cls}">${fmt(leave.start)} <i>${label}</i></span>`;
}

function weeklyRow(row) {
  const blocked = suspendedTypes().includes("أسبوعية");
  const chips = row.upcoming?.length
    ? row.upcoming.map(weeklyLeaveChip).join(" ")
    : `<span class="muted">مفيش راحات أسبوعية قادمة مسجّلة</span>`;
  return `<tr data-id="${esc(row.id)}">
    <td class="name">${esc(row.name)}<div class="sub">${esc(row.role)}</div></td>
    <td><span class="chip w">${esc(row.rest_day)}</span></td>
    <td>${fmt(row.next_fixed)}<div class="sub">الموعد الثابت الجاي</div></td>
    <td class="wrap weekly-rest-chips">${chips}</td>
    <td>
      <div class="weekly-extra-controls">
        <input type="date" class="select weekly-extra-date" data-id="${esc(row.id)}"
          min="${esc(curDate())}" ${blocked ? "disabled" : ""}>
        <button class="mini" data-action="addWeeklyExtra" data-id="${esc(row.id)}"
          ${blocked ? "disabled" : ""}>＋ راحة إضافية</button>
      </div>
      <div class="sub roster-error" id="weekly-err-${esc(row.id)}"></div>
    </td>
  </tr>`;
}

function renderWeekly() {
  const wrap = $("#weeklyRosterWrap");
  wrap.innerHTML = tableBlock(
    ["الضابط", "اليوم الثابت", "الموعد الجاي", "الراحات المسجّلة القادمة", "راحة إضافية"],
    WEEKLY_ROSTER.map(weeklyRow),
    `عدد ضباط الراحة الأسبوعية: ${WEEKLY_ROSTER.length}`,
    "لا يوجد ضباط بنظام راحة أسبوعية.");
  upgradeDateInputs(wrap);
}

ACTIONS.addWeeklyExtra = async (id, _extra, button) => {
  const input = document.querySelector(`.weekly-extra-date[data-id="${CSS.escape(id)}"]`);
  const errorBox = $(`#weekly-err-${id}`);
  if (errorBox) errorBox.innerHTML = "";
  const start = input?.value || "";
  if (!start) {
    if (errorBox) errorBox.innerHTML = `<span class="chip err">اختار تاريخ الراحة الإضافية.</span>`;
    return;
  }
  button.disabled = true;
  const out = await api("/api/leaves", {
    ...jsonReq("POST", {person_id: id, type: "أسبوعية", start, end: start,
      origin: "weekly_extra"}),
    onError: body => {
      if (errorBox) errorBox.innerHTML = `<span class="chip err">${esc(body.error || "تعذر تسجيل الراحة.")}</span>`;
      return true;
    },
  });
  button.disabled = false;
  if (!out) return;
  showToast("تم تسجيل الراحة الأسبوعية الإضافية");
  await load();
};

$("#saveRosterBtn").onclick = async () => {
  const entries = [];
  for (const row of ROSTER) {
    const input = document.querySelector(`.roster-date[data-id="${CSS.escape(row.id)}"]`);
    const start = input?.value || "";
    const already = row.status === "upcoming" ? row.current.start : "";
    if (start && start !== already) entries.push({officer_id: row.id, start});
    const errBox = $(`#err-${row.id}`);
    if (errBox) errBox.innerHTML = "";
  }
  if (!entries.length) { showToast("مفيش تواريخ جديدة لحفظها"); return }

  const out = await api("/api/leaves/monthly", jsonReq("POST", {entries}));
  if (!out) return;

  for (const e of out.errors || []) {
    const box = $(`#err-${e.officer_id}`);
    if (box) box.innerHTML = `<span class="chip err">${esc(e.error)}</span>`;
  }
  if (out.created?.length) showToast(`تم حفظ ${out.created.length} راحة`);
  if (out.errors?.length && !out.created?.length) showToast("حصلت أخطاء — راجع الصفوف المعلّمة", true);
  await load();
};

async function load() {
  const d = await bootstrap();
  if (!d) return;
  ROSTER = d.roster || [];
  WEEKLY_ROSTER = d.weekly_roster || [];
  render();
}
load();
