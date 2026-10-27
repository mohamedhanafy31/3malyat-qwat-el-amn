/* سجل المركبات — إدارة مركبات الحملة وحالتها من شاشة واحدة. */
let VEHICLES = [], VEHICLE_TYPES = [], VEHICLE_STATUSES = {};

const vehicleStatusLabel = status => VEHICLE_STATUSES[status] || (status === "disabled" ? "معطلة" : "صالحة");
const vehicleStatusClass = status => status === "disabled" ? "err" : "on";

function vehicleMatches(v) {
  const q = normAr($("#vehicleSearch").value);
  const type = $("#vehicleTypeFilter").value;
  const status = $("#vehicleStatusFilter").value;
  const origin = $("#vehicleOriginFilter").value;
  return (!q || [v.plate, v.model, v.notes, v.party].some(x => arIncludes(x, q)))
    && (!type || v.type === type) && (!status || v.status === status)
    && (!origin || (v.origin || "internal") === origin);
}

function vehicleRow(v) {
  const fault = v.status === "disabled" && v.fault ? `<div class="sub">${esc(v.fault)}</div>` : "";
  const stateAction = v.status === "disabled"
    ? {action: "enableVehicle", label: "تشغيل"}
    : {action: "disableVehicle", label: "تعطيل"};
  const archiveAction = v.archived
    ? {action: "restoreVehicle", label: "استرجاع"}
    : {action: "archiveVehicle", label: "أرشفة"};
  return `<tr>
    <td class="name"><span dir="ltr" class="bidi-isolate">${esc(v.plate)}</span></td>
    <td>${esc(v.type)}${v.origin === "external" ? `<div class="sub"><span class="chip w">خارجية</span> ${esc(v.party)}</div>` : ""}</td>
    <td>${esc(v.model || "—")}</td>
    <td><span class="chip ${vehicleStatusClass(v.status)}">${esc(vehicleStatusLabel(v.status))}</span>${fault}</td>
    <td class="wrap">${v.notes ? esc(v.notes) : "<span class='muted'>—</span>"}</td>
    <td class="col-actions"><div class="actions">
      <button class="mini" data-action="editVehicle" data-id="${esc(v.id)}">تعديل</button>
      ${rowMenu([
        {action: stateAction.action, id: v.id, label: stateAction.label},
        {action: archiveAction.action, id: v.id, label: archiveAction.label},
        {action: "deleteVehicle", id: v.id, extra: {name: v.plate}, label: "حذف", danger: true},
      ])}
    </div></td>
  </tr>`;
}

function renderVehicles() {
  const visible = VEHICLES.filter(vehicleMatches).sort((a, b) =>
    `${a.type}\u0000${a.plate}`.localeCompare(`${b.type}\u0000${b.plate}`, "ar"));
  const active = VEHICLES.filter(v => !v.archived);
  $("#vehicleTotal").textContent = active.length;
  $("#vehicleOperational").textContent = active.filter(v => v.status === "operational").length;
  $("#vehicleDisabled").textContent = active.filter(v => v.status === "disabled").length;
  $("#vehicleExternal").textContent = active.filter(v => v.origin === "external").length;
  const rows = visible.map(vehicleRow);
  $("#vehiclesWrap").innerHTML = rows.length
    ? `<div class="table-scroll">${mtable(["اللوحة", "النوع", "الموديل", "الحالة", "ملاحظات", "الإجراء"], rows)}</div><div class="count">${countLabel(rows.length, "سجل")}</div>`
    : emptyState({icon: "inbox", title: "لا توجد مركبات", hint: "أضف مركبة جديدة أو عدّل عوامل البحث والتصفية.", action: {label: "إضافة مركبة", id: "addVehicleBtn", primary: true}});
}

async function loadVehicles() {
  const d = await api(`/api/vehicles?archived=${$("#vehicleArchived").checked ? "1" : "0"}`);
  if (!d) return;
  VEHICLES = d.vehicles || [];
  VEHICLE_TYPES = d.types || [];
  VEHICLE_STATUSES = d.statuses || {};
  fillSelect($("#vehicleTypeFilter"), [["", "كل الأنواع"], ...VEHICLE_TYPES.map(t => [t, t])], true);
  fillSelect($("#vehicleType"), VEHICLE_TYPES.map(t => [t, t]));
  renderVehicles();
}

function syncVehicleFault() {
  const disabled = $("#vehicleStatus").value === "disabled";
  $("#vehicleFaultLabel").classList.toggle("hidden", !disabled);
  $("#vehicleFault").required = disabled;
}

function syncVehicleOrigin() {
  const external = $("#vehicleOrigin").value === "external";
  $("#vehiclePartyLabel").classList.toggle("hidden", !external);
  $("#vehicleParty").required = external;
}

function openVehicle(id) {
  const v = id ? VEHICLES.find(x => x.id === id) : null;
  $("#vehicleId").value = v?.id || "";
  $("#vehicleTitle").textContent = v ? "تعديل مركبة" : "إضافة مركبة";
  $("#vehicleSeries").value = v?.plate_series || "";
  $("#vehicleNumber").value = v?.plate_number || "";
  fillSelect($("#vehicleType"), VEHICLE_TYPES.map(t => [t, t]));
  $("#vehicleType").value = v?.type || VEHICLE_TYPES[0] || "";
  $("#vehicleModel").value = v?.model || "";
  $("#vehicleStatus").value = v?.status || "operational";
  $("#vehicleFault").value = v?.fault || "";
  $("#vehicleNotes").value = v?.notes || "";
  $("#vehicleOrigin").value = v?.origin || "internal";
  $("#vehicleParty").value = v?.party || "";
  syncVehicleOrigin(); syncVehicleFault(); openModal("vehicleModal");
}

ACTIONS.editVehicle = id => openVehicle(id);
ACTIONS.disableVehicle = async id => {
  const fault = await reasonDialog({title: "تعطيل المركبة", body: "اكتب سبب التعطيل ليظهر أسفل حالة المركبة.", label: "سبب التعطيل", confirmLabel: "تعطيل المركبة"});
  if (!fault) return;
  if (await api(`/api/vehicles/${encodeURIComponent(id)}`, jsonReq("PATCH", {status: "disabled", fault}))) { showToast("تم تعطيل المركبة"); loadVehicles(); }
};
ACTIONS.enableVehicle = async id => {
  if (await api(`/api/vehicles/${encodeURIComponent(id)}`, jsonReq("PATCH", {status: "operational"}))) { showToast("تم تشغيل المركبة"); loadVehicles(); }
};
ACTIONS.archiveVehicle = async id => {
  if (await api(`/api/vehicles/${encodeURIComponent(id)}`, jsonReq("PATCH", {archived: true}))) { showToast("تمت أرشفة المركبة"); loadVehicles(); }
};
ACTIONS.restoreVehicle = async id => {
  if (await api(`/api/vehicles/${encodeURIComponent(id)}`, jsonReq("PATCH", {archived: false}))) { showToast("تم استرجاع المركبة"); loadVehicles(); }
};
ACTIONS.deleteVehicle = async (id, extra) => {
  if (!(await confirmDialog({title: "حذف المركبة", body: `ستُحذف المركبة «${extra.name}» نهائيًا ولا يمكن التراجع عن ذلك.`, confirmLabel: "حذف المركبة", danger: true}))) return;
  if (await api(`/api/vehicles/${encodeURIComponent(id)}`, {method: "DELETE"})) { showToast("تم حذف المركبة"); loadVehicles(); }
};

$("#addVehicleBtn").onclick = () => openVehicle(null);
$("#vehicleStatus").onchange = syncVehicleFault;
$("#vehicleOrigin").onchange = syncVehicleOrigin;
$("#vehicleOriginFilter").onchange = renderVehicles;
$("#vehicleSearch").oninput = debounce(renderVehicles);
$("#vehicleTypeFilter").onchange = renderVehicles;
$("#vehicleStatusFilter").onchange = renderVehicles;
$("#vehicleArchived").onchange = loadVehicles;
$("#vehicleForm").onsubmit = async e => {
  e.preventDefault();
  const body = {plate_series: $("#vehicleSeries").value.trim(), plate_number: $("#vehicleNumber").value.trim(), type: $("#vehicleType").value, model: $("#vehicleModel").value.trim(), status: $("#vehicleStatus").value, fault: $("#vehicleFault").value.trim(), notes: $("#vehicleNotes").value.trim(), origin: $("#vehicleOrigin").value, party: $("#vehicleParty").value.trim()};
  const id = $("#vehicleId").value;
  const out = await api(id ? `/api/vehicles/${encodeURIComponent(id)}` : "/api/vehicles", jsonReq(id ? "PATCH" : "POST", body));
  if (!out) return;
  closeModal("vehicleModal", true); showToast(id ? "تم حفظ التعديلات" : "تمت إضافة المركبة"); loadVehicles();
};

async function load() { if (await bootstrap()) loadVehicles(); }
load();
