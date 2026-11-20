/* معاينة «يومية التعيينات» وإعداداتها اليومية. */
let ROSTER = null;
let ROSTER_DAY = "";
let ROSTER_SELECTION = new Set();
let ROSTER_SELECTION_BEFORE = new Set();

const rosterDate = () => $("#rosterDate").value;
const rosterUrl = day => `/api/assignments-roster/${encodeURIComponent(day)}`;

function rosterDisplayData(data) {
  const excluded = new Set(ROSTER_SELECTION);
  const targetIds = new Set(data.target_officer_ids || []);
  const allRows = data.all_rows || data.rows || [];
  const rows = allRows.filter(item => targetIds.has(item.id)
    || (item.medical ? item.status === "عمل" :
      (item.status !== "عمل" || !excluded.has(item.id))));
  const targetItems = rows.filter(item => targetIds.has(item.id));
  const doctors = rows.filter(item => item.medical && !targetIds.has(item.id)
    && item.status === "عمل");
  const normal = rows.filter(item => !item.medical && !targetIds.has(item.id));
  const right = normal.slice(0, 23).map((item, index) => ({...item, number: index + 1}));
  const left = [...targetItems, ...normal.slice(23)].map((item, index) => ({...item, number: index + 24}));
  const footerCategories = Array.isArray(data.footer_categories) ? data.footer_categories : [
    {label: "ضابط امن مركزي", count: data.central ?? 4},
    {label: "ضابط امن مواني", count: data.ports ?? 1},
  ];
  const footerTotal = footerCategories.reduce((sum, item) => sum + Number(item.count || 0), 0);
  return {...data, rows, doctors, left, right,
    targetItems, normal, footerCategories, footerTotal,
    total: normal.length + targetItems.length + doctors.length + footerTotal};
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
  $("#rosterPreview").innerHTML = `<table class="table roster-table"><thead><tr>
    <th>م</th><th>الرتبة</th><th>الاسم</th><th>ملاحظات</th>
    <th>م</th><th>الرتبة</th><th>الاسم</th><th>ملاحظات</th>
  </tr></thead><tbody>${rows.join("")}</tbody></table>`;
  $("#rosterTitle").textContent = data.title || "كشف التعيينات";
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
  list.innerHTML = people.map(person => `
    <label class="checkline roster-selection-row">
      <input type="checkbox" data-roster-officer="${esc(person.id)}" ${ROSTER_SELECTION.has(person.id) ? "" : "checked"}>
      <span>${esc(person.role)} / ${esc(person.name)}</span>
    </label>`).join("");
  list.querySelectorAll("[data-roster-officer]").forEach(input => {
    input.onchange = () => {
      if (input.checked) ROSTER_SELECTION.delete(input.dataset.rosterOfficer);
      else ROSTER_SELECTION.add(input.dataset.rosterOfficer);
      renderSelectionCount();
    };
  });
  renderSelectionCount();
}

function openRosterSelection() {
  ROSTER_SELECTION_BEFORE = new Set(ROSTER_SELECTION);
  renderSelectionList();
  openModal("rosterSelectionModal");
}

function discardRosterSelection() {
  ROSTER_SELECTION = new Set(ROSTER_SELECTION_BEFORE);
  renderSelectionCount();
  closeModal("rosterSelectionModal", true);
}

function rosterCells(item) {
  return [item.number, item.role, item.name, item.status].map(value => rosterCell(value)).join("");
}

function fillSignerOptions(data) {
  const select = $("#rosterOpsSigner");
  const selected = data.config?.ops_signer_id || "";
  select.innerHTML = `<option value="">بدون توقيع</option>` +
    (data.operations_members || []).map(person =>
      `<option value="${esc(person.id)}" ${person.id === selected ? "selected" : ""}>${esc(person.role)} / ${esc(person.short_name || person.name)}</option>`
    ).join("");
  select.value = selected;
}

function renderFooterCategories(categories) {
  const box = $("#rosterFooterCategories");
  box.innerHTML = (categories || []).map((item, index) => `
    <div class="roster-footer-edit" data-roster-footer-row>
      <input class="input" data-roster-footer-label maxlength="60" value="${esc(item.label || "")}" aria-label="اسم تصنيف الذيل ${index + 1}">
      <input class="input" data-roster-footer-count type="number" min="0" max="999" value="${Number(item.count || 0)}" aria-label="عدد تصنيف الذيل ${index + 1}">
      <button class="mini danger" type="button" data-roster-footer-remove>حذف</button>
    </div>`).join("");
}

function readFooterCategories() {
  return [...document.querySelectorAll("[data-roster-footer-row]")].map(row => ({
    label: row.querySelector("[data-roster-footer-label]").value.trim(),
    count: Number(row.querySelector("[data-roster-footer-count]").value),
  }));
}

function setRosterInputs(data) {
  renderFooterCategories(data.footer_categories || []);
  $("#rosterFooterTotal").textContent = `إجمالي تصنيفات الذيل: ${data.footer_total ?? 5}`;
  fillSignerOptions(data);
  const status = data.day_status || {};
  $("#rosterLock").textContent = status.closed ? "اليوم مقفول — العرض فقط" : "اليوم مفتوح";
  $("#rosterSave").disabled = Boolean(status.closed);
}

$("#rosterAddFooter").onclick = () => {
  const categories = readFooterCategories();
  if (categories.length >= 8) { showToast("أقصى عدد لتصنيفات الذيل 8.", true); return; }
  categories.push({label: "", count: 0});
  renderFooterCategories(categories);
};
$("#rosterFooterCategories").onclick = event => {
  if (!event.target.matches("[data-roster-footer-remove]")) return;
  event.target.closest("[data-roster-footer-row]").remove();
};

async function loadRoster(day) {
  ROSTER_DAY = day;
  $("#rosterPreview").innerHTML = skeleton("rows", 10);
  const data = await api(rosterUrl(day), {noLoader: true});
  if (!data) return;
  ROSTER = data;
  ROSTER_SELECTION = new Set(data.selection?.excluded_ids || data.excluded_officer_ids || []);
  setRosterInputs(data);
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
$("#rosterTomorrow").onclick = () => {
  const day = addDays(_localToday(), 1);
  $("#rosterDate").value = day;
  loadRoster(day);
};
$("#rosterDate").onchange = () => loadRoster(rosterDate());
$("#rosterDownload").onclick = () => previewExport(window.exportDocxUrl?.(), "يومية تعيينات الضباط");
$("#rosterSelect").onclick = openRosterSelection;
$("#rosterSelectAll").onclick = () => {
  rosterSelectionPeople().forEach(person => ROSTER_SELECTION.delete(person.id));
  renderSelectionList();
};
$("#rosterSelectNone").onclick = () => {
  rosterSelectionPeople().forEach(person => ROSTER_SELECTION.add(person.id));
  renderSelectionList();
};
$("#rosterApplySelection").onclick = () => {
  ROSTER.excluded_officer_ids = [...ROSTER_SELECTION];
  ROSTER.selection = {...(ROSTER.selection || {}), excluded_ids: [...ROSTER_SELECTION]};
  renderRoster(ROSTER);
  closeModal("rosterSelectionModal", true);
  showToast("تم تطبيق الاختيار على المعاينة. اضغط حفظ لتثبيته لليوم.");
};
$("#rosterSelectionCancel").onclick = discardRosterSelection;
$("#rosterSelectionClose").onclick = discardRosterSelection;

$("#rosterSave").onclick = async () => {
  if (!ROSTER) return;
  const footer_categories = readFooterCategories();
  if (footer_categories.length > 8 || footer_categories.some(item =>
    !item.label || item.label.length > 60 || !Number.isInteger(item.count)
    || item.count < 0 || item.count > 999)) {
    showToast("تحقق من أسماء تصنيفات الذيل وأعدادها (0 إلى 999).", true); return;
  }
  const out = await api(`/api/assignments-roster/${encodeURIComponent(ROSTER_DAY)}`, jsonReq("PUT", {
    footer_categories, ops_signer_id: $("#rosterOpsSigner").value,
    excluded_officer_ids: [...ROSTER_SELECTION], revision: ROSTER.revision,
  }));
  if (!out) return;
  ROSTER = out;
  ROSTER_SELECTION = new Set(out.selection?.excluded_ids || out.excluded_officer_ids || []);
  setRosterInputs(out);
  renderRoster(out);
  showToast("تم حفظ إعدادات يومية التعيينات.");
};

(async function initRoster() {
  const day = addDays(_localToday(), 1);
  $("#rosterDate").value = day;
  await loadRoster(day);
})();
