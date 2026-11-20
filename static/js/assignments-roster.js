/* معاينة «يومية التعيينات» وإعداداتها اليومية. */
let ROSTER = null;
let ROSTER_DAY = "";
let ROSTER_SELECTION = new Set();
let ROSTER_SELECTION_BEFORE = new Set();
let ROSTER_DIRTY_BEFORE = false;
let ROSTER_FILTER = "";
let ROSTER_DIRTY = false;
let ROSTER_SAVING = false;

const rosterDate = () => $("#rosterDate").value;
const rosterUrl = day => `/api/assignments-roster/${encodeURIComponent(day)}`;
const rosterIsWork = status => status === "عمل" || String(status || "").startsWith("عمل (");
const rosterIsIntervention = status => ["تدخل", "تدخل صبح", "تدخل ليل", "تدخل صبح + ليل"].includes(String(status || "").trim());

function rosterStatusClass(status) {
  if (rosterIsWork(status)) return "w";
  if (rosterIsIntervention(status)) return status.includes("ليل") ? "m" : "h";
  if (String(status || "").includes("راحة") || String(status || "").includes("اجازة")) return "rest";
  if (String(status || "").includes("فرقة")) return "cat2";
  return "cat1";
}

function rosterStatusHtml(status) {
  const value = String(status || "").trim();
  if (!value) return "";
  return `<span class="chip roster-status-chip ${rosterStatusClass(value)}">${esc(value)}</span>`;
}

function rosterDisplayData(data) {
  const excluded = new Set(ROSTER_SELECTION);
  const targetIds = new Set(data.target_officer_ids || []);
  const allRows = data.all_rows || data.rows || [];
  const rows = allRows.filter(item => targetIds.has(item.id)
    || (item.medical ? rosterIsWork(item.status) :
      (!rosterIsWork(item.status) || !excluded.has(item.id))));
  const targetItems = rows.filter(item => targetIds.has(item.id));
  const doctors = rows.filter(item => item.medical && !targetIds.has(item.id)
    && rosterIsWork(item.status));
  const normal = rows.filter(item => !item.medical && !targetIds.has(item.id));
  const right = normal.slice(0, 23).map((item, index) => ({...item, number: index + 1}));
  const left = [...targetItems, ...normal.slice(23)].map((item, index) => ({...item, number: index + 24}));
  const footerCategories = Array.isArray(data.footer_categories) ? data.footer_categories : [
    {label: "ضابط امن مركزي", count: data.central ?? 4},
    {label: "ضابط امن مواني", count: data.ports ?? 1},
  ];
  const footerTotal = footerCategories.reduce((sum, item) => sum + Number(item.count || 0), 0);
  const total = normal.length + targetItems.length + doctors.length + footerTotal;
  const counts = {
    total,
    work: rows.filter(item => rosterIsWork(item.status)).length,
    intervention: rows.filter(item => rosterIsIntervention(item.status)).length,
  };
  return {...data, rows, doctors, left, right,
    targetItems, normal, footerCategories, footerTotal,
    total, counts};
}

function rosterCell(value, cls = "") {
  return `<td class="${cls}">${esc(value || "")}</td>`;
}

function renderRoster(data) {
  data = rosterDisplayData(data);
  const left = data.left || [];
  const right = data.right || [];
  const doctors = data.doctors || [];
  const footerCategories = data.footerCategories || [];
  const footerSlots = Math.max(3, footerCategories.length);
  const clinicSlots = doctors.length <= 3 ? 4 : 1 + doctors.length;
  // The archive always reserves two merged rows for the large targets label.
  // Target officers themselves start in ordinary rows immediately below it.
  const contentExtra = Math.max(0, (2 + left.length) - 13);
  const footerStart = 14 + contentExtra;
  const clinicStart = footerStart + footerSlots + 1;
  const totalIndex = clinicStart + clinicSlots + 1;
  const rows = [];
  let leftCursor = 0;
  for (let rowIndex = 1; rowIndex <= totalIndex; rowIndex += 1) {
    const rightItem = right[rowIndex - 1] || {};
    const rightCells = rosterCells(rightItem);
    if (rowIndex === 1) {
      rows.push(`<tr>${rightCells}<td colspan="4" rowspan="2" class="roster-target">الأهداف</td></tr>`);
    } else if (rowIndex === 2) {
      rows.push(`<tr>${rightCells}</tr>`);
    } else if (rowIndex < footerStart) {
      const item = left[leftCursor] || {};
      leftCursor += 1;
      rows.push(`<tr>${rightCells}${rosterCells(item)}</tr>`);
    } else if (rowIndex >= footerStart && rowIndex < footerStart + footerSlots) {
      const footer = footerCategories[rowIndex - footerStart];
      rows.push(`<tr>${rightCells}<td colspan="4" class="roster-footer">${footer ? `( ${esc(footer.count)} ) ${esc(footer.label)}` : ""}</td></tr>`);
    } else if (rowIndex === footerStart + footerSlots) {
      rows.push(`<tr>${rightCells}<td colspan="4"></td></tr>`);
    } else if (rowIndex >= clinicStart && rowIndex < clinicStart + clinicSlots) {
      const labelSpan = clinicSlots - doctors.length;
      if (!doctors.length) {
        rows.push(`<tr>${rightCells}<td colspan="4"></td></tr>`);
      } else if (rowIndex < clinicStart + labelSpan) {
        rows.push(`<tr>${rightCells}<td colspan="4" class="roster-clinic">${rowIndex === clinicStart ? "العيادة الطبية" : ""}</td></tr>`);
      } else {
        const doctor = doctors[rowIndex - clinicStart - labelSpan] || {};
        rows.push(`<tr>${rightCells}${rosterCells(doctor)}</tr>`);
      }
    } else if (rowIndex === clinicStart + clinicSlots) {
      rows.push(`<tr>${rightCells}<td colspan="4"></td></tr>`);
    } else if (rowIndex === totalIndex) {
      rows.push(`<tr><td colspan="8" class="roster-total">الإجمالي: ${esc(data.total ?? 0)}</td></tr>`);
    } else {
      rows.push(`<tr>${rightCells}</tr>`);
    }
  }
  $("#rosterPreview").innerHTML = `<table class="table roster-table"><caption class="sr-only">${esc(data.title || "كشف التعيينات")}</caption><thead><tr>
    <th>م</th><th>الرتبة</th><th>الاسم</th><th>ملاحظات</th>
    <th>م</th><th>الرتبة</th><th>الاسم</th><th>ملاحظات</th>
  </tr></thead><tbody>${rows.join("")}</tbody></table>`;
  $("#rosterTitle").textContent = data.title || "كشف التعيينات";
  updateRosterSummary(data);
}

function rosterSelectionPeople() {
  return ROSTER?.selectable_officers || [];
}

function renderSelectionCount() {
  const people = rosterSelectionPeople();
  const selected = people.filter(person => !ROSTER_SELECTION.has(person.id)).length;
  const label = `${selected} من ${people.length}`;
  $("#rosterSelectionCount").textContent = label;
  $("#rosterSelectionModalCount").textContent = label;
}

function renderSelectionList() {
  const people = rosterSelectionPeople();
  const list = $("#rosterSelectionList");
  if (!people.length) {
    list.innerHTML = `<p class="muted">لا يوجد ضباط بحالة «عمل» متاحون للاختيار في هذا اليوم.</p>`;
    renderSelectionCount();
    return;
  }
  const query = ROSTER_FILTER.trim().toLocaleLowerCase();
  const visible = people.filter(person => !query ||
    `${person.role || ""} ${person.name || ""}`.toLocaleLowerCase().includes(query));
  if (!visible.length) {
    list.innerHTML = `<p class="muted roster-selection-empty">لا توجد نتائج مطابقة للبحث.</p>`;
    renderSelectionCount();
    return;
  }
  list.innerHTML = visible.map(person => `
    <label class="checkline roster-selection-row">
      <input type="checkbox" data-roster-officer="${esc(person.id)}" ${ROSTER_SELECTION.has(person.id) ? "" : "checked"} aria-label="اختيار ${esc(person.role)} / ${esc(person.name)}">
      <span><b>${esc(person.role)}</b><span class="sub">${esc(person.name)}</span></span>
    </label>`).join("");
  list.querySelectorAll("[data-roster-officer]").forEach(input => {
    input.onchange = () => {
      if (input.checked) ROSTER_SELECTION.delete(input.dataset.rosterOfficer);
      else ROSTER_SELECTION.add(input.dataset.rosterOfficer);
      renderSelectionCount();
      setRosterDirty(true);
    };
  });
  renderSelectionCount();
}

function openRosterSelection() {
  ROSTER_SELECTION_BEFORE = new Set(ROSTER_SELECTION);
  ROSTER_DIRTY_BEFORE = ROSTER_DIRTY;
  renderSelectionList();
  openModal("rosterSelectionModal");
}

function discardRosterSelection() {
  ROSTER_SELECTION = new Set(ROSTER_SELECTION_BEFORE);
  renderSelectionCount();
  setRosterDirty(ROSTER_DIRTY_BEFORE);
  closeModal("rosterSelectionModal", true);
}

function rosterCells(item) {
  return [item.number, item.role, item.name].map(value => rosterCell(value)).join("")
    + `<td class="roster-status">${rosterStatusHtml(item.status)}</td>`;
}

function fillSignerOptions(data) {
  const select = $("#rosterOpsSigner");
  const selected = data.config?.ops_signer_id || "";
  select.innerHTML = `<option value="">بدون توقيع</option>` +
    (data.operations_members || []).map(person =>
      `<option value="${esc(person.id)}" ${person.id === selected ? "selected" : ""}>${esc(person.role || person.rank)} / ${esc(person.name || person.full_name)}</option>`
    ).join("");
  select.value = selected;
}

function renderFooterCategories(categories) {
  const box = $("#rosterFooterCategories");
  box.innerHTML = (categories || []).map((item, index) => `
    <div class="roster-footer-edit" data-roster-footer-row>
      <label><span>اسم التصنيف</span><input class="input" data-roster-footer-label maxlength="60" value="${esc(item.label || "")}" aria-label="اسم تصنيف الذيل ${index + 1}"></label>
      <label><span>العدد</span><input class="input" data-roster-footer-count type="number" min="0" max="999" step="1" value="${Number(item.count || 0)}" aria-label="عدد تصنيف الذيل ${index + 1}"></label>
      <button class="btn roster-footer-remove" type="button" data-roster-footer-remove aria-label="حذف التصنيف ${esc(item.label || "بدون اسم")}" title="حذف التصنيف">${icon("trash")}<span class="sr-only">حذف</span></button>
      <p class="roster-inline-error" data-roster-footer-error role="alert"></p>
    </div>`).join("");
}

function updateFooterRemoveLabels() {
  document.querySelectorAll("[data-roster-footer-row]").forEach(row => {
    const label = row.querySelector("[data-roster-footer-label]")?.value.trim() || "بدون اسم";
    row.querySelector("[data-roster-footer-remove]")?.setAttribute("aria-label", `حذف التصنيف ${label}`);
  });
}

function readFooterCategories() {
  return [...document.querySelectorAll("[data-roster-footer-row]")].map(row => ({
    label: row.querySelector("[data-roster-footer-label]").value.trim(),
    count: Number(row.querySelector("[data-roster-footer-count]").value),
  }));
}

function updateRosterSummary(data) {
  const counts = data.counts || {};
  const dayText = data.weekday
    ? `${data.weekday} — ${fmt(data.date || ROSTER_DAY)}` : fmt(data.date || ROSTER_DAY);
  const total = counts.total ?? data.total ?? 0;
  const work = counts.work ?? 0;
  const intervention = counts.intervention ?? 0;
  const countsText = `إجمالي ${total} · عمل ${work} · تدخل ${intervention}`;
  const summaryHtml = [
    ["إجمالي", total, "total"],
    ["عمل", work, "work"],
    ["تدخل", intervention, "intervention"],
  ].map(([label, value, kind]) => `<span class="roster-stat-chip roster-stat-${kind}"><span>${label}</span><b>${esc(value)}</b></span>`).join("");
  $("#rosterDayLabel").textContent = dayText;
  $("#rosterSummary").innerHTML = summaryHtml;
  const pageSubtitle = document.querySelector(".page-head .titles p");
  if (pageSubtitle) {
    pageSubtitle.classList.add("roster-page-summary");
    pageSubtitle.setAttribute("aria-label", `${dayText} — ${countsText}`);
    pageSubtitle.innerHTML = `<span class="roster-page-day">${esc(dayText)}</span><span class="roster-page-stats">${summaryHtml}</span>`;
  }
}

function rosterSettingsNeedOpen(data) {
  const categories = (data.footer_categories || []).map(item => ({
    label: String(item.label || "").trim(), count: Number(item.count || 0),
  }));
  const defaults = [
    {label: "ضابط امن مركزي", count: 4},
    {label: "ضابط امن مواني", count: 1},
  ];
  const signer = data.config?.ops_signer_id || "";
  const defaultSigner = data.operations_members?.[0]?.id || "";
  return JSON.stringify(categories) !== JSON.stringify(defaults)
    || Boolean(signer && signer !== defaultSigner);
}

function syncRosterSettingsDisclosure(data) {
  const panel = $("#rosterSettings");
  if (panel) panel.open = rosterSettingsNeedOpen(data);
}

function setRosterMessage(message, bad = false, html = false) {
  const box = $("#rosterMessage");
  box.classList.toggle("is-error", bad);
  if (html) box.innerHTML = message;
  else box.textContent = message || "";
}

function setRosterDirty(value) {
  ROSTER_DIRTY = Boolean(value);
  const dirty = $("#rosterDirty");
  dirty.hidden = !ROSTER_DIRTY;
  $("#rosterSave").setAttribute("aria-label", ROSTER_DIRTY ? "حفظ التغييرات غير المحفوظة" : "حفظ إعدادات الكشف");
  updateRosterControls();
}

function updateRosterControls() {
  const closed = Boolean(ROSTER?.day_status?.closed);
  const disabled = closed || ROSTER_SAVING;
  $("#rosterSave").disabled = disabled || !ROSTER_DIRTY;
  $("#rosterSelect").disabled = closed || ROSTER_SAVING;
  $("#rosterDownload").disabled = ROSTER_SAVING;
  ["#rosterPrev", "#rosterNext", "#rosterToday", "#rosterTomorrow", "#rosterDate"].forEach(selector => {
    $(selector).disabled = ROSTER_SAVING;
  });
  $("#rosterAddFooter").disabled = disabled;
  $("#rosterOpsSigner").disabled = disabled;
  document.querySelectorAll("[data-roster-footer-label],[data-roster-footer-count],[data-roster-footer-remove]")
    .forEach(control => { control.disabled = disabled; });
}

function setRosterInputs(data) {
  renderFooterCategories(data.footer_categories || []);
  $("#rosterFooterTotal").textContent = `إجمالي تصنيفات الذيل: ${data.footer_total ?? 5}`;
  fillSignerOptions(data);
  const status = data.day_status || {};
  ROSTER.day_status = status;
  $("#rosterLock").textContent = status.closed
    ? "اليوم مقفول — العرض فقط، افتح اليوم من اليومية التفصيلية للتعديل"
    : "اليوم مفتوح للتعديل";
  $("#rosterLock").classList.toggle("is-locked", Boolean(status.closed));
  updateRosterSummary(data);
  updateRosterControls();
}

function validateFooterCategories(show = true) {
  let valid = true;
  document.querySelectorAll("[data-roster-footer-row]").forEach(row => {
    const label = row.querySelector("[data-roster-footer-label]");
    const count = row.querySelector("[data-roster-footer-count]");
    const error = row.querySelector("[data-roster-footer-error]");
    const number = Number(count.value);
    const message = !label.value.trim() ? "اكتب اسم التصنيف." :
      label.value.trim().length > 60 ? "اسم التصنيف 60 حرفًا كحد أقصى." :
      count.value === "" || !Number.isInteger(number) || number < 0 || number > 999
        ? "اكتب عددًا صحيحًا من 0 إلى 999." : "";
    label.setAttribute("aria-invalid", message && !label.value.trim() ? "true" : "false");
    count.setAttribute("aria-invalid", message && count.value === "" ? "true" : "false");
    error.textContent = show ? message : "";
    valid = valid && !message;
  });
  if (!valid) $("#rosterSettings").open = true;
  return valid;
}

function addFooterCategory(focus = true) {
  const categories = readFooterCategories();
  if (categories.length >= 8) { showToast("أقصى عدد لتصنيفات الذيل 8.", true); return null; }
  categories.push({label: "", count: 0});
  renderFooterCategories(categories);
  setRosterDirty(true);
  const input = document.querySelector("[data-roster-footer-row]:last-child [data-roster-footer-label]");
  if (focus) input?.focus();
  return input;
}

$("#rosterAddFooter").onclick = () => addFooterCategory();
$("#rosterFooterCategories").onclick = event => {
  if (!event.target.matches("[data-roster-footer-remove]")) return;
  const row = event.target.closest("[data-roster-footer-row]");
  confirmDialog({title: "حذف تصنيف الذيل؟", body: "سيختفي التصنيف من المعاينة بعد الحفظ.", confirmLabel: "حذف التصنيف", danger: true})
    .then(ok => { if (ok) { row.remove(); setRosterDirty(true); validateFooterCategories(); } });
};

$("#rosterFooterCategories").addEventListener("input", () => {
  validateFooterCategories(false);
  updateFooterRemoveLabels();
  setRosterDirty(true);
  $("#rosterFooterTotal").textContent = `إجمالي تصنيفات الذيل: ${readFooterCategories().reduce((sum, item) => sum + (Number(item.count) || 0), 0)}`;
});
$("#rosterFooterCategories").addEventListener("keydown", event => {
  if (event.key !== "Enter") return;
  if (event.target.matches("[data-roster-footer-label]")) {
    event.preventDefault();
    event.target.closest("[data-roster-footer-row]").querySelector("[data-roster-footer-count]").focus();
  } else if (event.target.matches("[data-roster-footer-count]")) {
    event.preventDefault();
    addFooterCategory();
  }
});

$("#rosterOpsSigner").onchange = () => setRosterDirty(true);

async function loadRoster(day, remember = true) {
  ROSTER_DAY = day;
  setRosterMessage("");
  $("#rosterPreview").innerHTML = skeleton("rows", 10);
  const data = await api(rosterUrl(day), {noLoader: true});
  if (!data) {
    $("#rosterPreview").innerHTML = `<div class="roster-state roster-state-error" role="alert">تعذر تحميل كشف هذا اليوم. <button class="btn" type="button" id="rosterRetry">إعادة المحاولة</button></div>`;
    $("#rosterRetry").onclick = () => loadRoster(ROSTER_DAY);
    setRosterMessage("تعذر تحميل البيانات؛ جرّب إعادة المحاولة.", true);
    return;
  }
  ROSTER = data;
  ROSTER_SELECTION = new Set(data.selection?.excluded_ids || data.excluded_officer_ids || []);
  ROSTER_FILTER = "";
  $("#rosterSelectionSearch").value = "";
  setRosterDirty(false);
  setPageDay(day, remember);          // الفتح التلقائي مايغيّرش يوم العمل المشترك؛ اختيار المستخدم بس
  setRosterInputs(data);
  syncRosterSettingsDisclosure(data);
  renderSelectionCount();
  renderRoster(data);
  window.exportDocxUrl = () => `/api/assignments-roster/${encodeURIComponent(ROSTER_DAY)}/export.docx`;
}

function shiftRoster(offset) {
  const day = addDays(rosterDate() || ROSTER_DAY, offset);
  $("#rosterDate").value = day;
  loadRoster(day);
}

$("#rosterPrev").onclick = () => shiftRoster(-1);
$("#rosterNext").onclick = () => shiftRoster(1);
$("#rosterToday").onclick = () => {
  const day = _localToday();
  $("#rosterDate").value = day;
  loadRoster(day);
};
$("#rosterTomorrow").onclick = () => {
  const day = addDays(_localToday(), 1);
  $("#rosterDate").value = day;
  loadRoster(day);
};
$("#rosterDate").onchange = () => loadRoster(rosterDate());
$("#rosterDownload").onclick = () => previewExport(window.exportDocxUrl?.(), "يومية تعيينات الضباط");
window.dailyFileDay = () => ROSTER_DAY;
$("#rosterSelect").onclick = openRosterSelection;
$("#rosterSelectAll").onclick = () => {
  rosterSelectionPeople().forEach(person => ROSTER_SELECTION.delete(person.id));
  renderSelectionList();
  setRosterDirty(true);
};
$("#rosterSelectNone").onclick = () => {
  rosterSelectionPeople().forEach(person => ROSTER_SELECTION.add(person.id));
  renderSelectionList();
  setRosterDirty(true);
};
$("#rosterApplySelection").onclick = () => {
  ROSTER.excluded_officer_ids = [...ROSTER_SELECTION];
  ROSTER.selection = {...(ROSTER.selection || {}), excluded_ids: [...ROSTER_SELECTION]};
  renderRoster(ROSTER);
  closeModal("rosterSelectionModal", true);
  setRosterDirty(true);
  showToast("تم تطبيق الاختيار على المعاينة. اضغط حفظ لتثبيته لليوم.");
};
$("#rosterSelectionCancel").onclick = discardRosterSelection;
$("#rosterSelectionClose").onclick = discardRosterSelection;
$("#rosterSelectionSearch").oninput = event => {
  ROSTER_FILTER = event.target.value;
  renderSelectionList();
};

$("#rosterSave").onclick = async () => {
  if (!ROSTER || ROSTER_SAVING || ROSTER.day_status?.closed) return;
  if (!validateFooterCategories()) return;
  const footer_categories = readFooterCategories();
  if (footer_categories.length > 8 || footer_categories.some(item =>
    !item.label || item.label.length > 60 || !Number.isInteger(item.count)
    || item.count < 0 || item.count > 999)) {
    showToast("تحقق من أسماء تصنيفات الذيل وأعدادها (0 إلى 999).", true); return;
  }
  ROSTER_SAVING = true;
  updateRosterControls();
  setRosterMessage("جارٍ حفظ إعدادات الكشف…");
  const out = await api(`/api/assignments-roster/${encodeURIComponent(ROSTER_DAY)}`, {
    ...jsonReq("PUT", {
      footer_categories, ops_signer_id: $("#rosterOpsSigner").value,
      excluded_officer_ids: [...ROSTER_SELECTION], revision: ROSTER.revision,
    }),
    onError: (body, status) => {
      if (status !== 409 || body?.code !== "stale_revision") return false;
      setRosterMessage(`تغيّرت بيانات اليوم من مكان آخر. <button type="button" class="btn" id="rosterReloadAfterConflict">إعادة تحميل آخر نسخة</button>`, true, true);
      $("#rosterReloadAfterConflict").onclick = () => loadRoster(ROSTER_DAY);
      return true;
    },
  });
  ROSTER_SAVING = false;
  updateRosterControls();
  if (!out) return;
  ROSTER = out;
  ROSTER_SELECTION = new Set(out.selection?.excluded_ids || out.excluded_officer_ids || []);
  setRosterDirty(false);
  setRosterInputs(out);
  renderRoster(out);
  setRosterMessage("");
  showToast("تم حفظ إعدادات يومية التعيينات.");
};

(async function initRoster() {
  // يوم العمل مشترك بين اليوميات كلها (core.js workDay): لو المستخدم اختار يوم في أي صفحة أو في الرابط
  // (?day=) الكشف بيفتح عليه؛ ولو ماحدش اختار (النهاردة) الكشف بيفتح على بكرة (الكشف بيتعمل لليوم اللي بعده).
  const today = (typeof META !== "undefined" && META.today) || _localToday();
  const shared = workDay();
  const day = shared !== today ? shared : addDays(today, 1);
  $("#rosterDate").value = day;
  await loadRoster(day, shared !== today);
})();
