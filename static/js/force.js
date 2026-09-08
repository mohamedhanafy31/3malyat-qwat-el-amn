/* صفحة القوة — بتخدم الضباط والأفراد. الفرق بينهم في الأعمدة وكرت القيادة،
   وحالة الراحة/التقصيرة بتيجي محسوبة من الباك إند فمش محتاجين نحمّل كل
   سجلات الراحات هنا. */
const IS_OFF = PAGE === "officers";
let LIST = {active: [], archive: []}, BUCKET = "active";
let COMMAND = {}, MEDICAL = [];

const personById = id => [...LIST.active, ...LIST.archive].find(p => p.id === id);
const commandOf = id => COMMAND_ROLES().find(r => COMMAND[r] === id);
const isMedical = id => MEDICAL.includes(id);

function badges(p) {
  const role = commandOf(p.id);
  return (role ? ` <span class="chip cmd">${esc(role)}</span>` : "")
       + (isMedical(p.id) ? ` <span class="chip cmd">${esc(MEDICAL_BADGE())}</span>` : "");
}

function renderStats() {
  const onRest = LIST.active.filter(p => p.status_today?.state === "resting").length;
  $("#forceStats").innerHTML = `
    <div class="stat"><span>على القوة</span><strong>${LIST.active.length}</strong></div>
    <div class="stat"><span>في الأرشيف</span><strong>${LIST.archive.length}</strong></div>
    ${IS_OFF ? `<div class="stat"><span>في راحة اليوم</span><strong>${onRest}</strong></div>` : ""}
    <div class="stat"><span>الإجمالي (قوة + أرشيف)</span><strong>${LIST.active.length + LIST.archive.length}</strong></div>`;
}

function filterRows(rows) {
  const q = $("#search").value.trim().toLowerCase();
  const rf = $("#restFilter")?.value;
  if (q) rows = rows.filter(p => [p.name, p.code, p.phone, p.role, p.post, p.address]
    .some(v => String(v || "").toLowerCase().includes(q)));
  if (rf && IS_OFF) rows = rf === "__rest_now"
    ? rows.filter(p => p.status_today?.state === "resting")
    : rows.filter(p => (p.rest_system || "—") === rf);
  return rows;
}

function renderTable() {
  const isArch = BUCKET === "archive";
  const rows = filterRows(LIST[BUCKET]);
  const head = IS_OFF
    ? (isArch ? ["الاسم","الرتبة","الأقدمية","الهاتف","العمل المسند","من","إلى","السبب","الإجراء"]
              : ["الاسم","الرتبة","الأقدمية","الهاتف","العمل المسند","نظام الراحة","حالة اليوم","من","الإجراء"])
    : (isArch ? ["الاسم","الدرجة","الكود","الهاتف","العمل","العنوان","من","إلى","السبب","الإجراء"]
              : ["الاسم","الدرجة","الكود","الهاتف","العمل","العنوان","من","الإجراء"]);

  const body = rows.map(p => {
    const acts = isArch
      ? `<button class="mini" data-action="openPerson" data-id="${esc(p.id)}">تعديل</button>
         <button class="mini ok" data-action="restorePerson" data-id="${esc(p.id)}">استرجاع</button>
         <button class="mini bad" data-action="deleteRecord" data-id="${esc(p.id)}" data-extra="${dataAttr({name: p.name})}">حذف</button>`
      : `<button class="mini" data-action="openPerson" data-id="${esc(p.id)}">تعديل</button>
         ${IS_OFF ? `<button class="mini ok" data-action="openLeaveFor" data-id="${esc(p.id)}">راحة</button>` : ""}
         <button class="mini bad" data-action="openRemove" data-id="${esc(p.id)}" data-extra="${dataAttr({name: p.name})}">إخراج</button>`;
    const dash = "<span class='muted'>—</span>";
    const cells = IS_OFF
      ? (isArch ? [`<td class="name">${esc(p.name)}</td>`,`<td><span class="badge">${esc(p.role)}</span></td>`,`<td>${esc(p.code)}</td>`,`<td class="num">${esc(p.phone) || dash}</td>`,`<td class="wrap">${esc(p.post) || "-"}</td>`,`<td>${fmt(p.join_date)}</td>`,`<td>${fmt(p.leave_date)}</td>`,`<td class="wrap">${esc(p.leave_reason) || dash}</td>`]
                : [`<td class="name">${esc(p.name)}${badges(p)}</td>`,`<td><span class="badge">${esc(p.role)}</span></td>`,`<td>${esc(p.code)}</td>`,`<td class="num">${esc(p.phone) || dash}</td>`,`<td class="wrap">${esc(p.post) || "-"}</td>`,`<td>${restLabel(p)}</td>`,`<td>${statusCell(p)}</td>`,`<td>${fmt(p.join_date)}</td>`])
      : (isArch ? [`<td class="name">${esc(p.name)}</td>`,`<td><span class="badge person">${esc(p.role)}</span></td>`,`<td>${esc(p.code)}</td>`,`<td class="num">${esc(p.phone)}</td>`,`<td>${esc(p.post) || "-"}</td>`,`<td class="wrap">${esc(p.address) || "-"}</td>`,`<td>${fmt(p.join_date)}</td>`,`<td>${fmt(p.leave_date)}</td>`,`<td class="wrap">${esc(p.leave_reason) || dash}</td>`]
                : [`<td class="name">${esc(p.name)}</td>`,`<td><span class="badge person">${esc(p.role)}</span></td>`,`<td>${esc(p.code)}</td>`,`<td class="num">${esc(p.phone)}</td>`,`<td>${esc(p.post) || "-"}</td>`,`<td class="wrap">${esc(p.address) || "-"}</td>`,`<td>${fmt(p.join_date)}</td>`]);
    return `<tr>${cells.join("")}<td><div class="actions">${acts}</div></td></tr>`;
  });
  $("#tableWrap").innerHTML = tableBlock(head, body, `عدد النتائج: ${rows.length}`, "لا توجد بيانات لعرضها.");
}

function render() { renderStats(); renderTable(); }

/* ---------- قيادة الإدارة + ضباط العيادة (صفحة الضباط بس) ---------- */
function renderCommand() {
  const box = $("#commandBar"); if (!box) return;
  const officers = LIST.active;
  box.innerHTML = `
    <div class="cmd-head">قيادة الإدارة
      <span class="muted">تشغيلهم ثابت يوميًا (إلا أيام الراحة) — غيّرهم مع حركة الضباط</span>
    </div>
    <div class="cmd-slots">${COMMAND_ROLES().map(role => {
      const held = COMMAND[role], p = held ? personById(held) : null;
      return `<label class="cmd-slot"><span class="cmd-role">${esc(role)}</span>
        <select data-cmd-role="${esc(role)}">
          <option value="">— غير محدد —</option>
          ${officers.map(o => `<option value="${esc(o.id)}" ${o.id === held ? "selected" : ""}>${esc(o.role)} / ${esc(o.name)}</option>`).join("")}
        </select>
        ${p ? `<span class="cmd-now">${esc(p.role)} / ${esc(p.name)}</span>`
            : `<span class="cmd-now empty">مفيش ضابط محدد للمنصب ده</span>`}</label>`;
    }).join("")}</div>
    <div class="cmd-head" style="margin-top:16px">${esc(MEDICAL_BADGE())}
      <span class="muted">تشغيلهم "طبية" (موجود/راحة) تلقائيًا كل يوم جديد — بدون تكليف يدوي</span>
    </div>
    <div class="svc-picker" id="medOfficerPicker" style="margin-bottom:0">
      ${officers.map(o => `<label class="svc-item ${isMedical(o.id) ? "on" : ""}">
        <input type="checkbox" value="${esc(o.id)}" ${isMedical(o.id) ? "checked" : ""}>
        <span class="svc-name">${esc(o.role)} / ${esc(o.name)}</span>
      </label>`).join("")}
    </div>`;

  box.querySelectorAll("[data-cmd-role]").forEach(sel => sel.onchange = async () => {
    const out = await api("/api/command", jsonReq("PATCH", {[sel.dataset.cmdRole]: sel.value || null}));
    if (!out) { renderCommand(); return }   // رجّع الاختيار القديم لو الطلب اترفض
    showToast("تم تحديث القيادة"); load();
  });
  const picker = $("#medOfficerPicker");
  picker.querySelectorAll("input").forEach(cb => cb.onchange = async () => {
    cb.closest(".svc-item").classList.toggle("on", cb.checked);
    const ids = [...picker.querySelectorAll("input:checked")].map(x => x.value);
    const out = await api("/api/medical-officers", jsonReq("PATCH", {officer_ids: ids}));
    if (!out) { renderCommand(); return }
    showToast("تم تحديث ضباط العيادة"); load();
  });
}

/* ---------- نموذج الشخص ---------- */
function updateRoles() {
  const isOff = $("#type").value === "officer";
  fillSelect($("#role"), (isOff ? OFFICER_ROLES : PERSONNEL_ROLES).map(x => [x, x]), true);
  $("#restSysWrap").classList.toggle("hidden", !isOff);
  $("#restDayWrap").classList.toggle("hidden", !isOff);
  $("#addressWrap").classList.toggle("hidden", isOff);
  toggleRestDay();
}
function toggleRestDay() {
  $("#restDayWrap").style.display =
    ($("#fRestSystem").value === "أسبوعية" && $("#type").value === "officer") ? "" : "none";
}

function openPerson(id) {
  const p = id ? personById(id) : null;
  $("#personId").value = id || "";
  $("#personModalTitle").textContent = p ? "تعديل البيانات" : "إضافة إلى القوة";
  $("#personSubmit").textContent = p ? "حفظ التعديلات" : "حفظ وإضافة للقوة";
  fillSelect($("#fRestSystem"), REST_SYSTEMS().map(x => [x, x]));
  fillSelect($("#fRestDay"), [["", "— بدون —"], ...WEEKDAYS().map(x => [x, x])]);

  $("#type").value = IS_OFF ? "officer" : "personnel";
  $("#type").disabled = !!p;
  updateRoles();

  $("#fName").value = p?.name || "";
  $("#fCode").value = p?.code || "";
  $("#fPhone").value = p?.phone || "";
  $("#fJoin").value = p?.join_date || curDate();
  $("#fPost").value = p?.post || "";
  $("#fAddress").value = p?.address || "";
  if (p?.role) fillSelect($("#role"),
    [[p.role, p.role], ...(IS_OFF ? OFFICER_ROLES : PERSONNEL_ROLES).filter(x => x !== p.role).map(x => [x, x])]);
  $("#fRestSystem").value = p?.rest_system || "—";
  $("#fRestDay").value = p?.rest_day || "";
  toggleRestDay();

  const archived = p?.status === "archived";
  $("#archiveFields").classList.toggle("hidden", !archived);
  if (archived) { $("#fLeaveDate").value = p.leave_date || ""; $("#fLeaveReason").value = p.leave_reason || "" }
  openModal("personModal");
}

$("#personForm").onsubmit = async e => {
  e.preventDefault();
  const id = $("#personId").value, isOff = $("#type").value === "officer";
  const body = {name: $("#fName").value, role: $("#role").value, code: $("#fCode").value,
    phone: $("#fPhone").value, join_date: $("#fJoin").value, post: $("#fPost").value};
  if (isOff) { body.rest_system = $("#fRestSystem").value; body.rest_day = $("#fRestSystem").value === "أسبوعية" ? $("#fRestDay").value : "" }
  else body.address = $("#fAddress").value;
  if (!$("#archiveFields").classList.contains("hidden")) {
    body.leave_date = $("#fLeaveDate").value; body.leave_reason = $("#fLeaveReason").value;
  }
  const out = id
    ? await api(`/api/person/${encodeURIComponent(id)}`, jsonReq("PATCH", body))
    : await api("/api/person", jsonReq("POST", {...body, type: $("#type").value}));
  if (!out) return;
  closeModal("personModal"); showToast(id ? "تم حفظ التعديلات" : "تمت الإضافة إلى القوة"); load();
};

$("#removeForm").onsubmit = async e => {
  e.preventDefault();
  const out = await api(`/api/person/${encodeURIComponent($("#removeId").value)}/remove`,
    jsonReq("POST", {leave_date: $("#leaveDate").value, reason: $("#reason").value}));
  if (!out) return;
  closeModal("removeModal"); showToast("تم الإخراج وحفظ السجل في الأرشيف"); load();
};

ACTIONS.openPerson = id => openPerson(id);
ACTIONS.openRemove = (id, extra) => {
  $("#removeId").value = id; $("#removeName").textContent = `سيتم إخراج: ${extra.name}`;
  $("#leaveDate").value = curDate(); $("#reason").value = ""; openModal("removeModal");
};
ACTIONS.restorePerson = async id => {
  if (!confirm("استرجاع هذا السجل إلى القوة؟")) return;
  if (await api(`/api/person/${encodeURIComponent(id)}/restore`, {method: "POST"})) {
    showToast("تم الاسترجاع إلى القوة"); load();
  }
};
ACTIONS.deleteRecord = async (id, extra) => {
  if (!confirm(`حذف سجل «${extra.name}» نهائيًا من الأرشيف؟ لا يمكن التراجع.`)) return;
  if (await api(`/api/person/${encodeURIComponent(id)}`, {method: "DELETE"})) {
    showToast("تم حذف السجل"); load();
  }
};
if (IS_OFF) ACTIONS.openLeaveFor = id => openLeave(null, id, personById(id));

/* ---------- ربط ---------- */
$$("[data-bucket]").forEach(b => b.onclick = () => {
  $$("[data-bucket]").forEach(x => x.classList.remove("active"));
  b.classList.add("active");
  BUCKET = b.dataset.bucket; $("#search").value = ""; render();
});
$("#search").oninput = render;
if ($("#restFilter")) $("#restFilter").onchange = render;
$("#addBtn").onclick = () => openPerson(null);
$("#type").onchange = updateRoles;
$("#fRestSystem").onchange = toggleRestDay;

async function load() {
  const d = await bootstrap();
  if (!d) return;
  LIST = IS_OFF ? d.officers : d.personnel;
  $("#addBtn").textContent = IS_OFF ? "＋ إضافة ضابط" : "＋ إضافة فرد";
  if (IS_OFF) {
    COMMAND = d.command || {}; MEDICAL = d.medical_officers || [];
    fillSelect($("#restFilter"), [["", "كل أنظمة الراحة"], ["__rest_now", "في راحة اليوم"],
      ...REST_SYSTEMS().map(x => [x, x])], true);
    renderAlerts(d.alerts);
    renderCommand();
    if (typeof setLeavePeople === "function") setLeavePeople(LIST.active);
  }
  render();
}
load();
