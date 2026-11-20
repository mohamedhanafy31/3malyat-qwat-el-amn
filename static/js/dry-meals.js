/* معاينة وتحرير «أمر صرف وجبات جافة». */
let DRY = null;
let DRY_DAY = "";
let DRY_DIRTY = false;
let DRY_SAVING = false;

const dryDate = () => $("#dryDate").value;
const dryUrl = day => `/api/dry-meals/${encodeURIComponent(day)}`;
const dryNumber = value => Number.isInteger(Number(value)) ? Math.max(0, Math.min(999, Number(value))) : 0;
const dryValue = value => String(value ?? "");
const dryTotal = row => dryNumber(row.officers) + dryNumber(row.personnel) + dryNumber(row.conscripts);
const dryDash = value => Number(value || 0) ? esc(value) : "ــــ";

function dryReadRows(selector, emergency = false) {
  return [...document.querySelectorAll(`${selector} [data-dry-row]`)].map(row => {
    const out = {
      name: row.querySelector("[data-dry-name]")?.value.trim() || "",
      officers: dryNumber(row.querySelector("[data-dry-officers]")?.value),
      personnel: dryNumber(row.querySelector("[data-dry-personnel]")?.value),
      conscripts: dryNumber(row.querySelector("[data-dry-conscripts]")?.value),
      notes: row.querySelector("[data-dry-notes]")?.value.trim() || "",
    };
    if (emergency) out.source = row.dataset.drySource || "";
    return out;
  });
}

function dryRowsFromState(rows, emergency = false) {
  return (rows || []).map(row => ({
    name: dryValue(row.name), officers: dryNumber(row.officers),
    personnel: dryNumber(row.personnel), conscripts: dryNumber(row.conscripts),
    notes: dryValue(row.notes), ...(emergency ? {source: dryValue(row.source)} : {}),
  }));
}

function dryRowHtml(row, index, emergency = false) {
  const source = emergency ? `data-dry-source="${esc(row.source || "")}"` : "";
  return `<div class="dry-row" data-dry-row data-dry-index="${index}" ${source}>
    <div class="dry-row-number">${index + 1}</div>
    <label><span>اسم الخدمة</span><input data-dry-name maxlength="80" value="${esc(row.name || "")}" aria-label="اسم الخدمة ${index + 1}"></label>
    <label><span>ضباط</span><input data-dry-officers type="number" min="0" max="999" step="1" value="${dryNumber(row.officers)}" aria-label="ضباط ${index + 1}"></label>
    <label><span>أفراد</span><input data-dry-personnel type="number" min="0" max="999" step="1" value="${dryNumber(row.personnel)}" aria-label="أفراد ${index + 1}"></label>
    <label><span>مجندين</span><input data-dry-conscripts type="number" min="0" max="999" step="1" value="${dryNumber(row.conscripts)}" aria-label="مجندين ${index + 1}"></label>
    <label class="dry-note"><span>ملاحظات</span><input data-dry-notes maxlength="120" value="${esc(row.notes || "")}" aria-label="ملاحظات ${index + 1}"></label>
    <output class="dry-row-total" aria-label="إجمالي الصف">${dryTotal(row)}</output>
    <button type="button" class="btn dry-remove" data-dry-remove aria-label="حذف الخدمة ${index + 1}">×</button>
  </div>`;
}

// الترقيم لكل جدول لوحده (الثابت من 1، والطوارئ من 1) وبعد أي حذف.
function dryRenumber(selector) {
  document.querySelectorAll(`${selector} [data-dry-row]`).forEach((row, i) => {
    row.dataset.dryIndex = i;
    row.querySelector(".dry-row-number").textContent = i + 1;
    [["[data-dry-name]", "اسم الخدمة"], ["[data-dry-officers]", "ضباط"], ["[data-dry-personnel]", "أفراد"],
     ["[data-dry-conscripts]", "مجندين"], ["[data-dry-notes]", "ملاحظات"], ["[data-dry-remove]", "حذف الخدمة"]]
      .forEach(([sel, label]) => row.querySelector(sel)?.setAttribute("aria-label", `${label} ${i + 1}`));
  });
}

function renderDryEditors() {
  const fixed = DRY?.config?.fixed_rows || DRY?.fixed_rows || [];
  const emergency = DRY?.config?.emergency_rows || DRY?.emergency_rows || [];
  $("#dryFixedEditor").innerHTML = fixed.map((row, i) => dryRowHtml(row, i)).join("");
  $("#dryEmergencyRows").innerHTML = emergency.map((row, i) => dryRowHtml(row, i, true)).join("");
  $("#dryEmergencyEnabled").checked = Boolean(DRY?.config?.emergency_enabled ?? DRY?.emergency_enabled);
  const signer = DRY?.config?.ops_signer_id || "";
  $("#dryOpsSigner").innerHTML = `<option value="">بدون توقيع</option>` +
    (DRY?.operations_members || []).map(person => `<option value="${esc(person.id)}">${esc(person.role || person.rank)} / ${esc(person.name)}</option>`).join("");
  $("#dryOpsSigner").value = signer;
  $("#dryEmergencyEditor").classList.toggle("hidden", !$("#dryEmergencyEnabled").checked);
  dryUpdateControls();
}

function dryHeader() {
  return `<thead><tr><th rowspan="2">م</th><th rowspan="2">اسم الخدمة</th><th colspan="3">الأعداد</th><th rowspan="2">الإجمالي</th><th rowspan="2">ملاحظات</th></tr><tr><th>ضباط</th><th>أفراد</th><th>مجندين</th></tr></thead>`;
}

function dryTable(rows, label) {
  const values = rows || [];
  const total = values.reduce((sum, row) => sum + dryTotal(row), 0);
  const body = values.map((row, index) => `<tr><td>${index + 1}</td><td class="dry-service-cell">${esc(row.name || "")}</td><td>${dryDash(row.officers)}</td><td>${dryDash(row.personnel)}</td><td>${dryDash(row.conscripts)}</td><td class="dry-total-cell">${dryDash(dryTotal(row))}</td><td class="dry-note-cell">${esc(row.notes || "")}</td></tr>`).join("");
  return `<table class="dry-table"><caption class="sr-only">${esc(label)}</caption>${dryHeader()}<tbody>${body}<tr class="dry-grand-total"><th colspan="6">${esc(label)}</th><th>${esc(total)} وجبة</th></tr></tbody></table>`;
}

function renderDryPreview() {
  if (!DRY) return;
  const fixed = DRY.config?.fixed_rows || DRY.fixed_rows || [];
  const emergency = DRY.config?.emergency_rows || DRY.emergency_rows || [];
  const enabled = Boolean(DRY.config?.emergency_enabled ?? DRY.emergency_enabled);
  const dateText = `${esc(DRY.weekday || "")} الموافق ${esc(String(DRY.date || "").replaceAll("-", "/"))} م`;
  const fixedText = `أمر صرف وجبات (جافة) للخدمات الثابتة عن يوم ${dateText} وكونهم مبيت 24 ساعة خدمة ولتعذر وصول التعيينات الطازجة لهم بصورة جيدة.`;
  let html = `<div class="dry-paper"><div class="dry-letterhead"><div><b>مديرية أمن السويس</b><b>إدارة قوات الأمن</b><b>قسم العمليات</b></div><b>أمر عمليات رقم ( ) عن شهر ( ) لسنة ${esc(String(DRY.date || "").slice(0, 4))}</b></div><h4>أمر عمليات ثابت</h4><p>${fixedText}</p>${dryTable(fixed, "أجمالي الوجبات الجافة المنصرفة")}`;
  if (enabled) {
    const padded = emergency.length < 4 ? [...emergency, ...Array.from({length: 4 - emergency.length}, () => ({name: "", officers: 0, personnel: 0, conscripts: 0, notes: ""}))] : emergency;
    html += `<hr><h4>أمر عمليات طارئ</h4><p>أمر صرف وجبات (جافة) للخدمات الطارئة عن يوم ${dateText} وكونهم مبيت 24 ساعة خدمة ولتعذر وصول التعيينات الطازجة لهم بصورة جيدة.</p>${dryTable(padded, "اجمالي الوجبات الجافة المنصرفة")}`;
  }
  html += `<div class="dry-preview-signatures"><div><b>بلوكامين قسم العمليات</b><span>${esc(DRY.ops_signer?.rank || "")}/</span><span>(${esc(DRY.ops_signer?.name || "")})</span></div><div><b>رئيس قسم العمليات</b><span>${esc(DRY.chief?.rank || "")}/</span><span>(${esc(DRY.chief?.name || "")})</span></div></div></div>`;
  $("#dryPreview").innerHTML = html;
  $("#dryTitle").textContent = `أمر صرف وجبات جافة عن يوم ${DRY.weekday || ""} الموافق ${String(DRY.date || "").replaceAll("-", "/")} م`;
  $("#dryDayLabel").textContent = `${DRY.weekday || ""} — ${fmt(DRY.date || DRY_DAY)}`;
  const total = (fixed || []).reduce((s, row) => s + dryTotal(row), 0) + (enabled ? emergency.reduce((s, row) => s + dryTotal(row), 0) : 0);
  $("#drySummary").innerHTML = `<span class="dry-stat"><span>الثابتة</span><b>${esc((fixed || []).reduce((s, row) => s + dryTotal(row), 0))}</b></span><span class="dry-stat"><span>الطوارئ</span><b>${esc(enabled ? emergency.reduce((s, row) => s + dryTotal(row), 0) : 0)}</b></span><span class="dry-stat dry-stat-total"><span>الإجمالي</span><b>${esc(total)}</b></span>`;
}

function drySetDirty(value) {
  DRY_DIRTY = Boolean(value);
  if (DRY) {
    DRY.config.fixed_rows = dryReadRows("#dryFixedEditor");
    DRY.config.emergency_rows = dryReadRows("#dryEmergencyRows", true);
    DRY.config.emergency_enabled = $("#dryEmergencyEnabled").checked;
    DRY.config.ops_signer_id = $("#dryOpsSigner")?.value || DRY.config.ops_signer_id || "";
  }
  $("#dryDirty").hidden = !DRY_DIRTY;
  dryUpdateControls();
  renderDryPreview();
}

function dryUpdateControls() {
  const disabled = Boolean(DRY?.day_status?.closed) || DRY_SAVING;
  $("#drySave").disabled = disabled || !DRY_DIRTY;
  $("#dryDownload").disabled = DRY_SAVING;
  ["#dryPrev", "#dryNext", "#dryToday", "#dryTomorrow", "#dryDate", "#dryAddFixed", "#dryEmergencyEnabled", "#dryPickEmergency"].forEach(id => { if ($(id)) $(id).disabled = disabled; });
  document.querySelectorAll("#dryFixedEditor input,#dryEmergencyEditor input,[data-dry-remove]").forEach(control => { control.disabled = disabled; });
  if ($("#dryOpsSigner")) $("#dryOpsSigner").disabled = disabled;
}

function dryMessage(text, bad = false, html = false) {
  const box = $("#dryMessage"); box.classList.toggle("is-error", bad);
  if (html) box.innerHTML = text; else box.textContent = text || "";
}

function dryCurrentBody() {
  return {fixed_rows: dryReadRows("#dryFixedEditor"), emergency_enabled: $("#dryEmergencyEnabled").checked,
    emergency_rows: dryReadRows("#dryEmergencyRows", true), ops_signer_id: $("#dryOpsSigner")?.value || DRY?.config?.ops_signer_id || "",
    revision: DRY?.revision};
}

function dryValidate(body) {
  if (!body.fixed_rows.length || body.fixed_rows.length > 12) return "أضف من 1 إلى 12 خدمة ثابتة.";
  for (const row of [...body.fixed_rows, ...(body.emergency_enabled ? body.emergency_rows : [])]) {
    if (!row.name) return "اكتب اسم كل خدمة.";
    if (row.name.length > 80) return "اسم الخدمة 80 حرفًا كحد أقصى.";
    if (row.notes.length > 120) return "الملاحظات 120 حرفًا كحد أقصى.";
    if ([row.officers, row.personnel, row.conscripts].some(n => !Number.isInteger(n) || n < 0 || n > 999)) return "الأعداد أرقام صحيحة من 0 إلى 999.";
  }
  if (body.emergency_rows.length > 8) return "أقصى عدد لخدمات الطوارئ 8.";
  const seen = new Set();
  for (const row of body.emergency_rows) {
    const key = row.name.replace(/[إأآا]/g, "ا").replace(/ى/g, "ي").replace(/ة/g, "ه").replace(/\s+/g, " ").trim();
    if (seen.has(key)) return "لا يمكن اختيار خدمة الطوارئ نفسها مرتين.";
    seen.add(key);
  }
  return "";
}

async function saveDry(showToastOnSuccess = true) {
  if (!DRY || DRY_SAVING || DRY.day_status?.closed) return false;
  const body = dryCurrentBody();
  const error = dryValidate(body);
  if (error) { dryMessage(error, true); showToast(error, true); return false; }
  DRY_SAVING = true; dryUpdateControls(); dryMessage("جارٍ حفظ أمر الوجبات…");
  const out = await api(dryUrl(DRY_DAY), {...jsonReq("PUT", body), onError: (response, status) => {
    if (status !== 409 || response?.code !== "stale_revision") return false;
    dryMessage(`تغيّرت بيانات اليوم من مكان آخر. <button type="button" class="btn" id="dryReloadConflict">إعادة تحميل آخر نسخة</button>`, true, true);
    $("#dryReloadConflict").onclick = () => loadDry(DRY_DAY);
    return true;
  }});
  DRY_SAVING = false; dryUpdateControls();
  if (!out) return false;
  DRY = out; DRY_DIRTY = false; $("#dryDirty").hidden = true; dryMessage(""); renderDryEditors(); renderDryPreview(); dryUpdateControls();
  if (showToastOnSuccess) showToast("تم حفظ أمر صرف الوجبات الجافة.");
  return true;
}

function openDryPicker() {
  const selected = new Set((DRY?.config?.emergency_rows || []).map(row => row.name));
  const groups = DRY?.pickable_services || {};
  $("#dryPickerGroups").innerHTML = Object.entries(groups).map(([group, items]) => `<section class="dry-picker-group"><h3>${esc(group)}</h3>${(items || []).map(item => {
    const disabled = selected.has(item.name);
    return `<button type="button" class="dry-picker-item" data-dry-pick="${dataAttr(item)}" ${disabled ? "disabled" : ""}><span>${esc(item.name)}</span><small>${esc(`${item.officers || 0} ضباط · ${item.personnel || 0} أفراد · ${item.conscripts || 0} مجندين`)}</small></button>`;
  }).join("") || `<p class="muted">لا توجد خدمات في هذه المجموعة.</p>`}</section>`).join("");
  openModal("dryPickerModal");
}

$("#dryFixedEditor").addEventListener("input", () => { drySetDirty(true); });
$("#dryEmergencyRows").addEventListener("input", () => { drySetDirty(true); });
document.addEventListener("click", event => {
  const remove = event.target.closest("[data-dry-remove]");
  if (remove) {
    remove.closest("[data-dry-row]")?.remove();
    dryRenumber("#dryFixedEditor"); dryRenumber("#dryEmergencyRows");
    drySetDirty(true);
    return;
  }
  const pick = event.target.closest("[data-dry-pick]");
  if (pick) {
    const item = JSON.parse(pick.dataset.dryPick);
    const rows = DRY.config.emergency_rows || [];
    rows.push({...item, notes: ""}); DRY.config.emergency_rows = rows;
    closeModal("dryPickerModal", true); renderDryEditors(); drySetDirty(true);
  }
});
$("#dryAddFixed").onclick = () => {
  const rows = dryReadRows("#dryFixedEditor");
  if (rows.length >= 12) { showToast("أقصى عدد للخدمات الثابتة 12.", true); return; }
  rows.push({name: "", officers: 0, personnel: 0, conscripts: 0, notes: ""});
  DRY.config.fixed_rows = rows; renderDryEditors(); drySetDirty(true);
  document.querySelector("#dryFixedEditor [data-dry-row]:last-child [data-dry-name]")?.focus();
};
$("#dryEmergencyEnabled").onchange = () => { DRY.config.emergency_enabled = $("#dryEmergencyEnabled").checked; renderDryEditors(); drySetDirty(true); };
$("#dryOpsSigner").onchange = () => { DRY.config.ops_signer_id = $("#dryOpsSigner").value; drySetDirty(true); };
$("#dryPickEmergency").onclick = openDryPicker;
$("#dryPickerCancel").onclick = () => closeModal("dryPickerModal", true);
$("#dryPickerClose").onclick = () => closeModal("dryPickerModal", true);
$("#drySave").onclick = () => saveDry();

async function loadDry(day, remember = true) {
  DRY_DAY = day; dryMessage(""); $("#dryPreview").innerHTML = skeleton("rows", 8);
  const data = await api(dryUrl(day), {noLoader: true});
  if (!data) { dryMessage("تعذر تحميل أمر هذا اليوم؛ جرّب إعادة المحاولة.", true); return; }
  DRY = data; DRY_DIRTY = false; $("#dryDirty").hidden = true; setPageDay(day, remember); renderDryEditors(); dryUpdateControls();
  $("#dryLock").textContent = data.day_status?.closed ? "اليوم مقفول — العرض فقط، افتح اليوم من اليومية التفصيلية للتعديل" : "اليوم مفتوح للتعديل";
  $("#dryLock").classList.toggle("is-locked", Boolean(data.day_status?.closed));
  renderDryPreview(); window.exportDocxUrl = () => `/api/dry-meals/${encodeURIComponent(DRY_DAY)}/export.docx`;
}
function shiftDry(offset) { const day = addDays(dryDate() || DRY_DAY, offset); $("#dryDate").value = day; loadDry(day); }
$("#dryPrev").onclick = () => shiftDry(-1); $("#dryNext").onclick = () => shiftDry(1);
$("#dryToday").onclick = () => { const day = _localToday(); $("#dryDate").value = day; loadDry(day); };
$("#dryTomorrow").onclick = () => { const day = addDays(_localToday(), 1); $("#dryDate").value = day; loadDry(day); };
$("#dryDate").onchange = () => loadDry(dryDate());
$("#dryDownload").onclick = async () => { if (DRY_DIRTY && !(await saveDry(false))) return; previewExport(window.exportDocxUrl?.(), "أمر صرف وجبات جافة"); };
window.dailyFileDay = () => DRY_DAY;

(async function initDryMeals() {
  const day = workDay();
  $("#dryDate").value = day;
  await loadDry(day, false);
})();
