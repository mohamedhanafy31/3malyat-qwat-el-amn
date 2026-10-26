/* تحديث كشف الراحات الشهرية — البداية والمدة قابلتان للتعديل لكل ضابط،
   مع إنهاء الجارية أو إلغاء القادمة مباشرة من نفس الصف. */
let ROSTER = [], WEEKLY_ROSTER = [];
const suspendedTypes = () => META.rest_suspension?.types || [];
const durationUnit = value => Number(value) === 1 ? "يوم" : Number(value) === 2 ? "يومان" : "أيام";

/* بانر وقف الراحات — مشترك الشكل مع الرئيسية وصفحة الراحات */
function suspensionBanner(types) {
  if (!types.length) return "";
  return `<div class="alert-card susp-banner"><div class="alert-head"><span class="alert-ico">${icon("block","ico-lg")}</span>
    <strong>الراحات موقوفة: ${types.map(esc).join("، ")}</strong>
    <span class="muted">لا يمكن تسجيل كشف للضباط ذوي هذه الأنواع حتى «فتح الراحات» من صفحة الراحات.</span>
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
  return `<span class="chip soon">يحتاج تاريخًا جديدًا</span>`;
}

function rosterRow(row) {
  const prefill = row.status === "upcoming" ? row.current.start : "";
  const actualDays = row.status === "upcoming" && row.current
    ? days(row.current.start, row.current.end) : (DURATIONS()[row.rest_system] || 1);
  const blocked = suspendedTypes().includes(row.rest_system);
  const needsDate = !["active", "upcoming", "suspended"].includes(row.status);
  const canStop = ["active", "upcoming"].includes(row.status) && row.current?.id;
  // الراحة الجارية لا تتعدل من كشف الراحة القادمة: الإجراء الواضح لها هو
  // «إنهاء الآن». القادمة فقط هي التي يمكن تغيير تاريخها ومدتها هنا.
  const editable = !blocked && !["active", "suspended"].includes(row.status);
  const action = canStop
    ? `<button class="mini roster-action-btn ${row.status === "upcoming" ? "bad" : "warn"}"
         data-action="stopRosterLeave" data-id="${esc(row.id)}">
         ${row.status === "upcoming" ? "إلغاء الراحة" : "إنهاء الآن"}</button>`
    : `<span class="muted">—</span>`;
  return `<tr data-id="${esc(row.id)}"${needsDate && !blocked ? ' class="needs-date"' : ""}>
    <td class="name">${esc(row.name)}<div class="sub">${esc(row.role)}</div></td>
    <td><span class="chip ${row.rest_system === "شهرية" ? "m" : "h"}">${esc(row.rest_system)}</span></td>
    <td>${statusChip(row)}</td>
    <td>
      <input type="date" class="select roster-date" value="${esc(prefill)}"
        data-id="${esc(row.id)}" data-initial="${esc(prefill)}" ${editable ? "" : "disabled"}
        aria-label="تاريخ الراحة الجديد — ${esc(row.name)}">
      <div class="sub roster-hint" id="hint-${esc(row.id)}"></div>
      <div class="roster-error" id="err-${esc(row.id)}"></div>
    </td>
    <td class="duration-cell">
      <div class="duration-stepper${editable ? "" : " is-disabled"}" role="group"
           aria-label="مدة راحة ${esc(row.name)}">
        <button type="button" class="duration-adjust" data-action="changeRestDays" data-id="${esc(row.id)}"
          data-extra="${dataAttr({delta: -1})}" ${editable ? "" : "disabled"} aria-label="تقليل المدة">−</button>
        <label class="duration-readout">
          <span class="sr-only">عدد أيام راحة ${esc(row.name)}</span>
          <input type="number" class="roster-days" min="1" max="120"
            value="${actualDays}" data-id="${esc(row.id)}" data-initial="${actualDays}"
            ${editable ? "" : "disabled"} aria-label="عدد أيام راحة ${esc(row.name)}">
          <span class="duration-unit" id="days-unit-${esc(row.id)}" aria-hidden="true">${durationUnit(actualDays)}</span>
        </label>
        <button type="button" class="duration-adjust" data-action="changeRestDays" data-id="${esc(row.id)}"
          data-extra="${dataAttr({delta: 1})}" ${editable ? "" : "disabled"} aria-label="زيادة المدة">+</button>
      </div>
      <div class="duration-note" id="days-note-${esc(row.id)}" aria-live="polite"></div>
    </td>
    <td class="roster-action">${action}</td>
  </tr>`;
}

function updateRowHint(id) {
  const input = document.querySelector(`.roster-date[data-id="${CSS.escape(id)}"]`);
  const hint = $(`#hint-${id}`);
  if (!input || !hint) return;
  const row = ROSTER.find(r => r.id === id);
  const start = input.value;
  if (!row) return;
  const duration = document.querySelector(`.roster-days[data-id="${CSS.escape(id)}"]`);
  const n = Math.max(1, Math.min(120, Number(duration?.value) || DURATIONS()[row.rest_system] || 1));
  const standard = DURATIONS()[row.rest_system] || 1;
  updateDurationStyle(id, n, standard);
  if (!start) { hint.textContent = ""; return }
  const end = addDays(start, n - 1);
  hint.textContent = `${countLabel(n, "يوم")} — حتى ${fmt(end)}، العودة ${fmt(addDays(end, 1))}`;
}

function updateDurationStyle(id, value, standard) {
  const input = document.querySelector(`.roster-days[data-id="${CSS.escape(id)}"]`);
  const stepper = input?.closest(".duration-stepper");
  const note = $(`#days-note-${id}`);
  const unit = $(`#days-unit-${id}`);
  const custom = Number(value) !== Number(standard);
  if (unit) unit.textContent = durationUnit(value);
  stepper?.classList.toggle("is-custom", custom);
  if (note) note.textContent = custom
    ? `معدّلة عن القياسي ${countLabel(standard, "يوم")}` : "";
}

function render() {
  const wrap = $("#rosterWrap");
  if (!ROSTER) { wrap.innerHTML = skeleton("rows", 8); return }
  $("#suspensionBar").innerHTML = suspensionBanner(suspendedTypes());
  const headers = ["الضابط", "نظام الراحة", "الحالة الحالية", "تاريخ الراحة الجديد", "المدة", "الإجراء"];
  const groupBlock = (type, title) => {
    const rows = ROSTER.filter(row => row.rest_system === type);
    const standard = DURATIONS()[type] || 1;
    return `<section class="roster-kind-group"><div class="roster-kind-head">
      <h4>${esc(title)} <span class="mcount">${rows.length}</span></h4>
      <span class="roster-standard">المدة القياسية <b>${countLabel(standard, "يوم")}</b></span>
      </div>${tableBlock(
      headers, rows.map(rosterRow), `عدد الضباط: ${rows.length}`, `لا يوجد ضباط بنظام ${title}`)}</section>`;
  };
  wrap.innerHTML = groupBlock("نصف شهرية", "راحات نصف شهرية")
    + groupBlock("شهرية", "راحات شهرية");
  // الصفوف دي بتتولّد من جديد كل render() — لازم ترقية يدوية كل مرة،
  // بعكس حقول التاريخ الثابتة في الـmodals اللي بترقّى مرة واحدة بس
  // في core.js وقت تحميل الصفحة.
  upgradeDateInputs(wrap);
  // data-action مقصورة على الضغط (زي core.js's click listener) — تغيير
  // تاريخ مش ضغطة، فلازم oninput مباشر زي lvStart في leave-form.js
  $$(".roster-date").forEach(input => {
    input.oninput = () => { updateRowHint(input.dataset.id); updateDirty(); };
    updateRowHint(input.dataset.id);
  });
  $$(".roster-days").forEach(input => {
    input.oninput = () => {
      input.value = Math.max(1, Math.min(120, Number(input.value) || 1));
      updateRowHint(input.dataset.id); updateDirty();
    };
  });
  updateDirty();

  renderWeekly();
}

ACTIONS.changeRestDays = (id, extra) => {
  const input = document.querySelector(`.roster-days[data-id="${CSS.escape(id)}"]`);
  if (!input || input.disabled) return;
  input.value = Math.max(1, Math.min(120, Number(input.value || 1) + Number(extra.delta || 0)));
  updateRowHint(id); updateDirty(); input.focus();
};

ACTIONS.stopRosterLeave = id => {
  const row = ROSTER.find(item => item.id === id);
  if (!row?.current?.id) return;
  openStopLeave({id: row.current.id, name: row.name, type: row.rest_system,
    start: row.current.start, end: row.current.end}, load);
};

function groupedRoster(rows) {
  const order = {"نصف شهرية": 0, "شهرية": 1};
  return [...rows].sort((a, b) => (order[a.rest_system] ?? 9) - (order[b.rest_system] ?? 9));
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
    : `<span class="muted">لا توجد راحات أسبوعية قادمة مسجّلة</span>`;
  return `<tr data-id="${esc(row.id)}">
    <td class="name">${esc(row.name)}<div class="sub">${esc(row.role)}</div></td>
    <td><span class="chip w">${esc(row.rest_day)}</span></td>
    <td>${fmt(row.next_fixed)}<div class="sub">الموعد الثابت القادم</div></td>
    <td class="wrap weekly-rest-chips">${chips}</td>
    <td>
      <div class="weekly-extra-controls">
        <input type="date" class="select weekly-extra-date" data-id="${esc(row.id)}"
          min="${esc(curDate())}" ${blocked ? "disabled" : ""}>
        <button class="mini" data-action="addWeeklyExtra" data-id="${esc(row.id)}"
          ${blocked ? "disabled" : ""}>${icon("plus")} راحة إضافية</button>
      </div>
      <div class="sub roster-error" id="weekly-err-${esc(row.id)}"></div>
    </td>
  </tr>`;
}

function renderWeekly() {
  const wrap = $("#weeklyRosterWrap");
  wrap.innerHTML = tableBlock(
    ["الضابط", "اليوم الثابت", "الموعد القادم", "الراحات المسجّلة القادمة", "راحة إضافية"],
    WEEKLY_ROSTER.map(weeklyRow),
    `عدد ضباط الراحة الأسبوعية: ${WEEKLY_ROSTER.length}`,
    "لا يوجد ضباط بنظام راحة أسبوعية");
  upgradeDateInputs(wrap);
}

ACTIONS.addWeeklyExtra = async (id, _extra, button) => {
  const input = document.querySelector(`.weekly-extra-date[data-id="${CSS.escape(id)}"]`);
  const errorBox = $(`#weekly-err-${id}`);
  if (errorBox) errorBox.innerHTML = "";
  const start = input?.value || "";
  if (!start) {
    if (errorBox) errorBox.innerHTML = `<span class="chip err">اختر تاريخ الراحة الإضافية.</span>`;
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

/* عدّاد التعديلات غير المحفوظة في شريط الحفظ اللاصق — الكشف طويل وزرار
   الحفظ كان فوق بس، فمكانش في أي إشارة إن فيه حاجة لسه ما اتحفظتش */
const dirtyRows = () => ROSTER.filter(row => {
  const dateInput = document.querySelector(`.roster-date[data-id="${CSS.escape(row.id)}"]`);
  const daysInput = document.querySelector(`.roster-days[data-id="${CSS.escape(row.id)}"]`);
  if (!dateInput || dateInput.disabled || !dateInput.value) return false;
  return dateInput.value !== (dateInput.dataset.initial || "")
    || daysInput?.value !== daysInput?.dataset.initial;
});
function updateDirty() {
  const n = dirtyRows().length;
  // الصفة بتتبع العدد: تعديل واحد غير محفوظ، تعديلان غير محفوظين، تعديلات غير محفوظة
  $("#rosterDirty").textContent = n ? `عدد التعديلات غير المحفوظة: ${n}` : "";
  $("#rosterUndo").classList.toggle("hidden", !n);
  $("#saveRosterBtn").disabled = !n;
}
$("#rosterUndo").onclick = () => {
  dirtyRows().forEach(row => {
    const dateInput = document.querySelector(`.roster-date[data-id="${CSS.escape(row.id)}"]`);
    const daysInput = document.querySelector(`.roster-days[data-id="${CSS.escape(row.id)}"]`);
    dateInput.value = dateInput.dataset.initial || "";
    daysInput.value = daysInput.dataset.initial || "1";
    updateRowHint(row.id);
  });
  updateDirty();
};
window.addEventListener("beforeunload", e => {
  if (dirtyRows().length) { e.preventDefault(); e.returnValue = ""; }
});

$("#saveRosterBtn").onclick = async () => {
  const entries = [];
  for (const row of ROSTER) {
    const input = document.querySelector(`.roster-date[data-id="${CSS.escape(row.id)}"]`);
    const start = input?.value || "";
    const duration = document.querySelector(`.roster-days[data-id="${CSS.escape(row.id)}"]`);
    const already = row.status === "upcoming" ? row.current.start : "";
    const alreadyDays = row.status === "upcoming" ? days(row.current.start, row.current.end)
      : (DURATIONS()[row.rest_system] || 1);
    const requestedDays = Number(duration?.value) || alreadyDays;
    if (start && (start !== already || requestedDays !== alreadyDays))
      entries.push({officer_id: row.id, start, days: requestedDays,
        leave_id: row.status === "upcoming" ? row.current.id : ""});
    const errBox = $(`#err-${row.id}`);
    if (errBox) errBox.innerHTML = "";
  }
  if (!entries.length) { showToast("لا توجد تواريخ جديدة للحفظ"); return }

  const out = await api("/api/leaves/monthly", jsonReq("POST", {entries}));
  if (!out) return;

  for (const e of out.errors || []) {
    const box = $(`#err-${e.officer_id}`);
    if (box) box.innerHTML = `<span class="chip err">${esc(e.error)}</span>`;
  }
  if (out.created?.length) showToast(`تم حفظ ${countLabel(out.created.length, "راحة")}`);
  if (out.errors?.length && !out.created?.length) showToast("حصلت أخطاء — راجع الصفوف المعلّمة", true);
  await load();
};

async function load() {
  const d = await bootstrap();
  if (!d) return;
  ROSTER = groupedRoster(d.roster || []);
  WEEKLY_ROSTER = d.weekly_roster || [];
  render();
}


function reportDate() {
  return $("#leavesReportDate").value || META.today || curDate();
}

$("#leavesReportDate").value = curDate();
$("#exportMonthlyLeaves").onclick = () => {
  window.location.assign(`/api/leaves/monthly/export.docx?on=${encodeURIComponent(reportDate())}`);
};
$("#exportWeeklyLeaves").onclick = () => {
  window.location.assign(`/api/leaves/weekly/export.docx?on=${encodeURIComponent(reportDate())}`);
};
load();
