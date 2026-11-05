/* يومية الحملة — تسكين سريع للسائق والمركبة مع حفظ فوري. */
let CAMPAIGN = null, DAY = null;
const CAMPAIGN_TYPE_FILTERS = new Map();
const GROUP_SELECTION = new Set();   // خدمات محددة للتجميع (ids)
let CAMPAIGN_WRITE_QUEUE = Promise.resolve();
let CAMPAIGN_SAVE_ERROR = "";
let CAMPAIGN_PLATES_DRAFT = null;

window.dailyFileDay = () => DAY;
window.exportDocxUrl = () => `/api/campaign/${DAY}/export.docx`;

const campaignServices = () => CAMPAIGN?.service_rows || CAMPAIGN?.services || [];
const rowSets = () => [...(CAMPAIGN?.lorries || []), ...(CAMPAIGN?.appointments || []),
  ...campaignServices(), ...(CAMPAIGN?.daily || []), ...(CAMPAIGN?.posts || [])];
const rowBy = id => rowSets().find(row => row.id === id);

async function campaignWrite(url, method, body = {}) {
  const writeDay = DAY;
  const run = async () => {
    let errorText = "";
    const out = await api(url, {
      ...jsonReq(method, {...body, revision: CAMPAIGN?.revision}),
      onError(payload) { errorText = payload?.error || ""; return false; },
    });
    if (!out) {
      CAMPAIGN_SAVE_ERROR = errorText || "لم يُحفظ التعديل. أُعيد تحميل بيانات اليومية من الخادم.";
      if (DAY === writeDay) await loadDay(writeDay);
      return null;
    }
    CAMPAIGN_SAVE_ERROR = "";
    if (DAY === writeDay) CAMPAIGN = out;
    return out;
  };
  const result = CAMPAIGN_WRITE_QUEUE.then(run, run);
  CAMPAIGN_WRITE_QUEUE = result.then(() => undefined, () => undefined);
  return result;
}

async function saveRow(row, body) {
  const scroll = window.scrollY;
  const out = await campaignWrite(`/api/campaign/${DAY}/${row.kind}/${encodeURIComponent(row.id)}`, "PUT", body);
  if (!out) return;
  render();
  window.scrollTo({top: scroll, behavior: "instant"});
}

function rowStateClass(row) {
  return ` campaign-status-${row.status || "empty"}`;
}

function statusPill(row) {
  return `<span class="chip campaign-status-pill campaign-status-pill-${esc(row.status || "empty")}">${esc(row.status_text || "غير متسكن")}</span>`;
}

function driverDisplay(driver) {
  if (!driver?.name) return "";
  return driver.role ? `${driver.role} / ${driver.name}` : driver.name;
}

function driverOptions(row, options = {}) {
  const selected = row.driver?.kind && row.driver.kind !== "text" ? `${row.driver.kind}|${row.driver.id}` : "";
  const fullValue = driverDisplay(row.driver);
  const driverMissing = (row.missing || []).includes("driver");
  const personnel = CAMPAIGN.pickers?.drivers?.personnel || [];
  const conscripts = CAMPAIGN.pickers?.drivers?.conscripts || [];
  const pickerValues = new Set([
    ...personnel.map(person => `personnel|${person.id}`),
    ...conscripts.map(person => `conscript|${person.id}`),
  ]);
  const groups = (list, label, withRole) => `<optgroup label="${esc(label)}">${list.map(person => {
    const text = withRole && person.role ? `${person.role}/ ${person.name}` : person.name;
    return `<option value="${esc(withRole ? `personnel|${person.id}` : `conscript|${person.id}`)}"${selected === (withRole ? `personnel|${person.id}` : `conscript|${person.id}`) ? " selected" : ""}>${esc(text)}</option>`;
  }).join("")}</optgroup>`;
  const savedOption = selected && !pickerValues.has(selected)
    ? `<option value="${esc(selected)}" selected>${esc(fullValue || row.driver.name)}</option>` : "";
  const custom = row.driver?.kind === "text" ? ` data-custom-value="${esc(row.driver.name)}"` : "";
  const full = fullValue ? ` data-full-value="${esc(fullValue)}" title="${esc(fullValue)}"` : "";
  const quiet = driverMissing ? " campaign-driver-gap" : " campaign-driver-quiet-empty";
  return `<select class="campaign-inline-select campaign-driver-select${quiet}" data-driver-row="${esc(row.id)}" data-combo-custom data-combo-custom-option="none" data-maxlength="200"${custom}${full} aria-label="السائق في ${esc(row.name)}">
    <option value="">${esc(options.emptyLabel || "— بدون سائق —")}</option>${savedOption}${groups(personnel, "الأفراد السواقين", true)}${groups(conscripts, "المجندون", false)}</select>`;
}

function vehicleOptions(row) {
  const selected = row.vehicle?.id || "";
  const type = CAMPAIGN_TYPE_FILTERS.get(row.id) ?? row.vehicle?.type ?? "";
  const available = (CAMPAIGN.pickers?.vehicles || []).filter(vehicle => !type || vehicle.type === type);
  const selectedVehicle = (CAMPAIGN.pickers?.vehicles || []).find(vehicle => vehicle.id === selected);
  const choices = selectedVehicle && !available.some(vehicle => vehicle.id === selected)
    ? [selectedVehicle, ...available] : available;
  const noMatches = type && !available.length;
  return `<select class="campaign-inline-select" data-vehicle-row="${esc(row.id)}" aria-label="رقم المركبة في ${esc(row.name)}">
    <option value="">اختر مركبة</option>${noMatches ? `<option disabled>لا توجد مركبات من هذا النوع</option>` : ""}${choices.map(vehicle => `<option value="${esc(vehicle.id)}"${vehicle.id === selected ? " selected" : ""}${vehicle.status === "disabled" ? " data-disabled=" + JSON.stringify(true) : ""}>${esc(vehicle.label)}${vehicle.status === "disabled" ? " (معطلة)" : ""}</option>`).join("")}</select>`;
}

function vehicleTypeOptions(row) {
  const selected = CAMPAIGN_TYPE_FILTERS.get(row.id) ?? row.vehicle?.type ?? "";
  return `<select class="campaign-inline-select" data-type-row="${esc(row.id)}" aria-label="نوع المركبة في ${esc(row.name)}">
    <option value="">اختر النوع</option>${(CAMPAIGN.pickers?.types || []).map(type => `<option value="${esc(type)}"${type === selected ? " selected" : ""}>${esc(type)}</option>`).join("")}</select>`;
}

function warningChips(row) {
  const warnings = row.warnings || [];
  const inherited = row.inherited ? `<span class="chip muted-chip campaign-inherited">من اليوم السابق</span>` : "";
  const warningText = warnings.length
    ? `<span class="campaign-row-warnings">${icon("alert")} ${esc(warnings.join(" — "))}</span>` : "";
  return `${statusPill(row)}${inherited}${warningText}`;
}

function serviceCell(row, allowAttach) {
  const chips = (row.attached || []).map(item => `<span class="chip campaign-attach-chip">${esc(item.name)}<button type="button" data-action="detachCampaignService" data-id="${esc(row.id)}" data-extra="${dataAttr(item)}" aria-label="إزالة ${esc(item.name)}">×</button></span>`).join("");
  const add = allowAttach ? `<button type="button" class="mini btn-xs campaign-add-service" data-action="openCampaignAttach" data-id="${esc(row.id)}">${icon("plus")} إضافة خدمة</button>` : "";
  return `<div class="campaign-service-name"><strong>${esc(row.base_name || row.name)}</strong>${chips}${add}${warningChips(row)}</div>`;
}

function campaignRow(row, allowAttach) {
  const driver = row.driver;
  if (row.kind === "group") return groupCampaignRow(row);
  if (row.kind === "service") return serviceCampaignRow(row);
  return `<tr class="campaign-row${rowStateClass(row)}${row.warnings?.length ? " has-warning" : ""}">
    <td class="name">${serviceCell(row, allowAttach)}</td>
    <td class="campaign-driver-cell">${driverOptions(row)}</td>
    <td dir="ltr">${vehicleOptions(row)}</td>
    <td><div class="campaign-vehicle-type">${vehicleTypeOptions(row)}${row.vehicle ? `<div class="sub">${esc(row.vehicle.model || "")}${row.vehicle.origin === "external" ? `${row.vehicle.model ? " — " : ""}خارجية: ${esc(row.vehicle.party)}` : ""}</div>` : ""}</div></td>
    <td class="col-actions">${row.kind === "daily" ? rowMenu([{action: "removeCampaignDaily", id: row.id, extra: {name: row.name}, label: "إزالة", danger: true}]) : "—"}</td>
  </tr>`;
}

function serviceCampaignRow(row) {
  const vehicles = row.service_vehicles || [];
  const directVehicles = vehicles.filter(item => item.source === "direct");
  const carrier = vehicles.find(item => item.source === "lorry");
  const carriedOnly = !directVehicles.length && !!carrier;
  const lines = vehicles.map(item => {
    const vehicle = item.vehicle || {};
    const plate = vehicle.plate || item.plate || "بدون مركبة";
    const type = vehicle.type || "نوع غير محدد";
    const driver = item.driver?.name || "بدون سائق";
    return item.source === "lorry"
      ? `<span><b>لوري ${esc(item.lorry_name || item.lorry_id || "")}</b> — <span dir="ltr">${esc(plate)}</span> — ${esc(driver)}</span>`
      : `<span><span dir="ltr">${esc(plate)}</span> — ${esc(type)} — ${esc(driver)}</span>`;
  }).join("");
  const details = lines || `<span class="campaign-unassigned">غير متسكن</span>`;
  const groupPick = carriedOnly ? "" : `<label class="check-label campaign-group-pick"><input type="checkbox" data-group-pick="${esc(row.id)}"${GROUP_SELECTION.has(row.id) ? " checked" : ""} aria-label="تحديد ${esc(row.base_name || row.name)} للتجميع"></label>`;
  const driverCell = carriedOnly
    ? `<span class="campaign-carried-driver" title="${esc(driverDisplay(carrier.driver) || "اللوري بدون سائق")}">${esc(driverDisplay(carrier.driver) || "اللوري بدون سائق")}</span>`
    : driverOptions(row, {emptyLabel: directVehicles.length && !(row.missing || []).includes("driver") ? "حسب كل مركبة" : "— بدون سائق —"});
  return `<tr class="campaign-row${rowStateClass(row)}${row.warnings?.length ? " has-warning" : ""}${row.category_break ? " campaign-cat-break" : ""}" data-vehicle-category="${esc(row.vehicle_category || "")}">
    <td class="name"><div class="campaign-service-name">${groupPick}<strong>${esc(row.base_name || row.name)}</strong>${(row.attached || []).map(item => `<span class="chip campaign-attach-chip">${esc(item.name)}</span>`).join("")}${warningChips(row)}</div></td>
    <td class="campaign-driver-cell">${driverCell}</td>
    <td colspan="2"><div class="campaign-service-assignment">${details}<button type="button" class="mini btn-xs" data-action="openCampaignServiceVehicles" data-id="${esc(row.id)}">${icon("edit")} مركبات وأفراد</button></div></td>
    <td class="col-actions">—</td>
  </tr>`;
}

function groupCampaignRow(row) {
  const members = (row.members || []).map(item => esc(item.name)).join(" • ");
  return `<tr class="campaign-row campaign-group-row${rowStateClass(row)}${row.warnings?.length ? " has-warning" : ""}${row.category_break ? " campaign-cat-break" : ""}" data-vehicle-category="${esc(row.vehicle_category || "")}">
    <td class="name"><div class="campaign-service-name"><strong>${esc(row.name)}</strong><span class="chip muted-chip">مجموعة ${(row.members || []).length}</span>${warningChips(row)}</div><div class="sub campaign-group-members">${members}</div></td>
    <td class="campaign-driver-cell">${driverOptions(row)}</td>
    <td dir="ltr">${vehicleOptions(row)}</td>
    <td><div class="campaign-vehicle-type">${vehicleTypeOptions(row)}${row.vehicle ? `<div class="sub">${esc(row.vehicle.model || "")}</div>` : ""}</div></td>
    <td class="col-actions"><div class="row-actions"><button type="button" class="mini" data-action="renameCampaignGroup" data-id="${esc(row.id)}">${icon("edit")} تسمية</button><button type="button" class="mini danger" data-action="ungroupCampaign" data-id="${esc(row.id)}">فك التجميع</button></div></td>
  </tr>`;
}

function postDriver(row) {
  const title = row.driver_text ? ` title="${esc(row.driver_text)}"` : "";
  return `<input class="campaign-post-driver${row.driver_text ? "" : " is-empty"}" data-post-driver="${esc(row.id)}" value="${esc(row.driver_text || "")}" maxlength="200"${title} aria-label="السائق في ${esc(row.name)}">`;
}

function postRow(row) {
  const plate = row.vehicle?.label || row.vehicle?.plate || row.plate_text || "—";
  const type = row.type_text || row.vehicle?.type || "—";
  return `<tr class="campaign-row${rowStateClass(row)}${row.warnings?.length ? " has-warning" : ""}">
    <td>${esc(row.number || "")}</td><td class="name"><strong>${esc(row.name)}</strong>${warningChips(row)}</td>
    <td class="campaign-driver-cell">${postDriver(row)}</td><td dir="ltr"><div class="campaign-vehicle-cell">${vehicleOptions(row)}${!row.vehicle && row.plate_text ? `<span class="muted-text" dir="ltr">${esc(plate)}</span>` : ""}</div></td>
    <td><div class="campaign-vehicle-type">${vehicleTypeOptions(row)}${!row.vehicle && row.type_text ? `<span class="muted-text">${esc(type)}</span>` : ""}</div></td>
    <td class="col-actions"><div class="row-actions"><button class="mini" type="button" data-action="editCampaignPost" data-id="${esc(row.id)}">تعديل</button>${rowMenu([{action: "removeCampaignPost", id: row.id, extra: {name: row.name}, label: "إزالة", danger: true}])}</div></td>
  </tr>`;
}

function postCard() {
  const rows = CAMPAIGN.posts || [];
  const action = `<button type="button" class="mini on-dark" data-action="openCampaignPost">${icon("plus")} إضافة</button>`;
  const body = rows.length ? `<div class="mtable-wrap">${mtable(["الرقم", "الارتكاز", "السائق", "رقم المركبة", "نوع المركبة", "الإجراء"], rows.map(postRow))}</div>` : emptyState({compact: true, title: "لا توجد ارتكازات اليوم"});
  return `<div class="mcard campaign-table-card campaign-posts-card"><h3>مركبات الارتكازات<span class="mcount">${rows.length}</span>${summaryChip("posts")}${action}</h3>${body}</div>`;
}

function serverPlatesText() {
  return (CAMPAIGN.plates?.rows || []).map(row => row.join(" ")).join("\n");
}

function platesText() {
  return CAMPAIGN_PLATES_DRAFT?.day === DAY ? CAMPAIGN_PLATES_DRAFT.value : serverPlatesText();
}

function updatePlatesDraft(value) {
  CAMPAIGN_PLATES_DRAFT = {day: DAY, value, dirty: value !== serverPlatesText()};
  const indicator = $("#campaignPlatesUnsaved");
  if (indicator) indicator.hidden = !CAMPAIGN_PLATES_DRAFT.dirty;
}

function platesCard() {
  const dirty = CAMPAIGN_PLATES_DRAFT?.day === DAY && CAMPAIGN_PLATES_DRAFT.dirty;
  return `<div class="mcard campaign-plates-card"><h3>سجل اللوحات${CAMPAIGN.plates?.inherited ? `<span class="chip muted-chip campaign-inherited">من اليوم السابق</span>` : ""}<span class="chip campaign-plates-unsaved" id="campaignPlatesUnsaved"${dirty ? "" : " hidden"}>تعديلات غير محفوظة</span></h3><textarea id="campaignPlates" class="campaign-plates" dir="ltr" rows="4" placeholder="ب13/9416 ب13/9417">${esc(platesText())}</textarea><div class="actions"><button type="button" class="primary" id="saveCampaignPlates">حفظ</button></div></div>`;
}

function summaryChip(section) {
  const summary = CAMPAIGN.summary?.sections?.[section] || {};
  return summary.missing
    ? `<span class="campaign-missing-chip">ناقص ${summary.missing}</span>`
    : `<span class="campaign-complete-chip">مكتمل</span>`;
}

function tableCard(title, rows, empty, options = {}) {
  const action = options.add ? `<button type="button" class="mini on-dark" data-action="openCampaignDaily">${icon("plus")} إضافة</button>` : "";
  const groupBtn = options.group ? `<button type="button" class="mini on-dark" id="campaignGroupBtn" data-action="openCampaignGroup"${GROUP_SELECTION.size >= 2 ? "" : " disabled"}>تجميع خدمات${GROUP_SELECTION.size ? ` (${GROUP_SELECTION.size})` : ""}</button>` : "";
  const body = rows.length ? `<div class="mtable-wrap">${mtable(["الخدمة", "السائق", "رقم المركبة", "نوع المركبة", "الإجراء"], rows.map(row => campaignRow(row, options.attach)))}</div>` : emptyState({compact: true, title: empty});
  return `<div class="mcard campaign-table-card campaign-${esc(options.section)}-card"><h3>${esc(title)}<span class="mcount">${rows.length}</span>${summaryChip(options.section)}${groupBtn}${action}</h3>${body}</div>`;
}

function renderWarnings() {
  if (!CAMPAIGN.warnings?.length) return "";
  return `<div class="alert-card campaign-alert"><div class="alert-head"><span class="alert-ico">${icon("alert")}</span><strong>تنبيهات المراجعة</strong></div><ul class="alert-list">${CAMPAIGN.warnings.map(item => `<li><b>${esc(item.row)}</b> — ${esc(item.text)}</li>`).join("")}</ul></div>`;
}

function renderSaveError() {
  if (!CAMPAIGN_SAVE_ERROR) return "";
  return `<div class="data-region-error campaign-save-error" role="alert">${icon("alert")}<div><strong>لم يُحفظ آخر تعديل</strong><span>${esc(CAMPAIGN_SAVE_ERROR)}</span></div></div>`;
}

function render() {
  const wrap = $("#campaignWrap");
  if (!CAMPAIGN) { wrap.innerHTML = skeleton("cards", 3); return; }
  const selectable = new Set(campaignServices().filter(row => row.kind === "service" && !(
    !(row.service_vehicles || []).some(item => item.source === "direct") &&
    (row.service_vehicles || []).some(item => item.source === "lorry")
  )).map(row => row.id));
  [...GROUP_SELECTION].forEach(id => { if (!selectable.has(id)) GROUP_SELECTION.delete(id); });
  const summary = CAMPAIGN.summary?.overall || {missing: 0, total: 0};
  const summaryText = summary.missing
    ? `<b>ناقص ${summary.missing} من ${summary.total} صف مطلوب</b>`
    : (summary.total ? "كل الصفوف المطلوبة متسكنة" : "لا توجد صفوف مطلوبة للتسكين");
  wrap.innerHTML = `${renderSaveError()}<p class="vacancy-summary ${summary.missing ? "warn" : "ok"}"><span class="status-dot ${summary.missing ? "warn" : "ok"}" aria-hidden="true"></span>${summaryText}</p>${renderWarnings()}<div class="ledger-board"><div class="ledger-head"><h2>يومية الحملة</h2><div class="ledger-sub">${dayName(CAMPAIGN.date)} الموافق ${fmt(CAMPAIGN.date)}</div></div>${postCard()}${tableCard("اللواري الأساسية", CAMPAIGN.lorries || [], "", {attach: true, section: "lorries"})}${tableCard("الخدمات الطارئة", campaignServices(), "لا توجد خدمات طارئة اليوم", {group: true, section: "services"})}${tableCard("الأقوال اليومية", CAMPAIGN.daily || [], "لا توجد أقوال يومية اليوم", {add: true, section: "daily"})}${tableCard("لواري التعيينات", CAMPAIGN.appointments || [], "", {attach: true, section: "appointments"})}${platesCard()}</div>`;
  upgradeSelects(wrap);
  wrap.querySelectorAll("select[data-driver-row]").forEach(select => {
    if (select.dataset.customValue) select.value = select.dataset.customValue;
    if (select.dataset.fullValue) select._comboInput?.setAttribute("title", select.dataset.fullValue);
    const initial = rowBy(select.dataset.driverRow)?.driver;
    let savedValue = initial?.kind === "text" ? initial.name : (initial?.kind ? `${initial.kind}|${initial.id}` : "");
    let draftEdited = false, explicitChange = false;
    const saveDriver = value => {
      const driver = !value ? "" : value.includes("|")
        ? (() => { const [kind, id] = value.split("|"); return {kind, id}; })()
        : {kind: "text", name: value};
      saveRow(rowBy(select.dataset.driverRow), {driver});
    };
    select.addEventListener("input", () => { draftEdited = true; explicitChange = false; });
    select.addEventListener("change", () => {
      explicitChange = true;
      draftEdited = false;
      const value = select.value.trim();
      if (value === savedValue) return;
      savedValue = value;
      saveDriver(value);
    });
    select._comboInput?.addEventListener("blur", () => setTimeout(() => {
      if (!select.isConnected) return;
      if (explicitChange) { explicitChange = false; return; }
      if (!draftEdited) return;
      draftEdited = false;
      const draft = select.value.trim();
      if (!draft) { select.value = savedValue; return; }
      const unfinishedSearch = [...select.options].some(option => arIncludes(option.textContent, draft));
      if (savedValue || unfinishedSearch) {
        select.value = savedValue;
        showToast("لم يتغيّر السائق. اختر من القائمة أو اضغط Enter لحفظ النص.", true);
        return;
      }
      savedValue = draft;
      saveDriver(draft);
    }, 0));
  });
  wrap.querySelectorAll("select[data-vehicle-row]").forEach(select => {
    select._comboInput?.setAttribute("dir", "ltr");
    select.addEventListener("change", () => {
      const row = rowBy(select.dataset.vehicleRow);
      const vehicle = (CAMPAIGN.pickers?.vehicles || []).find(item => item.id === select.value);
      if (vehicle) CAMPAIGN_TYPE_FILTERS.set(row.id, vehicle.type);
      saveRow(row, {vehicle_id: select.value});
    });
  });
  wrap.querySelectorAll("select[data-type-row]").forEach(select => {
    select.addEventListener("change", () => {
      CAMPAIGN_TYPE_FILTERS.set(select.dataset.typeRow, select.value);
      render();
    });
  });
  wrap.querySelectorAll("input[data-post-driver]").forEach(input => {
    const original = rowBy(input.dataset.postDriver)?.driver_text || "";
    input.addEventListener("input", () => {
      input.classList.toggle("is-empty", !input.value.trim());
      input.title = input.value.trim();
    });
    input.addEventListener("blur", () => {
      const value = input.value.trim();
      if (value !== original) saveRow(rowBy(input.dataset.postDriver), {driver_text: value});
    });
  });
  wrap.querySelectorAll("input[data-group-pick]").forEach(input => input.onchange = () => {
    input.checked ? GROUP_SELECTION.add(input.dataset.groupPick) : GROUP_SELECTION.delete(input.dataset.groupPick);
    const button = $("#campaignGroupBtn");
    if (button) { button.disabled = GROUP_SELECTION.size < 2; button.textContent = `تجميع خدمات${GROUP_SELECTION.size ? ` (${GROUP_SELECTION.size})` : ""}`; }
  });
  wrap.querySelectorAll("button[data-action='openCampaignServiceVehicles']").forEach(button => {
    button.onclick = () => openServiceVehicles(rowBy(button.dataset.id));
  });
  const platesInput = $("#campaignPlates");
  platesInput.addEventListener("input", () => updatePlatesDraft(platesInput.value));
  $("#saveCampaignPlates").onclick = async () => {
    const savedText = platesInput.value;
    const lines = savedText.split(/\n/).map(line => line.split(/[ ,،]+/).map(v => v.trim()).filter(Boolean)).filter(row => row.length);
    const out = await campaignWrite(`/api/campaign/${DAY}/plates`, "PUT", {rows: lines});
    if (out) {
      if (CAMPAIGN_PLATES_DRAFT?.day === DAY && CAMPAIGN_PLATES_DRAFT.value === savedText) CAMPAIGN_PLATES_DRAFT = null;
      render(); showToast("تم حفظ سجل اللوحات");
    }
  };
}

function serviceVehicleEditor(row) {
  const options = (CAMPAIGN.pickers?.vehicles || []).map(vehicle =>
    `<option value="${esc(vehicle.id)}">${esc(vehicle.label)}${vehicle.status === "disabled" ? " (معطلة)" : ""}</option>`).join("");
  const people = row.people || [];
  return (row.vehicles || []).map((item, index) => `<div class="campaign-service-vehicle" data-service-vehicle-index="${index}">
    <div class="campaign-service-vehicle-head"><label>المركبة <select data-service-vehicle="${index}" aria-label="مركبة الخدمة ${index + 1}"><option value="">اختر مركبة</option>${options}</select></label><button type="button" class="mini danger" data-remove-service-vehicle="${index}">إزالة</button></div>
    <fieldset><legend>أفراد الخدمة في المركبة</legend><div class="campaign-service-people">${people.length ? people.map(person => {
      const key = person.category === "officers" ? "officer_ids" : "personnel_ids";
      const checked = (item[key] || []).includes(person.id);
      return `<label class="check-label"><input type="checkbox" data-service-person="${index}" data-person-key="${key}" value="${esc(person.id)}"${checked ? " checked" : ""}>${esc(person.role ? `${person.role}/ ${person.name}` : person.name)}</label>`;
    }).join("") : "<span class='muted-text'>لا يوجد أفراد أو ضباط مسجلون على التكليف.</span>"}</div></fieldset>
  </div>`).join("");
}

function openServiceVehicles(row) {
  const state = {row, vehicles: (row.vehicles || []).map(item => ({...item, vehicle: undefined}))};
  const modal = $("#campaignServiceVehiclesModal");
  const renderEditor = () => {
    modal.querySelector("[data-service-vehicles-body]").innerHTML = serviceVehicleEditor({...row, vehicles: state.vehicles});
    modal.querySelectorAll("select[data-service-vehicle]").forEach(select => {
      const item = state.vehicles[Number(select.dataset.serviceVehicle)];
      select.value = item.vehicle_id || "";
    });
    upgradeSelects(modal);
    modal.querySelectorAll("select[data-service-vehicle]").forEach(select => select.onchange = () => {
      state.vehicles[Number(select.dataset.serviceVehicle)].vehicle_id = select.value;
    });
    modal.querySelectorAll("input[data-service-person]").forEach(input => input.onchange = () => {
      const item = state.vehicles[Number(input.dataset.servicePerson)];
      const key = input.dataset.personKey;
      const ids = new Set(item[key] || []);
      input.checked ? ids.add(input.value) : ids.delete(input.value);
      item[key] = [...ids];
    });
    modal.querySelectorAll("button[data-remove-service-vehicle]").forEach(button => button.onclick = async () => {
      if (!(await confirmDialog({title: "إزالة المركبة", body: "ستُزال هذه المركبة وتوزيع أفرادها من الخدمة.", confirmLabel: "إزالة", danger: true}))) return;
      state.vehicles.splice(Number(button.dataset.removeServiceVehicle), 1); renderEditor();
    });
  };
  modal.querySelector("[data-service-vehicles-title]").textContent = `مركبات «${row.name}» وأفرادها`;
  modal.querySelector("[data-add-service-vehicle]").onclick = () => { state.vehicles.push({vehicle_id: "", personnel_ids: [], officer_ids: []}); renderEditor(); };
  modal.querySelector("[data-save-service-vehicles]").onclick = async () => {
    const vehicles = state.vehicles.map(item => ({vehicle_id: item.vehicle_id, personnel_ids: item.personnel_ids || [], officer_ids: item.officer_ids || []}));
    const out = await campaignWrite(`/api/campaign/${DAY}/service/${encodeURIComponent(row.id)}`, "PUT", {vehicles});
    if (out) { closeModal("campaignServiceVehiclesModal", true); render(); showToast("تم حفظ مركبات الخدمة"); }
  };
  renderEditor(); openModal("campaignServiceVehiclesModal");
}

async function loadDay(day) {
  const out = await api(`/api/campaign/${day}`);
  if (!out) { UI.regionError("#campaignWrap", {message:"تعذر تحميل يومية الحملة.", retry:()=>loadDay(day)}); return; }
  UI.regionReady("#campaignWrap");
  const changingDay = DAY !== null && DAY !== day;
  if (changingDay) {
    CAMPAIGN_TYPE_FILTERS.clear();
    GROUP_SELECTION.clear();
    CAMPAIGN_PLATES_DRAFT = null;
    CAMPAIGN_SAVE_ERROR = "";
  }
  CAMPAIGN = out; DAY = day; $("#dutyDate").value = day; setPageDay(day); render(); loadDayStatus();
}

async function loadDayStatus() {
  const status = await api(`/api/day-status/${DAY}`);
  if (!status) return;
  $("#dayLockBadge").innerHTML = status.closed ? `<span class="chip err">${icon("lock")} مغلق${status.auto ? " (تلقائي)" : ""}</span>` : status.stage === "not_open" ? `<span class="chip w">${icon("clock")} لم يُفتح بعد</span>` : `<span class="chip on"><span class="status-dot ok"></span> مفتوح</span>`;
}

function openAttach(lorryId) {
  // الخدمة المُلحقة بأي لوري تختفي من الاختيارات — مش بس اللوري الحالي
  const attached = new Set([...(CAMPAIGN.lorries || []), ...(CAMPAIGN.appointments || [])].flatMap(lorry => lorry.attached || [])
    .map(item => item.assignment_id).filter(Boolean));
  const choices = (CAMPAIGN.pickers?.attachable || []).filter(item => !attached.has(item.assignment_id));
  $("#campaignAttachLorry").value = lorryId;
  $("#campaignAttachSelect").innerHTML = `<option value="">اختر خدمة أو اكتب اسمًا</option>${choices.map(item => `<option value="${esc(item.assignment_id)}">${esc(item.name)}</option>`).join("")}`;
  $("#campaignAttachSelect").value = "";
  openModal("campaignAttachModal");
}

function openGroupModal(group = null) {
  $("#campaignGroupId").value = group?.id || "";
  $("#campaignGroupName").value = group?.name || "";
  $("#campaignGroupTitle").textContent = group ? "تسمية المجموعة" : "تجميع خدمات";
  $("#campaignGroupSubmit").textContent = group ? "حفظ" : "تجميع";
  const names = group ? [] : [...GROUP_SELECTION].map(id => rowBy(id)?.base_name || rowBy(id)?.name).filter(Boolean);
  $("#campaignGroupMembers").textContent = names.length ? `الخدمات: ${names.join(" • ")}` : "";
  openModal("campaignGroupModal");
}

ACTIONS.openCampaignGroup = () => { if (GROUP_SELECTION.size >= 2) openGroupModal(); };
ACTIONS.renameCampaignGroup = id => openGroupModal(rowBy(id));
ACTIONS.ungroupCampaign = async id => {
  const row = rowBy(id);
  if (!(await confirmDialog({title: "فك التجميع", body: `ستعود خدمات «${row.name}» صفوفًا مستقلة ببياناتها السابقة.`, confirmLabel: "فك التجميع", danger: true}))) return;
  const out = await campaignWrite(`/api/campaign/${DAY}/groups/${encodeURIComponent(id)}`, "DELETE");
  if (out) { render(); showToast("تم فك التجميع"); }
};

$("#campaignGroupForm").onsubmit = async event => {
  event.preventDefault();
  const id = $("#campaignGroupId").value, title = $("#campaignGroupName").value.trim();
  if (!title) { showToast("اكتب عنوان المجموعة", true); return; }
  const out = id
    ? await campaignWrite(`/api/campaign/${DAY}/groups/${encodeURIComponent(id)}`, "PATCH", {title})
    : await campaignWrite(`/api/campaign/${DAY}/groups`, "POST", {title, members: [...GROUP_SELECTION]});
  if (!out) return;
  if (!id) GROUP_SELECTION.clear();
  closeModal("campaignGroupModal", true); render(); showToast(id ? "تم حفظ العنوان" : "تم تجميع الخدمات");
};

ACTIONS.openCampaignAttach = id => openAttach(id);
ACTIONS.detachCampaignService = async (id, extra) => {
  const row = rowBy(id);
  const out = await campaignWrite(`/api/campaign/${DAY}/lorry/${encodeURIComponent(row.id)}/service`, "DELETE", extra);
  if (out) { render(); showToast("تمت إزالة الخدمة"); }
};
ACTIONS.openCampaignDaily = () => { $("#campaignDailyName").value = ""; $("#campaignDailyBasic").innerHTML = `<option value="">بدون ربط</option>${(CAMPAIGN.pickers?.basic_services || []).map(item => `<option value="${esc(item.id)}">${esc(item.name)}</option>`).join("")}`; openModal("campaignDailyModal"); };
function openPostModal(row = null) {
  $("#campaignPostId").value = row?.id || "";
  $("#campaignPostName").value = row?.name || "";
  $("#campaignPostNumber").value = row?.number || "";
  $("#campaignPostDriver").value = "";
  $("#campaignPostDriverField").hidden = !!row;
  $("#campaignPostTitle").textContent = row ? "تعديل الارتكاز" : "إضافة ارتكاز";
  $("#campaignPostSubmit").textContent = row ? "حفظ التعديل" : "إضافة";
  openModal("campaignPostModal");
}

ACTIONS.openCampaignPost = () => openPostModal();
ACTIONS.editCampaignPost = id => openPostModal(rowBy(id));
ACTIONS.removeCampaignPost = async (id, extra) => {
  if (!(await confirmDialog({title: "إزالة الارتكاز", body: "سيُزال ابتداءً من اليوم، وتبقى الأيام السابقة دون تغيير.", confirmLabel: "إزالة", danger: true}))) return;
  const out = await campaignWrite(`/api/campaign/${DAY}/posts/${encodeURIComponent(id)}`, "DELETE");
  if (out) { render(); showToast("تمت إزالة الارتكاز"); }
};
ACTIONS.removeCampaignDaily = async (id, extra) => {
  if (!(await confirmDialog({title: "إزالة القول اليومي", body: `ستُزال «${extra.name}» ابتداءً من اليوم، وتبقى الأيام السابقة دون تغيير.`, confirmLabel: "إزالة", danger: true}))) return;
  const out = await campaignWrite(`/api/campaign/${DAY}/daily-rows/${encodeURIComponent(id)}`, "DELETE");
  if (out) { render(); showToast("تمت إزالة القول"); }
};

$("#campaignAttachForm").onsubmit = async event => {
  event.preventDefault();
  const select = $("#campaignAttachSelect"), value = select.value.trim();
  if (!value) { showToast("حدد خدمة أو اكتب اسمًا", true); return; }
  const known = (CAMPAIGN.pickers?.attachable || []).find(item => item.assignment_id === value);
  const body = known ? {assignment_id: value} : {name: value};
  const out = await campaignWrite(`/api/campaign/${DAY}/lorry/${encodeURIComponent($("#campaignAttachLorry").value)}/service`, "POST", body);
  if (out) { closeModal("campaignAttachModal", true); render(); showToast("تمت إضافة الخدمة"); }
};

$("#campaignDailyForm").onsubmit = async event => {
  event.preventDefault();
  const name = $("#campaignDailyName").value.trim();
  const basic_entry_id = $("#campaignDailyBasic").value;
  if (!name) return;
  const out = await campaignWrite(`/api/campaign/${DAY}/daily-rows`, "POST", {name, basic_entry_id});
  if (out) { closeModal("campaignDailyModal", true); render(); showToast("تمت إضافة القول"); }
};

$("#campaignPostForm").onsubmit = async event => {
  event.preventDefault();
  const id = $("#campaignPostId").value;
  const body = {name: $("#campaignPostName").value.trim(), number: $("#campaignPostNumber").value.trim()};
  if (!id) body.driver_text = $("#campaignPostDriver").value.trim();
  if (!body.name) return;
  const url = id ? `/api/campaign/${DAY}/posts/${encodeURIComponent(id)}` : `/api/campaign/${DAY}/posts`;
  const out = await campaignWrite(url, id ? "PATCH" : "POST", body);
  if (out) { closeModal("campaignPostModal", true); render(); showToast(id ? "تم تعديل الارتكاز من اليوم" : "تمت إضافة الارتكاز"); }
};

async function navigateDay(day) {
  if (!day || day === DAY) { $("#dutyDate").value = DAY || day; return; }
  await CAMPAIGN_WRITE_QUEUE;
  if (CAMPAIGN_PLATES_DRAFT?.day === DAY && CAMPAIGN_PLATES_DRAFT.dirty) {
    const discard = await confirmDialog({
      title: "سجل اللوحات غير محفوظ",
      body: "توجد تعديلات غير محفوظة في سجل اللوحات. هل تريد تجاهلها والانتقال إلى يوم آخر؟",
      confirmLabel: "تجاهل والانتقال",
      danger: true,
    });
    if (!discard) { $("#dutyDate").value = DAY; return; }
    CAMPAIGN_PLATES_DRAFT = null;
  }
  await loadDay(day);
}

$("#dayPrev").onclick = () => navigateDay(addDays($("#dutyDate").value || curDate(), -1));
$("#dayNext").onclick = () => navigateDay(addDays($("#dutyDate").value || curDate(), 1));
$("#dayToday").onclick = () => navigateDay(curDate());
$("#dutyDate").onchange = () => navigateDay($("#dutyDate").value);
document.addEventListener("keydown", event => {
  if (!["PageUp", "PageDown"].includes(event.key) || document.querySelector(".modal:not(.hidden), .combo-pop:not(.hidden)")) return;
  if (["INPUT", "SELECT", "TEXTAREA", "BUTTON", "A"].includes(event.target.tagName) || event.target.isContentEditable) return;
  event.preventDefault(); navigateDay(addDays($("#dutyDate").value || curDate(), event.key === "PageUp" ? -1 : 1));
});

(async () => { if (await bootstrap()) loadDay(workDay()); else UI.regionError("#campaignWrap", {message:"تعذر تهيئة يومية الحملة.", retry:()=>location.reload()}); })();
