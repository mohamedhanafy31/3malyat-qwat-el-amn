/* السواقين — عرض الأفراد السواقين وإدارة المجندين المحددين كسائقين. */
let PERSONNEL_DRIVERS = [], CONSCRIPTS = [];

function personnelDriverRow(p) {
  return `<tr><td class="name">${esc(p.name)}</td><td>${esc(p.role || "—")}</td><td dir="ltr" class="bidi-isolate">${esc(fmtPhone(p.phone) || "—")}</td><td>${esc(p.post || "—")}</td></tr>`;
}

function conscriptRow(c) {
  return `<tr><td class="name">${esc(c.name)}</td><td dir="ltr" class="bidi-isolate">${esc(fmtPhone(c.phone) || "—")}</td><td><label class="switch-label"><input type="checkbox" data-driver-toggle="1" data-id="${esc(c.id)}" ${c.is_driver ? "checked" : ""}> سواق</label></td><td class="col-actions"><button class="mini bad" data-action="deleteConscript" data-id="${esc(c.id)}" data-extra="${dataAttr({name: c.name})}">حذف</button></td></tr>`;
}

function renderDrivers() {
  $("#personnelDriversCount").textContent = PERSONNEL_DRIVERS.length;
  $("#conscriptsCount").textContent = CONSCRIPTS.length;
  $("#personnelDriversWrap").innerHTML = PERSONNEL_DRIVERS.length
    ? `<div class="table-scroll">${mtable(["الاسم", "الدرجة", "التليفون", "العمل"], PERSONNEL_DRIVERS.map(personnelDriverRow))}</div>`
    : emptyState({icon: "users", title: "لا يوجد أفراد سواقين", hint: "حدد «سائق» في خانة العمل المسند بسجل الأفراد."});
  const q = normAr($("#conscriptSearch").value);
  const rows = CONSCRIPTS.filter(c => !q || arIncludes(`${c.name} ${c.phone}`, q)).map(conscriptRow);
  $("#conscriptsWrap").innerHTML = rows.length
    ? `<div class="table-scroll">${mtable(["الاسم", "التليفون", "الصفة", "الإجراء"], rows)}</div>`
    : emptyState({icon: q ? "search" : "users", title: q ? "لا توجد نتائج مطابقة" : "لا يوجد مجندون", hint: q ? "حاول تعديل البحث." : "أضف مجندًا لتحديده كسائق عند الحاجة.", action: q ? null : {label: "إضافة مجند", id: "addConscriptBtn", primary: true}});
}

async function loadDrivers() {
  const [drivers, conscripts] = await Promise.all([api("/api/drivers"), api("/api/conscripts")]);
  if (!drivers || !conscripts) return;
  PERSONNEL_DRIVERS = drivers.personnel || [];
  CONSCRIPTS = conscripts.conscripts || [];
  renderDrivers();
}

ACTIONS.deleteConscript = async (id, extra) => {
  if (!(await confirmDialog({title: "حذف المجند", body: `سيُحذف المجند «${extra.name}» نهائيًا ولا يمكن التراجع عن ذلك.`, confirmLabel: "حذف المجند", danger: true}))) return;
  if (await api(`/api/conscripts/${encodeURIComponent(id)}`, {method: "DELETE"})) { showToast("تم حذف المجند"); loadDrivers(); }
};

document.addEventListener("change", async e => {
  const input = e.target.closest("[data-driver-toggle]");
  if (!input) return;
  const out = await api(`/api/conscripts/${encodeURIComponent(input.dataset.id)}`, jsonReq("PATCH", {is_driver: input.checked}));
  if (!out) { input.checked = !input.checked; return; }
  const c = CONSCRIPTS.find(x => x.id === input.dataset.id); if (c) c.is_driver = input.checked;
  loadDrivers();
});

$("#addConscriptBtn").onclick = () => { $("#conscriptForm").reset(); openModal("conscriptModal"); };
$("#conscriptSearch").oninput = debounce(renderDrivers);
$("#conscriptForm").onsubmit = async e => {
  e.preventDefault();
  const out = await api("/api/conscripts", jsonReq("POST", {name: $("#conscriptName").value.trim(), phone: $("#conscriptPhone").value.trim()}));
  if (!out) return;
  closeModal("conscriptModal", true); showToast("تمت إضافة المجند"); loadDrivers();
};

async function load() { if (await bootstrap()) loadDrivers(); }
load();
