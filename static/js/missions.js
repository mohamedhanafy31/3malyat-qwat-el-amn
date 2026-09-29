/* المأموريات — كيان له دورة حياة (مخططة/بدأت/عادت/أغلقت/ألغيت)،
   مختلف عن الخدمة المتكررة اللي بتتحط على اليومية التفصيلية كل يوم. */
let MISSIONS = [], OFFICERS = [], STATUSES = [];

const STATUS_CLS = {"مخططة": "w", "بدأت": "on", "عادت": "h", "أغلقت": "done", "ألغيت": "err"};
const nameOf = p => `${p.role ? p.role + "/ " : ""}${p.name}`;

function missionRow(m) {
  const members = m.members.map(p => `<span class="chip m">${esc(nameOf(p))}</span>`).join(" ")
    || "<span class='muted'>—</span>";
  return `<tr>
    <td class="name">${esc(m.name)}${m.note ? `<div class="sub">${esc(m.note)}</div>` : ""}</td>
    <td class="wrap">${members}</td>
    <td>${m.start ? fmt(m.start) : "<span class='muted'>—</span>"}</td>
    <td><span class="chip ${STATUS_CLS[m.status] || "w"}">${esc(m.status)}</span></td>
    <td><div class="actions">
      <button class="mini" data-action="openMission" data-id="${esc(m.id)}">تعديل</button>
      <button class="mini bad" data-action="deleteMission" data-id="${esc(m.id)}"
        data-extra="${dataAttr({name: m.name})}">حذف</button>
    </div></td>
  </tr>`;
}

function render() {
  $("#missionsWrap").innerHTML = tableBlock(
    ["المأمورية", "المشاركين", "تاريخ البداية", "الحالة", "الإجراء"],
    MISSIONS.map(missionRow), `عدد المأموريات: ${MISSIONS.length}`, "لا توجد مأموريات.");
}

async function loadList(status) {
  const q = status ? `?status=${encodeURIComponent(status)}` : "";
  const d = await api(`/api/missions${q}`);
  if (!d) return;
  MISSIONS = d.missions; STATUSES = d.statuses;
  fillSelect($("#msnStatusFilter"), [["", "كل الحالات"], ...STATUSES.map(s => [s, s])], true);
  render();
}
$("#msnStatusFilter").onchange = () => loadList($("#msnStatusFilter").value);

function fillMulti(el, people, chosen) {
  el.innerHTML = people.map(p =>
    `<option value="${esc(p.id)}" ${chosen.includes(p.id) ? "selected" : ""}>${esc(nameOf(p))}</option>`).join("");
}
const readMulti = el => [...el.selectedOptions].map(o => o.value);

function openMission(id) {
  const m = id ? MISSIONS.find(x => x.id === id) : null;
  $("#msnId").value = id || "";
  $("#missionTitle").textContent = m ? "تعديل مأمورية" : "مأمورية جديدة";
  $("#msnName").value = m?.name || "";
  fillSelect($("#msnStatus"), STATUSES.map(s => [s, s]));
  $("#msnStatus").value = m?.status || STATUSES[0] || "";
  $("#msnStart").value = m?.start || "";
  fillMulti($("#msnMembers"), OFFICERS, (m?.members || []).map(p => p.id));
  $("#msnNote").value = m?.note || "";
  openModal("missionModal");
}
ACTIONS.openMission = id => openMission(id || null);
ACTIONS.deleteMission = async (id, extra) => {
  if (!(await confirmDialog({
    title: "حذف المأمورية",
    body: `ستُحذف مأمورية «${extra.name}» نهائيًا ولا يمكن التراجع عن ذلك.`,
    confirmLabel: "حذف المأمورية",
    danger: true,
  }))) return;
  if (await api(`/api/missions/${encodeURIComponent(id)}`, {method: "DELETE"})) {
    showToast("تم الحذف"); loadList($("#msnStatusFilter").value);
  }
};
$("#addMissionBtn").onclick = () => openMission(null);

$("#missionForm").onsubmit = async e => {
  e.preventDefault();
  const body = {
    name: $("#msnName").value.trim(),
    status: $("#msnStatus").value,
    start: $("#msnStart").value,
    member_ids: readMulti($("#msnMembers")),
    note: $("#msnNote").value.trim(),
  };
  const id = $("#msnId").value;
  const out = id
    ? await api(`/api/missions/${encodeURIComponent(id)}`, jsonReq("PATCH", body))
    : await api("/api/missions", jsonReq("POST", body));
  if (!out) return;
  closeModal("missionModal", true); showToast(id ? "تم الحفظ" : "تمت الإضافة");
  loadList($("#msnStatusFilter").value);
};

async function load() {
  const d = await bootstrap();
  if (!d) return;
  OFFICERS = d.officer_index || [];
  loadList("");
}
load();
