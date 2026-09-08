/* كتالوج الخدمات — المرجع الوحيد لأسماء الخدمات.
   التكليفات بتشاور عليه بالـid، فإعادة التسمية عملية عرض بحتة. */
let SERVICES = [];

const SECTIONS = () => META.service_sections || [];
const DOCS = () => META.service_documents || [];
const DOC_LABEL = {board: "اليومية التفصيلية", afrad: "يومية الأفراد",
                   counts: "اعداد الخدمات", tashkeel: "خط التشكيل", hamla: "يومية الحملة"};

function renderCatalog() {
  const q = $("#svcSearch").value.trim().toLowerCase();
  const k = $("#svcKindFilter").value, sec = $("#svcSectionFilter").value;
  let rows = SERVICES;
  if (q) rows = rows.filter(s => (s.name + " " + (s.aliases || []).join(" ")).toLowerCase().includes(q));
  if (k) rows = rows.filter(s => s.kind === k);
  if (sec) rows = rows.filter(s => s.section === sec);
  const body = rows.map(s => `<tr>
      <td class="name">${esc(s.name)}${s.sub ? `<div class="sub">${esc(s.sub)}</div>` : ""}</td>
      <td><span class="chip ${KIND_CLS[s.kind] || "w"}">${esc(s.kind)}</span></td>
      <td class="wrap">${esc(s.section)}</td>
      <td>${(s.shifts || []).map(x => `<span class="chip w">${esc(x)}</span>`).join(" ")}</td>
      <td class="wrap">${(s.appears_in || []).map(d => esc(DOC_LABEL[d] || d)).join("، ")}</td>
      <td class="wrap">${esc(s.default_weapon) || "<span class='muted'>—</span>"}</td>
      <td class="wrap">${esc(s.default_time) || "<span class='muted'>—</span>"}</td>
      <td><div class="actions">
        <button class="mini" data-action="openSvc" data-id="${esc(s.id)}">تعديل</button>
        <button class="mini bad" data-action="deleteSvc" data-id="${esc(s.id)}" data-extra="${dataAttr({name: s.name})}">حذف</button>
      </div></td></tr>`);
  $("#catalogWrap").innerHTML = tableBlock(
    ["الخدمة", "التصنيف", "القسم", "الفترات", "تظهر في", "التسليح", "الانتظام", "الإجراء"],
    body, `عدد الخدمات: ${rows.length} من ${SERVICES.length}`, "لا توجد خدمات.");
}

const checkboxes = (name, options, chosen, labels) => options.map(o =>
  `<label class="checkline"><input type="checkbox" name="${name}" value="${esc(o)}"
    ${chosen.includes(o) ? "checked" : ""}> ${esc((labels || {})[o] || o)}</label>`).join(" ");
const readChecks = name => $$(`input[name="${name}"]:checked`).map(el => el.value);

function openSvc(id) {
  const s = id ? SERVICES.find(x => x.id === id) : null;
  $("#svcId").value = id || "";
  $("#svcTitle").textContent = s ? "تعديل خدمة" : "خدمة جديدة";
  $("#svcName").value = s ? s.name : "";
  $("#svcLabel").value = s ? s.board_label || "" : "";
  fillSelect($("#svcKind"), KINDS().map(x => [x, x]));
  fillSelect($("#svcSection"), SECTIONS().map(x => [x, x]));
  if (s) { $("#svcKind").value = s.kind; $("#svcSection").value = s.section }
  $("#svcStanding").checked = !!s?.standing;
  $("#svcShifts").innerHTML = checkboxes("svcShift", SHIFTS(), s?.shifts || SHIFTS());
  $("#svcDocs").innerHTML = checkboxes("svcDoc", DOCS(), s?.appears_in || ["board"], DOC_LABEL);
  $("#svcStrength").value = s?.default_strength || "";
  $("#svcWeapon").value = s?.default_weapon || "";
  $("#svcTime").value = s?.default_time || "";
  $("#svcParty").value = s?.party || "";
  $("#svcAliases").value = (s?.aliases || []).join("، ");
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
  const id = $("#svcId").value;
  const body = {
    name: $("#svcName").value, board_label: $("#svcLabel").value,
    kind: $("#svcKind").value, section: $("#svcSection").value,
    standing: $("#svcStanding").checked,
    shifts: readChecks("svcShift"), appears_in: readChecks("svcDoc"),
    default_strength: $("#svcStrength").value, default_weapon: $("#svcWeapon").value,
    default_time: $("#svcTime").value, party: $("#svcParty").value,
    aliases: $("#svcAliases").value.split(/[،,]/).map(x => x.trim()).filter(Boolean),
  };
  const out = id
    ? await api(`/api/services/${encodeURIComponent(id)}`, jsonReq("PATCH", body))
    : await api("/api/services", jsonReq("POST", body));
  if (!out) return;
  closeModal("svcModal"); showToast(id ? "تم تعديل الخدمة" : "تمت إضافة الخدمة"); load();
};
$("#svcSearch").oninput = renderCatalog;
$("#svcKindFilter").onchange = renderCatalog;
$("#svcSectionFilter").onchange = renderCatalog;
$("#addSvcBtn").onclick = () => openSvc(null);

async function load() {
  const d = await bootstrap();
  if (!d) return;
  SERVICES = d.services || [];
  fillSelect($("#svcKindFilter"), [["", "كل التصنيفات"], ...KINDS().map(x => [x, x])], true);
  fillSelect($("#svcSectionFilter"), [["", "كل الأقسام"], ...SECTIONS().map(x => [x, x])], true);
  renderCatalog();
}
load();
