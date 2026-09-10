/* تحديث كشف الراحات الشهرية — صف لكل ضابط نظامه شهري/نصف شهري، وتاريخ
   بداية واحد بس. النوع والمدة معروفين مسبقًا من نظام راحته. */
let ROSTER = [];

function statusChip(row) {
  const c = row.current;
  if (row.status === "active") {
    return `<span class="chip rest">جارية الآن</span><div class="sub">حتى ${fmt(c.end)}</div>`;
  }
  if (row.status === "upcoming") {
    return `<span class="chip soon">قادمة</span><div class="sub">من ${fmt(c.start)}</div>`;
  }
  return `<span class="chip done">تم</span><div class="sub">محتاج تاريخ جديد</div>`;
}

function rosterRow(row) {
  const prefill = row.status === "upcoming" ? row.current.start : "";
  return `<tr data-id="${esc(row.id)}">
    <td class="name">${esc(row.name)}<div class="sub">${esc(row.role)}</div></td>
    <td><span class="chip ${row.rest_system === "شهرية" ? "m" : "h"}">${esc(row.rest_system)}</span></td>
    <td>${statusChip(row)}</td>
    <td>
      <input type="date" class="select roster-date" value="${esc(prefill)}"
        data-id="${esc(row.id)}">
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
  wrap.innerHTML = tableBlock(
    ["الضابط", "نظام الراحة", "الحالة الحالية", "تاريخ الراحة الجديد", ""],
    ROSTER.map(rosterRow),
    `عدد الضباط: ${ROSTER.length}`,
    "لا يوجد ضباط بنظام راحة شهري أو نصف شهري.");
  // data-action مقصورة على الضغط (زي core.js's click listener) — تغيير
  // تاريخ مش ضغطة، فلازم oninput مباشر زي lvStart في leave-form.js
  $$(".roster-date").forEach(input => {
    input.oninput = () => updateRowHint(input.dataset.id);
    updateRowHint(input.dataset.id);
  });
}

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
  render();
}
load();
