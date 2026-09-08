/* كتالوج الخدمات */
let SERVICES = [];

function renderCatalog() {
  const q = $("#svcSearch").value.trim().toLowerCase(), k = $("#svcKindFilter").value;
  let rows = SERVICES;
  if (q) rows = rows.filter(s => s.name.toLowerCase().includes(q));
  if (k) rows = rows.filter(s => s.kind === k);
  const body = rows.map(s => `<tr>
      <td class="name">${esc(s.name)}</td>
      <td><span class="chip ${KIND_CLS[s.kind] || "w"}">${esc(s.kind)}</span></td>
      <td><div class="actions">
        <button class="mini" data-action="openSvc" data-id="${esc(s.id)}">تعديل</button>
        <button class="mini bad" data-action="deleteSvc" data-id="${esc(s.id)}" data-extra="${dataAttr({name: s.name})}">حذف</button>
      </div></td></tr>`);
  $("#catalogWrap").innerHTML = tableBlock(
    ["الخدمة", "التصنيف", "الإجراء"], body, `عدد الخدمات: ${rows.length}`, "لا توجد خدمات.");
}

function openSvc(id) {
  const s = id ? SERVICES.find(x => x.id === id) : null;
  $("#svcId").value = id || "";
  $("#svcTitle").textContent = s ? "تعديل خدمة" : "خدمة جديدة";
  $("#svcName").value = s ? s.name : "";
  fillSelect($("#svcKind"), KINDS().map(x => [x, x]));
  if (s) $("#svcKind").value = s.kind;
  openModal("svcModal");
}

ACTIONS.openSvc = id => openSvc(id);
ACTIONS.deleteSvc = async (id, extra) => {
  if (!confirm(`حذف خدمة «${extra.name}» من الكتالوج؟`)) return;
  if (await api(`/api/services/${encodeURIComponent(id)}`, {method: "DELETE"})) {
    showToast("تم حذف الخدمة"); load();
  }
};

$("#svcForm").onsubmit = async e => {
  e.preventDefault();
  const id = $("#svcId").value, body = {name: $("#svcName").value, kind: $("#svcKind").value};
  const out = id
    ? await api(`/api/services/${encodeURIComponent(id)}`, jsonReq("PATCH", body))
    : await api("/api/services", jsonReq("POST", body));
  if (!out) return;
  closeModal("svcModal"); showToast(id ? "تم تعديل الخدمة" : "تمت إضافة الخدمة"); load();
};
$("#svcSearch").oninput = renderCatalog;
$("#svcKindFilter").onchange = renderCatalog;
$("#addSvcBtn").onclick = () => openSvc(null);

async function load() {
  const d = await bootstrap();
  if (!d) return;
  SERVICES = d.services || [];
  fillSelect($("#svcKindFilter"), [["", "كل التصنيفات"], ...KINDS().map(x => [x, x])], true);
  renderCatalog();
}
load();
