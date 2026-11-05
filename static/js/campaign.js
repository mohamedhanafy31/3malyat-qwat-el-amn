/* يومية الحملة — تسكين سريع للسائق والمركبة مع حفظ تلقائي متسلسل. */
let CAMPAIGN = null, DAY = null;
const CAMPAIGN_TYPE_FILTERS = new Map();
const GROUP_SELECTION = new Set();
const CAMPAIGN_FILTER_PINNED = new Set();
let CAMPAIGN_WRITE_QUEUE = Promise.resolve();
let CAMPAIGN_SAVE_ERROR = "";
let CAMPAIGN_SAVE_PENDING = 0;
let CAMPAIGN_PLATES_DRAFT = null;
let CAMPAIGN_PLATES_TIMER = null;
let CAMPAIGN_PLATES_SAVE = null;
let CAMPAIGN_DELIVERY_ORDER = [];
let CAMPAIGN_DELIVERY_BANDS = new Map();
let CAMPAIGN_MISSING_ONLY = false;
let CAMPAIGN_UNDO = null;

window.dailyFileDay = () => DAY;
window.exportDocxUrl = () => `/api/campaign/${DAY}/export.docx`;

const campaignServices = (payload = CAMPAIGN) => payload?.service_rows || payload?.services || [];
const orderedCampaignRows = (payload = CAMPAIGN) => payload?.delivery_rows || [
  ...(payload?.lorries || []), ...(payload?.appointments || []),
  ...campaignServices(payload), ...(payload?.daily || []),
];
const rowSets = (payload = CAMPAIGN) => [...orderedCampaignRows(payload), ...(payload?.posts || [])];
const rowBy = id => rowSets().find(row => row.id === id);
const rowKey = row => `${row.kind}:${row.id}`;
const rowByKey = (key, payload = CAMPAIGN) => rowSets(payload).find(row => rowKey(row) === key);
const controlKey = (row, field) => `${rowKey(row)}:${field}`;

function setSaveState(state, detail = "") {
  const el = $("#campaignSaveStatus");
  if (!el) return;
  const labels = {saving: "جارٍ الحفظ…", saved: "تم الحفظ", failed: "تعذر الحفظ"};
  el.textContent = labels[state] || labels.saved;
  el.className = `campaign-save-status is-${state}`;
  el.title = detail;
}

function updateUndoControl() {
  const button = $("#campaignUndo");
  if (!button) return;
  button.hidden = !CAMPAIGN_UNDO;
  button.disabled = CAMPAIGN_SAVE_PENDING > 0;
}

function rememberUndo(change) {
  CAMPAIGN_UNDO = change;
  updateUndoControl();
}

function clearUndo() {
  CAMPAIGN_UNDO = null;
  updateUndoControl();
}

function stabilizeCampaignOrder(payload, fresh = false) {
  const rows = orderedCampaignRows(payload);
  if (fresh) {
    CAMPAIGN_DELIVERY_ORDER = rows.map(row => rowKey(row));
    CAMPAIGN_DELIVERY_BANDS = new Map(rows.map(row => [rowKey(row), {
      band: row.band || "", label: row.band_label || "",
    }]));
  }
  const known = new Set(CAMPAIGN_DELIVERY_ORDER);
  rows.forEach(row => {
    const key = rowKey(row);
    if (known.has(key)) return;
    CAMPAIGN_DELIVERY_ORDER.push(key);
    CAMPAIGN_DELIVERY_BANDS.set(key, {band: row.band || "", label: row.band_label || ""});
  });
  const positions = new Map(CAMPAIGN_DELIVERY_ORDER.map((key, index) => [key, index]));
  payload.delivery_rows = [...rows].sort((a, b) =>
    (positions.get(rowKey(a)) ?? Number.MAX_SAFE_INTEGER) -
    (positions.get(rowKey(b)) ?? Number.MAX_SAFE_INTEGER));
  payload.delivery_rows.forEach(row => {
    const fixed = CAMPAIGN_DELIVERY_BANDS.get(rowKey(row));
    if (!fixed) return;
    row.band = fixed.band;
    row.band_label = fixed.label;
  });
}

async function refreshTruth(writeDay, quietKey = "") {
  const truth = await api(`/api/campaign/${writeDay}`, {noLoader: true});
  if (!truth || DAY !== writeDay) return;
  stabilizeCampaignOrder(truth);
  const previous = CAMPAIGN;
  CAMPAIGN = truth;
  patchCampaign(previous, {quietKey});
}

async function campaignWrite(url, method, body = {}, options = {}) {
  const writeDay = DAY;
  CAMPAIGN_SAVE_PENDING += 1;
  setSaveState("saving");
  updateUndoControl();
  const run = async () => {
    let errorText = "";
    const out = await api(url, {
      ...jsonReq(method, {...body, revision: CAMPAIGN?.revision}),
      noLoader: !!options.noLoader,
      onError(payload) { errorText = payload?.error || ""; return true; },
    });
    if (!out) {
      CAMPAIGN_SAVE_ERROR = errorText || "لم يُحفظ التعديل. بقيت القيمة المكتوبة ظاهرة، وأُعيدت قراءة الحقيقة من الخادم.";
      if (DAY === writeDay) await refreshTruth(writeDay, options.quietKey);
      return null;
    }
    CAMPAIGN_SAVE_ERROR = "";
    if (DAY === writeDay) {
      stabilizeCampaignOrder(out, !!options.structural);
      const previous = CAMPAIGN;
      CAMPAIGN = out;
      if (options.structural) render({preserveFocus: true});
      else patchCampaign(previous, {quietKey: options.quietKey});
    }
    return out;
  };
  const result = CAMPAIGN_WRITE_QUEUE.then(run, run);
  CAMPAIGN_WRITE_QUEUE = result.then(() => undefined, () => undefined);
  result.finally(() => {
    CAMPAIGN_SAVE_PENDING = Math.max(0, CAMPAIGN_SAVE_PENDING - 1);
    if (!CAMPAIGN_SAVE_PENDING) setSaveState(CAMPAIGN_SAVE_ERROR ? "failed" : "saved", CAMPAIGN_SAVE_ERROR);
    updateUndoControl();
  });
  return result;
}

function driverPayload(driver) {
  if (!driver) return "";
  return driver.kind === "text" ? {kind: "text", name: driver.name} : {kind: driver.kind, id: driver.id};
}

function driverValuePayload(value) {
  if (!value) return "";
  if (!value.includes("|")) return {kind: "text", name: value};
  const [kind, id] = value.split("|");
  return {kind, id};
}

async function saveRow(row, body, options = {}) {
  if (!row) return null;
  const url = `/api/campaign/${DAY}/${row.kind}/${encodeURIComponent(row.id)}`;
  const out = await campaignWrite(url, "PUT", body, {
    quietKey: options.sourceKey, noLoader: true,
  });
  if (out && options.undoBody !== undefined) {
    rememberUndo({url, method: "PUT", body: options.undoBody, label: options.undoLabel || "آخر تعديل"});
  }
  return out;
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
  return `<select class="campaign-inline-select campaign-driver-select${quiet}" data-driver-row="${esc(row.id)}" data-control-key="${esc(controlKey(row, "driver"))}" data-required-field="driver" data-combo-custom data-combo-custom-option="none" data-maxlength="200"${custom}${full} aria-label="السائق في ${esc(row.name)}">
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
  return `<select class="campaign-inline-select" data-vehicle-row="${esc(row.id)}" data-control-key="${esc(controlKey(row, "vehicle"))}" data-required-field="vehicle" aria-label="رقم المركبة في ${esc(row.name)}">
    <option value="">اختر مركبة</option>${noMatches ? `<option disabled>لا توجد مركبات من هذا النوع</option>` : ""}${choices.map(vehicle => `<option value="${esc(vehicle.id)}"${vehicle.id === selected ? " selected" : ""}${vehicle.status === "disabled" ? " data-disabled=" + JSON.stringify(true) : ""}>${esc(vehicle.label)}${vehicle.status === "disabled" ? " (معطلة)" : ""}</option>`).join("")}</select>`;
}

function vehicleTypeOptions(row) {
  const selected = CAMPAIGN_TYPE_FILTERS.get(row.id) ?? row.vehicle?.type ?? "";
  return `<select class="campaign-inline-select" data-type-row="${esc(row.id)}" data-control-key="${esc(controlKey(row, "type"))}" aria-label="نوع المركبة في ${esc(row.name)}">
    <option value="">اختر النوع</option>${(CAMPAIGN.pickers?.types || []).map(type => `<option value="${esc(type)}"${type === selected ? " selected" : ""}>${esc(type)}</option>`).join("")}</select>`;
}

function inheritedBadge(value) {
  const sources = value?.inherited_from || {};
  const days = [...new Set(Object.values(sources).filter(Boolean))].sort();
  if (!days.length) return "";
  const previous = addDays(DAY, -1);
  const label = days.length === 1 && days[0] === previous
    ? "من اليوم السابق"
    : days.length === 1 ? `من يوم ${fmtShort(days[0])}` : `من أيام ${days.map(fmtShort).join("، ")}`;
  const names = {driver: "السائق", vehicle: "المركبة", plate: "اللوحة", type: "النوع", plates: "سجل اللوحات"};
  const detail = Object.entries(sources).map(([field, day]) => `${names[field] || field}: ${fmtShort(day)}`).join("، ");
  return `<span class="chip muted-chip campaign-inherited" title="${esc(detail)}">${esc(label)}</span>`;
}

function warningChips(row) {
  const warnings = row.warnings || [];
  const inherited = inheritedBadge(row);
  const warningText = warnings.length
    ? `<span class="campaign-row-warnings">${icon("alert")} ${esc(warnings.join(" — "))}</span>` : "";
  return `${statusPill(row)}${inherited}${warningText}`;
}

function serviceCell(row, allowAttach) {
  const chips = (row.attached || []).map(item => `<span class="chip campaign-attach-chip">${esc(item.name)}<button type="button" data-action="detachCampaignService" data-id="${esc(row.id)}" data-extra="${dataAttr(item)}" aria-label="إزالة ${esc(item.name)}">×</button></span>`).join("");
  const add = allowAttach ? `<button type="button" class="mini btn-xs campaign-add-service" data-action="openCampaignAttach" data-id="${esc(row.id)}">${icon("plus")} إضافة خدمة</button>` : "";
  return `<div class="campaign-service-name"><strong>${esc(row.base_name || row.name)}</strong>${chips}${add}${warningChips(row)}</div>`;
}

function campaignRow(row, allowAttach, section) {
  if (row.kind === "group") return groupCampaignRow(row);
  if (row.kind === "service") return serviceCampaignRow(row);
  return `<tr class="campaign-row${rowStateClass(row)}${row.warnings?.length ? " has-warning" : ""}" data-row-key="${esc(rowKey(row))}" data-section="${esc(section)}" data-row-band="${esc(row.band || "")}" data-row-state="${esc(row.status)}">
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
  const action = `<button type="button" class="mini btn-xs campaign-service-secondary" data-action="openCampaignServiceVehicles" data-id="${esc(row.id)}">${icon("edit")} مركبات وأفراد</button>`;
  let cells;
  if (carriedOnly) {
    const lorryDriver = driverDisplay(carrier.driver) || "اللوري بدون سائق";
    cells = `<td class="campaign-driver-cell"><span class="campaign-carried-driver" title="${esc(lorryDriver)}">${esc(lorryDriver)}</span></td><td colspan="2"><div class="campaign-service-assignment">${details}</div></td><td class="col-actions">${action}</td>`;
  } else if (directVehicles.length >= 2) {
    cells = `<td colspan="3"><div class="campaign-service-assignment">${details}</div></td><td class="col-actions">${action}</td>`;
  } else {
    cells = `<td class="campaign-driver-cell">${driverOptions(row)}</td><td dir="ltr">${vehicleOptions(row)}</td><td><div class="campaign-vehicle-type">${vehicleTypeOptions(row)}${row.vehicle ? `<div class="sub">${esc(row.vehicle.model || "")}</div>` : ""}</div></td><td class="col-actions">${action}</td>`;
  }
  return `<tr class="campaign-row${rowStateClass(row)}${row.warnings?.length ? " has-warning" : ""}" data-row-key="${esc(rowKey(row))}" data-section="routes" data-row-band="${esc(row.band || "")}" data-row-state="${esc(row.status)}">
    <td class="name"><div class="campaign-service-name">${groupPick}<strong>${esc(row.base_name || row.name)}</strong>${(row.attached || []).map(item => `<span class="chip campaign-attach-chip">${esc(item.name)}</span>`).join("")}${warningChips(row)}</div></td>
    ${cells}
  </tr>`;
}

function groupCampaignRow(row) {
  const members = (row.members || []).map(item => esc(item.name)).join(" • ");
  return `<tr class="campaign-row campaign-group-row${rowStateClass(row)}${row.warnings?.length ? " has-warning" : ""}" data-row-key="${esc(rowKey(row))}" data-section="routes" data-row-band="${esc(row.band || "")}" data-row-state="${esc(row.status)}">
    <td class="name"><div class="campaign-service-name"><strong>${esc(row.name)}</strong><span class="chip muted-chip">مجموعة ${(row.members || []).length}</span>${warningChips(row)}</div><div class="sub campaign-group-members">${members}</div></td>
    <td class="campaign-driver-cell">${driverOptions(row)}</td>
    <td dir="ltr">${vehicleOptions(row)}</td>
    <td><div class="campaign-vehicle-type">${vehicleTypeOptions(row)}${row.vehicle ? `<div class="sub">${esc(row.vehicle.model || "")}</div>` : ""}</div></td>
    <td class="col-actions"><div class="row-actions"><button type="button" class="mini" data-action="renameCampaignGroup" data-id="${esc(row.id)}">${icon("edit")} تسمية</button><button type="button" class="mini danger" data-action="ungroupCampaign" data-id="${esc(row.id)}">فك التجميع</button></div></td>
  </tr>`;
}

function postDriver(row) {
  const title = row.driver_text ? ` title="${esc(row.driver_text)}"` : "";
  return `<input class="campaign-post-driver${row.driver_text ? "" : " is-empty"}" data-post-driver="${esc(row.id)}" data-control-key="${esc(controlKey(row, "driver"))}" data-required-field="driver" value="${esc(row.driver_text || "")}" maxlength="200"${title} aria-label="السائق في ${esc(row.name)}">`;
}

function postRow(row) {
  const plate = row.vehicle?.label || row.vehicle?.plate || row.plate_text || "—";
  const type = row.type_text || row.vehicle?.type || "—";
  return `<tr class="campaign-row${rowStateClass(row)}${row.warnings?.length ? " has-warning" : ""}" data-row-key="${esc(rowKey(row))}" data-section="posts" data-row-state="${esc(row.status)}">
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
  return `<div class="mcard campaign-table-card campaign-posts-card" data-campaign-section="posts"><h3>مركبات الارتكازات<span class="mcount">${rows.length}</span>${summaryChip("posts")}${action}</h3><div data-section-body>${body}</div></div>`;
}

function serverPlatesText() {
  return (CAMPAIGN.plates?.rows || []).map(row => row.join(" ")).join("\n");
}

function platesText() {
  return CAMPAIGN_PLATES_DRAFT?.day === DAY ? CAMPAIGN_PLATES_DRAFT.value : serverPlatesText();
}

function updatePlatesDraft(value) {
  const savedValue = CAMPAIGN_PLATES_DRAFT?.day === DAY
    ? CAMPAIGN_PLATES_DRAFT.savedValue : serverPlatesText();
  CAMPAIGN_PLATES_DRAFT = {day: DAY, value, savedValue, dirty: value !== savedValue};
  clearTimeout(CAMPAIGN_PLATES_TIMER);
  CAMPAIGN_PLATES_TIMER = CAMPAIGN_PLATES_DRAFT.dirty
    ? setTimeout(() => savePlatesDraft(), 800) : null;
}

function platesCard() {
  return `<div class="mcard campaign-plates-card"><h3>سجل اللوحات<span id="campaignPlatesInherited">${inheritedBadge(CAMPAIGN.plates)}</span></h3><textarea id="campaignPlates" class="campaign-plates" data-control-key="plates" dir="ltr" rows="4" placeholder="ب13/9416 ب13/9417">${esc(platesText())}</textarea></div>`;
}

function summaryChip(section) {
  const summaries = CAMPAIGN.summary?.sections || {};
  const summary = section === "routes"
    ? ["lorries", "services", "appointments"].reduce((total, key) => ({
      missing: total.missing + (summaries[key]?.missing || 0),
      total: total.total + (summaries[key]?.total || 0),
    }), {missing: 0, total: 0})
    : (summaries[section] || {});
  return summary.missing
    ? `<span class="campaign-missing-chip" data-summary-section="${esc(section)}">ناقص ${summary.missing}</span>`
    : `<span class="campaign-complete-chip" data-summary-section="${esc(section)}">مكتمل</span>`;
}

function bandedRows(rows, section, options = {}) {
  const markup = [];
  let previousBand = null;
  rows.forEach(row => {
    if (row.band !== previousBand && !(options.skipFirstBand && !markup.length)) {
      markup.push(`<tr class="campaign-band-row" data-campaign-band="${esc(row.band || "")}"><th colspan="5">${esc(row.band_label || "")}</th></tr>`);
    }
    markup.push(campaignRow(row, row.kind === "lorry", section));
    previousBand = row.band;
  });
  return markup;
}

function routesCard() {
  const rows = orderedCampaignRows().filter(row => !["security", "ambulance", "driver_only"].includes(row.band));
  const groupBtn = `<button type="button" class="mini on-dark" id="campaignGroupBtn" data-action="openCampaignGroup"${GROUP_SELECTION.size >= 2 ? "" : " disabled"}>تجميع خدمات${GROUP_SELECTION.size ? ` (${GROUP_SELECTION.size})` : ""}</button>`;
  const body = rows.length ? `<div class="mtable-wrap">${mtable(["الخدمة", "السائق", "رقم المركبة", "نوع المركبة", "الإجراء"], bandedRows(rows, "routes"))}</div>` : emptyState({compact: true, title: "لا توجد خطوط سير اليوم"});
  return `<div class="mcard campaign-table-card campaign-routes-card" data-campaign-section="routes"><h3>خطوط السير<span class="mcount">${rows.length}</span>${summaryChip("routes")}${groupBtn}</h3><div data-section-body>${body}</div></div>`;
}

function dailyCard() {
  const rows = orderedCampaignRows().filter(row => ["security", "ambulance", "driver_only"].includes(row.band));
  const action = `<button type="button" class="mini on-dark" data-action="openCampaignDaily">${icon("plus")} إضافة</button>`;
  const body = rows.length ? `<div class="mtable-wrap">${mtable(["الخدمة", "السائق", "رقم المركبة", "نوع المركبة", "الإجراء"], bandedRows(rows, "daily", {skipFirstBand: rows[0]?.band === "security"}))}</div>` : emptyState({compact: true, title: "لا توجد أقوال أمنية اليوم"});
  return `<div class="mcard campaign-table-card campaign-daily-card" data-campaign-section="daily"><h3>الأقوال الأمنية<span class="mcount">${rows.length}</span>${summaryChip("daily")}${action}</h3><div data-section-body>${body}</div></div>`;
}

function renderWarnings() {
  if (!CAMPAIGN.warnings?.length) return "";
  return `<div class="alert-card campaign-alert"><div class="alert-head"><span class="alert-ico">${icon("alert")}</span><strong>تنبيهات المراجعة</strong></div><ul class="alert-list">${CAMPAIGN.warnings.map(item => `<li><b>${esc(item.row)}</b> — ${esc(item.text)}</li>`).join("")}</ul></div>`;
}

function renderSaveError() {
  if (!CAMPAIGN_SAVE_ERROR) return "";
  return `<div class="data-region-error campaign-save-error" role="alert">${icon("alert")}<div><strong>لم يُحفظ آخر تعديل</strong><span>${esc(CAMPAIGN_SAVE_ERROR)}</span></div></div>`;
}

function overallSummary() {
  const summary = CAMPAIGN.summary?.overall || {missing: 0, total: 0};
  const text = summary.missing
    ? `<b>ناقص ${summary.missing} من ${summary.total} صف مطلوب</b>`
    : (summary.total ? "كل الصفوف المطلوبة متسكنة" : "لا توجد صفوف مطلوبة للتسكين");
  return `<p class="vacancy-summary ${summary.missing ? "warn" : "ok"}"><span class="status-dot ${summary.missing ? "warn" : "ok"}" aria-hidden="true"></span>${text}</p>`;
}

function captureDrafts() {
  const drafts = new Map();
  document.querySelectorAll("#campaignWrap input[data-post-driver]").forEach(input => {
    const row = rowBy(input.dataset.postDriver);
    if (input.value !== (row?.driver_text || "")) drafts.set(input.dataset.controlKey, {value: input.value});
  });
  document.querySelectorAll("#campaignWrap select[data-control-key]").forEach(select => {
    if (select._comboCustomDraft !== null && select._comboCustomDraft !== undefined) {
      drafts.set(select.dataset.controlKey, {value: select._comboCustomDraft, combo: true});
    }
  });
  return drafts;
}

function activeSnapshot() {
  const active = document.activeElement;
  if (!active) return null;
  let key = active.dataset?.controlKey;
  let select = null;
  if (!key) {
    select = [...document.querySelectorAll("#campaignWrap select[data-control-key]")]
      .find(item => item._comboInput === active);
    key = select?.dataset.controlKey;
  }
  if (!key) {
    const action = active.closest?.("#campaignWrap [data-action]");
    if (!action) return null;
    return {action: action.dataset.action, id: action.dataset.id || "", element: active};
  }
  return {key, value: active.value, combo: !!select,
    custom: select?._comboCustomDraft, start: active.selectionStart, end: active.selectionEnd,
    element: active};
}

function visibleControl(key) {
  const control = document.querySelector(`#campaignWrap [data-control-key="${CSS.escape(key)}"]`);
  return control?._comboInput || control;
}

function focusControl(key, quiet = false) {
  const native = document.querySelector(`#campaignWrap select[data-control-key="${CSS.escape(key)}"]`);
  const control = native?._comboInput || visibleControl(key);
  if (!control) return;
  if (quiet && native) native.disabled = true;
  control.focus({preventScroll: true});
  if (quiet && native) native.disabled = false;
  const rect = control.getBoundingClientRect();
  const top = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--topbar-h")) || 60;
  if (rect.top < top + 8 || rect.bottom > window.innerHeight - 8) {
    control.scrollIntoView({block: "nearest", inline: "nearest"});
  }
}

function restoreDrafts(drafts) {
  drafts.forEach((draft, key) => {
    const native = document.querySelector(`#campaignWrap select[data-control-key="${CSS.escape(key)}"]`);
    const control = native?._comboInput || visibleControl(key);
    if (!control) return;
    if (draft.combo && native) native._comboCustomDraft = draft.value;
    control.value = draft.value;
  });
}

function restoreActive(snapshot, quietKey = "") {
  if (!snapshot || snapshot.element?.isConnected) return;
  if (snapshot.action) {
    const selector = `#campaignWrap [data-action="${CSS.escape(snapshot.action)}"]${snapshot.id ? `[data-id="${CSS.escape(snapshot.id)}"]` : ""}`;
    const target = document.querySelector(selector) || $("#campaignMissingOnly");
    target?.focus({preventScroll: true});
    return;
  }
  const native = document.querySelector(`#campaignWrap select[data-control-key="${CSS.escape(snapshot.key)}"]`);
  const control = native?._comboInput || visibleControl(snapshot.key);
  if (!control) return;
  const quiet = snapshot.key === quietKey;
  if (!quiet) {
    if (snapshot.combo && native && snapshot.custom !== null && snapshot.custom !== undefined) {
      native._comboCustomDraft = snapshot.custom;
    }
    control.value = snapshot.value;
  }
  focusControl(snapshot.key, quiet);
  if (!quiet && snapshot.start !== null && snapshot.start !== undefined) {
    control.setSelectionRange?.(snapshot.start, snapshot.end);
  }
}

function focusAction(action, id = "") {
  setTimeout(() => {
    const selector = `#campaignWrap [data-action="${CSS.escape(action)}"]${id ? `[data-id="${CSS.escape(id)}"]` : ""}`;
    (document.querySelector(selector) || $("#campaignMissingOnly"))?.focus({preventScroll: true});
  }, 0);
}

function rowMarkup(row, section) {
  return row.kind === "post" ? postRow(row) : campaignRow(row, row.kind === "lorry", section);
}

function bindRowControls(root) {
  upgradeSelects(root);
  root.querySelectorAll("select[data-control-key]").forEach(select => {
    if (select._comboInput) select._comboInput.dataset.controlKey = select.dataset.controlKey;
  });
  root.querySelectorAll("select[data-driver-row]").forEach(select => {
    if (select.dataset.customValue) select.value = select.dataset.customValue;
    if (select.dataset.fullValue) select._comboInput?.setAttribute("title", select.dataset.fullValue);
    const initial = rowBy(select.dataset.driverRow)?.driver;
    let savedValue = initial?.kind === "text" ? initial.name : (initial?.kind ? `${initial.kind}|${initial.id}` : "");
    let draftEdited = false, explicitChange = false;
    const saveDriver = (value, explicit = false, previousValue = savedValue) => {
      const row = rowBy(select.dataset.driverRow);
      const driver = driverValuePayload(value);
      saveRow(row, {driver}, {sourceKey: select.dataset.controlKey,
        undoBody: {driver: driverValuePayload(previousValue)}, undoLabel: "تعديل السائق"});
      if (explicit) scheduleNextGap(select.dataset.controlKey);
    };
    select.addEventListener("input", () => { draftEdited = true; explicitChange = false; });
    select.addEventListener("change", () => {
      explicitChange = true;
      draftEdited = false;
      const value = select.value.trim();
      if (value === savedValue) { scheduleNextGap(select.dataset.controlKey); return; }
      const previousValue = savedValue;
      savedValue = value;
      saveDriver(value, true, previousValue);
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
      const previousValue = savedValue;
      savedValue = draft;
      saveDriver(draft, false, previousValue);
    }, 0));
  });
  root.querySelectorAll("select[data-vehicle-row]").forEach(select => {
    select._comboInput?.setAttribute("dir", "ltr");
    let savedValue = rowBy(select.dataset.vehicleRow)?.vehicle?.id || "";
    select.addEventListener("change", () => {
      const row = rowBy(select.dataset.vehicleRow);
      const value = select.value;
      const previous = savedValue;
      const vehicle = (CAMPAIGN.pickers?.vehicles || []).find(item => item.id === value);
      if (vehicle) CAMPAIGN_TYPE_FILTERS.set(row.id, vehicle.type);
      if (value !== previous) saveRow(row, {vehicle_id: value}, {
        sourceKey: select.dataset.controlKey, undoBody: {vehicle_id: previous}, undoLabel: "تعديل المركبة"});
      savedValue = value;
      scheduleNextGap(select.dataset.controlKey);
    });
  });
  root.querySelectorAll("select[data-type-row]").forEach(select => {
    select.addEventListener("change", () => {
      CAMPAIGN_TYPE_FILTERS.set(select.dataset.typeRow, select.value);
      const tr = select.closest("tr[data-row-key]");
      const row = rowByKey(tr.dataset.rowKey);
      replaceRow(tr, row, tr.dataset.section);
      scheduleNextGap(select.dataset.controlKey);
    });
  });
  root.querySelectorAll("input[data-post-driver]").forEach(input => {
    const original = rowBy(input.dataset.postDriver)?.driver_text || "";
    input.addEventListener("input", () => {
      input.classList.toggle("is-empty", !input.value.trim());
      input.title = input.value.trim();
    });
    input.addEventListener("blur", () => {
      const value = input.value.trim();
      if (value !== original) saveRow(rowBy(input.dataset.postDriver), {driver_text: value}, {
        sourceKey: input.dataset.controlKey, undoBody: {driver_text: original}, undoLabel: "تعديل سائق الارتكاز"});
    });
  });
  root.querySelectorAll("input[data-group-pick]").forEach(input => input.onchange = () => {
    input.checked ? GROUP_SELECTION.add(input.dataset.groupPick) : GROUP_SELECTION.delete(input.dataset.groupPick);
    const button = $("#campaignGroupBtn");
    if (button) { button.disabled = GROUP_SELECTION.size < 2; button.textContent = `تجميع خدمات${GROUP_SELECTION.size ? ` (${GROUP_SELECTION.size})` : ""}`; }
  });
  root.querySelectorAll("button[data-action='openCampaignServiceVehicles']").forEach(button => {
    button.onclick = () => openServiceVehicles(rowBy(button.dataset.id));
  });
}

function replaceRow(oldRow, row, section) {
  if (!oldRow || !row) return null;
  const holder = document.createElement("tbody");
  holder.innerHTML = rowMarkup(row, section);
  const replacement = holder.firstElementChild;
  oldRow.replaceWith(replacement);
  bindRowControls(replacement);
  return replacement;
}

function patchCampaign(previous, options = {}) {
  if (!previous || !$("#campaignWrap [data-row-key]")) { render({preserveFocus: true}); return; }
  const oldRows = new Map(rowSets(previous).map(row => [rowKey(row), row]));
  const newRows = new Map(rowSets().map(row => [rowKey(row), row]));
  if (oldRows.size !== newRows.size || [...oldRows.keys()].some(key => !newRows.has(key))) {
    render({preserveFocus: true});
    return;
  }
  const drafts = captureDrafts();
  const active = activeSnapshot();
  const scroll = window.scrollY;
  newRows.forEach((row, key) => {
    if (JSON.stringify(oldRows.get(key)) === JSON.stringify(row)) return;
    const tr = document.querySelector(`#campaignWrap tr[data-row-key="${CSS.escape(key)}"]`);
    if (tr) replaceRow(tr, row, tr.dataset.section);
  });
  updateCampaignMeta();
  restoreDrafts(drafts);
  window.scrollTo({top: scroll, behavior: "instant"});
  restoreActive(active, options.quietKey);
  applyMissingFilter();
}

function updateCampaignMeta() {
  const overall = $("#campaignOverall");
  if (overall) overall.innerHTML = overallSummary();
  const warnings = $("#campaignWarnings");
  if (warnings) warnings.innerHTML = renderWarnings();
  const error = $("#campaignSaveError");
  if (error) error.innerHTML = renderSaveError();
  Object.keys(CAMPAIGN.summary?.sections || {}).forEach(section => {
    const chip = document.querySelector(`[data-summary-section="${CSS.escape(section)}"]`);
    if (!chip) return;
    const holder = document.createElement("span");
    holder.innerHTML = summaryChip(section);
    chip.replaceWith(holder.firstElementChild);
  });
  const routesChip = document.querySelector('[data-summary-section="routes"]');
  if (routesChip) {
    const holder = document.createElement("span");
    holder.innerHTML = summaryChip("routes");
    routesChip.replaceWith(holder.firstElementChild);
  }
  const inherited = $("#campaignPlatesInherited");
  if (inherited) inherited.innerHTML = inheritedBadge(CAMPAIGN.plates);
}

function scheduleNextGap(sourceKey) {
  setTimeout(() => {
    const controls = [...document.querySelectorAll("#campaignWrap [data-control-key]")];
    const index = controls.findIndex(control => control.dataset.controlKey === sourceKey);
    const next = controls.slice(index + 1).find(control => {
      if (control.dataset.controlKey === sourceKey) return false;
      if (!control.dataset.requiredField || control.closest("tr")?.hidden) return false;
      const row = rowByKey(control.closest("tr")?.dataset.rowKey || "");
      return (row?.missing || []).includes(control.dataset.requiredField);
    });
    focusControl(next?.dataset.controlKey || sourceKey, !next);
  }, 0);
}

function applyMissingFilter() {
  document.querySelectorAll("#campaignWrap tr[data-row-key]").forEach(tr => {
    const missing = ["partial", "empty"].includes(tr.dataset.rowState);
    if (CAMPAIGN_MISSING_ONLY && missing) CAMPAIGN_FILTER_PINNED.add(tr.dataset.rowKey);
    tr.hidden = CAMPAIGN_MISSING_ONLY && !missing && !CAMPAIGN_FILTER_PINNED.has(tr.dataset.rowKey);
  });
  document.querySelectorAll("#campaignWrap [data-campaign-section]").forEach(card => {
    card.querySelectorAll("tr[data-campaign-band]").forEach(bandRow => {
      const band = bandRow.dataset.campaignBand;
      const rows = [...card.querySelectorAll(`tr[data-row-band="${CSS.escape(band)}"]`)];
      bandRow.hidden = !rows.some(row => !row.hidden);
    });
    const body = card.querySelector("[data-section-body]");
    const rows = [...card.querySelectorAll("tr[data-row-key]")];
    if (body) body.hidden = CAMPAIGN_MISSING_ONLY && !rows.some(row => !row.hidden);
  });
}

function bindCampaign(root) {
  bindRowControls(root);
  const platesInput = root.querySelector("#campaignPlates");
  if (platesInput) {
    platesInput.addEventListener("input", () => updatePlatesDraft(platesInput.value));
    platesInput.addEventListener("blur", () => savePlatesDraft());
  }
}

function render(options = {}) {
  const wrap = $("#campaignWrap");
  if (!CAMPAIGN) { wrap.innerHTML = skeleton("cards", 3); return; }
  const drafts = options.preserveFocus ? captureDrafts() : new Map();
  const active = options.preserveFocus ? activeSnapshot() : null;
  const scroll = options.preserveFocus ? window.scrollY : null;
  const selectable = new Set(campaignServices().filter(row => row.kind === "service" && !(
    !(row.service_vehicles || []).some(item => item.source === "direct") &&
    (row.service_vehicles || []).some(item => item.source === "lorry")
  )).map(row => row.id));
  [...GROUP_SELECTION].forEach(id => { if (!selectable.has(id)) GROUP_SELECTION.delete(id); });
  wrap.innerHTML = `<div id="campaignSaveError">${renderSaveError()}</div><div id="campaignOverall">${overallSummary()}</div><div id="campaignWarnings">${renderWarnings()}</div><div class="ledger-board"><div class="ledger-head"><h2>يومية الحملة</h2><div class="ledger-sub">${dayName(CAMPAIGN.date)} الموافق ${fmt(CAMPAIGN.date)}</div></div>${postCard()}${routesCard()}${dailyCard()}${platesCard()}</div>`;
  bindCampaign(wrap);
  restoreDrafts(drafts);
  if (scroll !== null) window.scrollTo({top: scroll, behavior: "instant"});
  restoreActive(active);
  applyMissingFilter();
}

function parsePlates(value) {
  return value.split(/\n/).map(line => line.split(/[ ,،]+/)
    .map(cell => cell.trim()).filter(Boolean)).filter(row => row.length);
}

async function savePlatesDraft() {
  clearTimeout(CAMPAIGN_PLATES_TIMER);
  CAMPAIGN_PLATES_TIMER = null;
  if (CAMPAIGN_PLATES_SAVE) {
    const saved = await CAMPAIGN_PLATES_SAVE;
    if (!saved) return false;
    return CAMPAIGN_PLATES_DRAFT?.day === DAY && CAMPAIGN_PLATES_DRAFT.dirty
      ? savePlatesDraft() : true;
  }
  const draft = CAMPAIGN_PLATES_DRAFT;
  if (!draft || draft.day !== DAY || !draft.dirty) return true;
  const savedText = draft.value;
  const previousRows = parsePlates(draft.savedValue);
  const request = campaignWrite(`/api/campaign/${DAY}/plates`, "PUT", {rows: parsePlates(savedText)}, {
    noLoader: true,
  });
  CAMPAIGN_PLATES_SAVE = request;
  const out = await request;
  if (CAMPAIGN_PLATES_SAVE === request) CAMPAIGN_PLATES_SAVE = null;
  if (!out) return false;
  if (CAMPAIGN_PLATES_DRAFT?.day === DAY && CAMPAIGN_PLATES_DRAFT.value === savedText) {
    CAMPAIGN_PLATES_DRAFT.savedValue = savedText;
    CAMPAIGN_PLATES_DRAFT.dirty = false;
  } else if (CAMPAIGN_PLATES_DRAFT?.day === DAY) {
    CAMPAIGN_PLATES_DRAFT.savedValue = savedText;
    CAMPAIGN_PLATES_DRAFT.dirty = CAMPAIGN_PLATES_DRAFT.value !== savedText;
    if (CAMPAIGN_PLATES_DRAFT.dirty) CAMPAIGN_PLATES_TIMER = setTimeout(() => savePlatesDraft(), 800);
  }
  rememberUndo({url: `/api/campaign/${DAY}/plates`, method: "PUT", body: {rows: previousRows},
    label: "تعديل سجل اللوحات", kind: "plates"});
  return true;
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
    const vehicles = state.vehicles.map(item => ({vehicle_id: item.vehicle_id,
      personnel_ids: item.personnel_ids || [], officer_ids: item.officer_ids || [],
      ...(item.driver ? {driver: driverPayload(item.driver)} : {})}));
    clearUndo();
    const out = await campaignWrite(`/api/campaign/${DAY}/service/${encodeURIComponent(row.id)}`, "PUT", {vehicles}, {structural: true});
    if (out) {
      closeModal("campaignServiceVehiclesModal", true);
      focusAction("openCampaignServiceVehicles", row.id);
      showToast("تم حفظ مركبات الخدمة");
    }
  };
  renderEditor(); openModal("campaignServiceVehiclesModal");
}

async function loadDay(day) {
  const out = await api(`/api/campaign/${day}`);
  if (!out) { UI.regionError("#campaignWrap", {message:"تعذر تحميل يومية الحملة.", retry:()=>loadDay(day)}); return; }
  UI.regionReady("#campaignWrap");
  const changingDay = DAY !== null && DAY !== day;
  if (changingDay) {
    clearTimeout(CAMPAIGN_PLATES_TIMER);
    CAMPAIGN_PLATES_TIMER = null;
    CAMPAIGN_PLATES_SAVE = null;
    CAMPAIGN_TYPE_FILTERS.clear();
    GROUP_SELECTION.clear();
    CAMPAIGN_FILTER_PINNED.clear();
    CAMPAIGN_MISSING_ONLY = false;
    $("#campaignMissingOnly").checked = false;
    CAMPAIGN_PLATES_DRAFT = null;
    CAMPAIGN_SAVE_ERROR = "";
    clearUndo();
  }
  DAY = day;
  stabilizeCampaignOrder(out, true);
  CAMPAIGN = out;
  $("#dutyDate").value = day;
  setPageDay(day);
  setSaveState("saved");
  render();
  loadDayStatus();
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
  clearUndo();
  const out = await campaignWrite(`/api/campaign/${DAY}/groups/${encodeURIComponent(id)}`, "DELETE", {}, {structural: true});
  if (out) { $("#campaignMissingOnly").focus({preventScroll: true}); showToast("تم فك التجميع"); }
};

$("#campaignGroupForm").onsubmit = async event => {
  event.preventDefault();
  const id = $("#campaignGroupId").value, title = $("#campaignGroupName").value.trim();
  if (!title) { showToast("اكتب عنوان المجموعة", true); return; }
  clearUndo();
  const out = id
    ? await campaignWrite(`/api/campaign/${DAY}/groups/${encodeURIComponent(id)}`, "PATCH", {title}, {structural: true})
    : await campaignWrite(`/api/campaign/${DAY}/groups`, "POST", {title, members: [...GROUP_SELECTION]}, {structural: true});
  if (!out) return;
  if (!id) GROUP_SELECTION.clear();
  closeModal("campaignGroupModal", true);
  focusAction(id ? "renameCampaignGroup" : "openCampaignGroup", id);
  showToast(id ? "تم حفظ العنوان" : "تم تجميع الخدمات");
};

ACTIONS.openCampaignAttach = id => openAttach(id);
ACTIONS.detachCampaignService = async (id, extra) => {
  const row = rowBy(id);
  clearUndo();
  const out = await campaignWrite(`/api/campaign/${DAY}/lorry/${encodeURIComponent(row.id)}/service`, "DELETE", extra, {structural: true});
  if (out) { focusAction("openCampaignAttach", row.id); showToast("تمت إزالة الخدمة"); }
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
  clearUndo();
  const out = await campaignWrite(`/api/campaign/${DAY}/posts/${encodeURIComponent(id)}`, "DELETE", {}, {structural: true});
  if (out) { $("#campaignMissingOnly").focus({preventScroll: true}); showToast("تمت إزالة الارتكاز"); }
};
ACTIONS.removeCampaignDaily = async (id, extra) => {
  if (!(await confirmDialog({title: "إزالة القول اليومي", body: `ستُزال «${extra.name}» ابتداءً من اليوم، وتبقى الأيام السابقة دون تغيير.`, confirmLabel: "إزالة", danger: true}))) return;
  clearUndo();
  const out = await campaignWrite(`/api/campaign/${DAY}/daily-rows/${encodeURIComponent(id)}`, "DELETE", {}, {structural: true});
  if (out) { $("#campaignMissingOnly").focus({preventScroll: true}); showToast("تمت إزالة القول"); }
};

$("#campaignAttachForm").onsubmit = async event => {
  event.preventDefault();
  const select = $("#campaignAttachSelect"), value = select.value.trim();
  if (!value) { showToast("حدد خدمة أو اكتب اسمًا", true); return; }
  const known = (CAMPAIGN.pickers?.attachable || []).find(item => item.assignment_id === value);
  const body = known ? {assignment_id: value} : {name: value};
  clearUndo();
  const out = await campaignWrite(`/api/campaign/${DAY}/lorry/${encodeURIComponent($("#campaignAttachLorry").value)}/service`, "POST", body, {structural: true});
  if (out) {
    const lorryId = $("#campaignAttachLorry").value;
    closeModal("campaignAttachModal", true);
    focusAction("openCampaignAttach", lorryId);
    showToast("تمت إضافة الخدمة");
  }
};

$("#campaignDailyForm").onsubmit = async event => {
  event.preventDefault();
  const name = $("#campaignDailyName").value.trim();
  const basic_entry_id = $("#campaignDailyBasic").value;
  if (!name) return;
  clearUndo();
  const out = await campaignWrite(`/api/campaign/${DAY}/daily-rows`, "POST", {name, basic_entry_id}, {structural: true});
  if (out) {
    closeModal("campaignDailyModal", true);
    focusAction("openCampaignDaily");
    showToast("تمت إضافة القول");
  }
};

$("#campaignPostForm").onsubmit = async event => {
  event.preventDefault();
  const id = $("#campaignPostId").value;
  const body = {name: $("#campaignPostName").value.trim(), number: $("#campaignPostNumber").value.trim()};
  if (!id) body.driver_text = $("#campaignPostDriver").value.trim();
  if (!body.name) return;
  const url = id ? `/api/campaign/${DAY}/posts/${encodeURIComponent(id)}` : `/api/campaign/${DAY}/posts`;
  clearUndo();
  const out = await campaignWrite(url, id ? "PATCH" : "POST", body, {structural: true});
  if (out) {
    closeModal("campaignPostModal", true);
    focusAction(id ? "editCampaignPost" : "openCampaignPost", id);
    showToast(id ? "تم تعديل الارتكاز من اليوم" : "تمت إضافة الارتكاز");
  }
};

async function navigateDay(day) {
  if (!day || day === DAY) { $("#dutyDate").value = DAY || day; return; }
  const platesSaved = await savePlatesDraft();
  await CAMPAIGN_WRITE_QUEUE;
  if (!platesSaved || (CAMPAIGN_PLATES_DRAFT?.day === DAY && CAMPAIGN_PLATES_DRAFT.dirty)) {
    $("#dutyDate").value = DAY;
    return;
  }
  await loadDay(day);
}

$("#campaignMissingOnly").onchange = event => {
  CAMPAIGN_MISSING_ONLY = event.target.checked;
  CAMPAIGN_FILTER_PINNED.clear();
  if (CAMPAIGN_MISSING_ONLY) rowSets().filter(row => ["partial", "empty"].includes(row.status))
    .forEach(row => CAMPAIGN_FILTER_PINNED.add(rowKey(row)));
  applyMissingFilter();
};

$("#campaignUndo").onclick = async () => {
  const change = CAMPAIGN_UNDO;
  if (!change) return;
  const out = await campaignWrite(change.url, change.method, change.body, {noLoader: true});
  if (!out || CAMPAIGN_UNDO !== change) return;
  if (change.kind === "plates") {
    clearTimeout(CAMPAIGN_PLATES_TIMER);
    CAMPAIGN_PLATES_TIMER = null;
    const value = serverPlatesText();
    CAMPAIGN_PLATES_DRAFT = {day: DAY, value, savedValue: value, dirty: false};
    const textarea = $("#campaignPlates");
    if (textarea) textarea.value = value;
  }
  clearUndo();
};

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
