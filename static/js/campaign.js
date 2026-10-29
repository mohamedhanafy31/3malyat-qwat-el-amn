/* يومية الحملة — تسكين سريع للسائق والمركبة مع حفظ فوري. */
let CAMPAIGN = null, DAY = null;
const CAMPAIGN_TYPE_FILTERS = new Map();

window.exportDocxUrl = () => `/api/campaign/${DAY}/export.docx`;

const rowSets = () => [...(CAMPAIGN?.lorries || []), ...(CAMPAIGN?.appointments || []),
  ...(CAMPAIGN?.services || []), ...(CAMPAIGN?.daily || []), ...(CAMPAIGN?.posts || [])];
const rowBy = id => rowSets().find(row => row.id === id);

function staleReload(out, status) {
  if (status === 409 && out?.code === "stale_revision") {
    showToast(out.error || "تغيّرت اليومية؛ حدّث الصفحة.", true);
    loadDay(DAY);
    return true;
  }
  return false;
}

async function saveRow(row, body) {
  const scroll = window.scrollY;
  const out = await api(`/api/campaign/${DAY}/${row.kind}/${encodeURIComponent(row.id)}`,
    {...jsonReq("PUT", {...body, revision: CAMPAIGN.revision}), onError: staleReload});
  if (!out) return;
  CAMPAIGN = out;
  render();
  window.scrollTo({top: scroll, behavior: "instant"});
}

function driverOptions(row) {
  const selected = row.driver?.kind && row.driver.kind !== "text" ? `${row.driver.kind}|${row.driver.id}` : "";
  const personnel = CAMPAIGN.pickers?.drivers?.personnel || [];
  const conscripts = CAMPAIGN.pickers?.drivers?.conscripts || [];
  const groups = (list, label, withRole) => `<optgroup label="${esc(label)}">${list.map(person => {
    const text = withRole && person.role ? `${person.role}/ ${person.name}` : person.name;
    return `<option value="${esc(withRole ? `personnel|${person.id}` : `conscript|${person.id}`)}"${selected === (withRole ? `personnel|${person.id}` : `conscript|${person.id}`) ? " selected" : ""}>${esc(text)}</option>`;
  }).join("")}</optgroup>`;
  const custom = row.driver?.kind === "text" ? ` data-custom-value="${esc(row.driver.name)}"` : "";
  return `<select class="campaign-inline-select" data-driver-row="${esc(row.id)}" data-combo-custom data-combo-custom-option="none" data-maxlength="200"${custom} aria-label="السائق في ${esc(row.name)}">
    <option value="">— بدون سائق —</option>${groups(personnel, "الأفراد السواقين", true)}${groups(conscripts, "المجندون", false)}</select>`;
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
  return `${row.inherited ? `<span class="chip muted-chip">من اليوم السابق</span>` : ""}${warnings.length ? `<span class="chip taq campaign-warn" title="${esc(warnings.join(" — "))}">${icon("alert")} ${warnings.length}</span>` : ""}`;
}

function serviceCell(row, allowAttach) {
  const chips = (row.attached || []).map(item => `<span class="chip campaign-attach-chip">${esc(item.name)}<button type="button" data-action="detachCampaignService" data-id="${esc(row.id)}" data-extra="${dataAttr(item)}" aria-label="إزالة ${esc(item.name)}">×</button></span>`).join("");
  const add = allowAttach ? `<button type="button" class="mini btn-xs campaign-add-service" data-action="openCampaignAttach" data-id="${esc(row.id)}">${icon("plus")} إضافة خدمة</button>` : "";
  return `<div class="campaign-service-name"><strong>${esc(row.base_name || row.name)}</strong>${chips}${add}${warningChips(row)}</div>`;
}

function campaignRow(row, allowAttach) {
  const driver = row.driver;
  return `<tr class="campaign-row${row.warnings?.length ? " has-warning" : ""}">
    <td class="name">${serviceCell(row, allowAttach)}</td>
    <td>${driverOptions(row)}</td>
    <td dir="ltr">${vehicleOptions(row)}</td>
    <td><div class="campaign-vehicle-type">${vehicleTypeOptions(row)}${row.vehicle ? `<div class="sub">${esc(row.vehicle.model || "")}${row.vehicle.origin === "external" ? `${row.vehicle.model ? " — " : ""}خارجية: ${esc(row.vehicle.party)}` : ""}</div>` : ""}</div></td>
    <td class="col-actions">${row.kind === "daily" ? rowMenu([{action: "removeCampaignDaily", id: row.id, extra: {name: row.name}, label: "إزالة", danger: true}]) : "—"}</td>
  </tr>`;
}

function postDriver(row) {
  return `<input class="campaign-post-driver" data-post-driver="${esc(row.id)}" value="${esc(row.driver_text || "")}" maxlength="200" aria-label="السائق في ${esc(row.name)}">`;
}

function postRow(row) {
  const plate = row.vehicle?.label || row.vehicle?.plate || row.plate_text || "—";
  const type = row.type_text || row.vehicle?.type || "—";
  return `<tr class="campaign-row${row.warnings?.length ? " has-warning" : ""}">
    <td>${esc(row.number || "")}</td><td class="name"><strong>${esc(row.name)}</strong>${warningChips(row)}</td>
    <td>${postDriver(row)}</td><td dir="ltr"><div class="campaign-vehicle-cell">${vehicleOptions(row)}${!row.vehicle && row.plate_text ? `<span class="muted-text" dir="ltr">${esc(plate)}</span>` : ""}</div></td>
    <td><div class="campaign-vehicle-type">${vehicleTypeOptions(row)}${!row.vehicle && row.type_text ? `<span class="muted-text">${esc(type)}</span>` : ""}</div></td>
    <td class="col-actions"><div class="row-actions"><button class="mini" type="button" data-action="editCampaignPost" data-id="${esc(row.id)}">تعديل</button>${rowMenu([{action: "removeCampaignPost", id: row.id, extra: {name: row.name}, label: "إزالة", danger: true}])}</div></td>
  </tr>`;
}

function postCard() {
  const rows = CAMPAIGN.posts || [];
  const action = `<button type="button" class="mini on-dark" data-action="openCampaignPost">${icon("plus")} إضافة</button>`;
  const body = rows.length ? `<div class="mtable-wrap">${mtable(["الرقم", "الارتكاز", "السائق", "رقم المركبة", "نوع المركبة", "الإجراء"], rows.map(postRow))}</div>` : emptyState({compact: true, title: "لا توجد ارتكازات اليوم"});
  return `<div class="mcard"><h3>مركبات الارتكازات<span class="mcount">${rows.length}</span>${action}</h3>${body}</div>`;
}

function platesCard() {
  const rows = (CAMPAIGN.plates?.rows || []).map(row => row.join(" ")).join("\n");
  return `<div class="mcard campaign-plates-card"><h3>سجل اللوحات${CAMPAIGN.plates?.inherited ? `<span class="chip muted-chip">من اليوم السابق</span>` : ""}</h3><textarea id="campaignPlates" class="campaign-plates" dir="ltr" rows="4" placeholder="ب13/9416 ب13/9417">${esc(rows)}</textarea><div class="actions"><button type="button" class="primary" id="saveCampaignPlates">حفظ</button></div></div>`;
}

function tableCard(title, rows, empty, options = {}) {
  const action = options.add ? `<button type="button" class="mini on-dark" data-action="openCampaignDaily">${icon("plus")} إضافة</button>` : "";
  const body = rows.length ? `<div class="mtable-wrap">${mtable(["الخدمة", "السائق", "رقم المركبة", "نوع المركبة", "الإجراء"], rows.map(row => campaignRow(row, options.attach)))}</div>` : emptyState({compact: true, title: empty});
  return `<div class="mcard"><h3>${esc(title)}<span class="mcount">${rows.length}</span>${action}</h3>${body}</div>`;
}

function renderWarnings() {
  if (!CAMPAIGN.warnings?.length) return "";
  return `<div class="alert-card campaign-alert"><div class="alert-head"><span class="alert-ico">${icon("alert")}</span><strong>تنبيهات المراجعة</strong></div><ul class="alert-list">${CAMPAIGN.warnings.map(item => `<li><b>${esc(item.row)}</b> — ${esc(item.text)}</li>`).join("")}</ul></div>`;
}

function render() {
  const wrap = $("#campaignWrap");
  if (!CAMPAIGN) { wrap.innerHTML = skeleton("cards", 3); return; }
  const rows = rowSets();
  const missing = rows.filter(row => !row.driver || !row.vehicle).length;
  wrap.innerHTML = `<p class="vacancy-summary ${missing ? "warn" : "ok"}"><span class="status-dot ${missing ? "warn" : "ok"}" aria-hidden="true"></span>${missing ? `<b>ناقص: ${missing} صف من ${rows.length}</b>` : "لا توجد خانات ناقصة"}</p>${renderWarnings()}<div class="ledger-board"><div class="ledger-head"><h2>يومية الحملة</h2><div class="ledger-sub">${dayName(CAMPAIGN.date)} الموافق ${fmt(CAMPAIGN.date)}</div></div>${postCard()}${tableCard("اللواري الأساسية", CAMPAIGN.lorries || [], "", {attach: true})}${tableCard("الخدمات الطارئة", CAMPAIGN.services || [], "لا توجد خدمات طارئة اليوم")}${tableCard("الأقوال اليومية", CAMPAIGN.daily || [], "لا توجد أقوال يومية اليوم", {add: true})}${tableCard("لواري التعيينات", CAMPAIGN.appointments || [], "", {attach: true})}${platesCard()}</div>`;
  upgradeSelects(wrap);
  wrap.querySelectorAll("select[data-driver-row]").forEach(select => {
    if (select.dataset.customValue) select.value = select.dataset.customValue;
    select.addEventListener("change", () => {
      const value = select.value.trim();
      const driver = !value ? "" : value.includes("|")
        ? (() => { const [kind, id] = value.split("|"); return {kind, id}; })()
        : {kind: "text", name: value};
      saveRow(rowBy(select.dataset.driverRow), {driver});
    });
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
    const save = () => saveRow(rowBy(input.dataset.postDriver), {driver_text: input.value});
    input.addEventListener("change", save); input.addEventListener("blur", save);
  });
  $("#saveCampaignPlates").onclick = async () => {
    const lines = $("#campaignPlates").value.split(/\n/).map(line => line.split(/[ ,،]+/).map(v => v.trim()).filter(Boolean)).filter(row => row.length);
    const out = await api(`/api/campaign/${DAY}/plates`, {...jsonReq("PUT", {rows: lines, revision: CAMPAIGN.revision}), onError: staleReload});
    if (out) { CAMPAIGN = out; render(); showToast("تم حفظ سجل اللوحات"); }
  };
}

async function loadDay(day) {
  const out = await api(`/api/campaign/${day}`);
  if (!out) return;
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

ACTIONS.openCampaignAttach = id => openAttach(id);
ACTIONS.detachCampaignService = async (id, extra) => {
  const row = rowBy(id);
  const body = {...extra, revision: CAMPAIGN.revision};
  const out = await api(`/api/campaign/${DAY}/lorry/${encodeURIComponent(row.id)}/service`, {...jsonReq("DELETE", body), onError: staleReload});
  if (out) { CAMPAIGN = out; render(); showToast("تمت إزالة الخدمة"); }
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
  if (!(await confirmDialog({title: "إزالة الارتكاز", body: "هتتشال من النهاردة ورايح، والأيام السابقة زي ما هي", confirmLabel: "إزالة", danger: true}))) return;
  const out = await api(`/api/campaign/${DAY}/posts/${encodeURIComponent(id)}`, {...jsonReq("DELETE", {revision: CAMPAIGN.revision}), onError: staleReload});
  if (out) { CAMPAIGN = out; render(); showToast("تمت إزالة الارتكاز"); }
};
ACTIONS.removeCampaignDaily = async (id, extra) => {
  if (!(await confirmDialog({title: "إزالة القول اليومي", body: `هتتشال «${extra.name}» من النهاردة ورايح، والأيام السابقة زي ما هي.`, confirmLabel: "إزالة", danger: true}))) return;
  const out = await api(`/api/campaign/${DAY}/daily-rows/${encodeURIComponent(id)}`, {...jsonReq("DELETE", {revision: CAMPAIGN.revision}), onError: staleReload});
  if (out) { CAMPAIGN = out; render(); showToast("تمت إزالة القول"); }
};

$("#campaignAttachForm").onsubmit = async event => {
  event.preventDefault();
  const select = $("#campaignAttachSelect"), value = select.value.trim();
  if (!value) { showToast("حدد خدمة أو اكتب اسمًا", true); return; }
  const known = (CAMPAIGN.pickers?.attachable || []).find(item => item.assignment_id === value);
  const body = {...(known ? {assignment_id: value} : {name: value}), revision: CAMPAIGN.revision};
  const out = await api(`/api/campaign/${DAY}/lorry/${encodeURIComponent($("#campaignAttachLorry").value)}/service`, {...jsonReq("POST", body), onError: staleReload});
  if (out) { CAMPAIGN = out; closeModal("campaignAttachModal", true); render(); showToast("تمت إضافة الخدمة"); }
};

$("#campaignDailyForm").onsubmit = async event => {
  event.preventDefault();
  const name = $("#campaignDailyName").value.trim();
  const basic_entry_id = $("#campaignDailyBasic").value;
  if (!name) return;
  const out = await api(`/api/campaign/${DAY}/daily-rows`, {...jsonReq("POST", {name, basic_entry_id, revision: CAMPAIGN.revision}), onError: staleReload});
  if (out) { CAMPAIGN = out; closeModal("campaignDailyModal", true); render(); showToast("تمت إضافة القول"); }
};

$("#campaignPostForm").onsubmit = async event => {
  event.preventDefault();
  const id = $("#campaignPostId").value;
  const body = {name: $("#campaignPostName").value.trim(), number: $("#campaignPostNumber").value.trim(), revision: CAMPAIGN.revision};
  if (!id) body.driver_text = $("#campaignPostDriver").value.trim();
  if (!body.name) return;
  const url = id ? `/api/campaign/${DAY}/posts/${encodeURIComponent(id)}` : `/api/campaign/${DAY}/posts`;
  const out = await api(url, {...jsonReq(id ? "PATCH" : "POST", body), onError: staleReload});
  if (out) { CAMPAIGN = out; closeModal("campaignPostModal", true); render(); showToast(id ? "تم تعديل الارتكاز من اليوم" : "تمت إضافة الارتكاز"); }
};

$("#dayPrev").onclick = () => loadDay(addDays($("#dutyDate").value || curDate(), -1));
$("#dayNext").onclick = () => loadDay(addDays($("#dutyDate").value || curDate(), 1));
$("#dayToday").onclick = () => loadDay(curDate());
$("#dutyDate").onchange = () => loadDay($("#dutyDate").value);
document.addEventListener("keydown", event => {
  if (!["PageUp", "PageDown"].includes(event.key) || document.querySelector(".modal:not(.hidden), .combo-pop:not(.hidden)")) return;
  if (["INPUT", "SELECT", "TEXTAREA", "BUTTON", "A"].includes(event.target.tagName) || event.target.isContentEditable) return;
  event.preventDefault(); loadDay(addDays($("#dutyDate").value || curDate(), event.key === "PageUp" ? -1 : 1));
});

(async () => { if (await bootstrap()) loadDay(curDate()); })();
