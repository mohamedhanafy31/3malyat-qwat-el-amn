/* سجل الراحات والإجازات */
let LEAVES = [], PEOPLE = [], OFFICER_IDS = new Set(), LEAVE_TAB = "all";

const personById = id => PEOPLE.find(p => p.id === id);
// أسبوعية/نصف شهرية/شهرية الأول بالترتيب ده، والباقي بعدهم — المهم إن كل
// نوع يتجمّع لوحده مش يتوزّع بين الرتب
const leaveTypeIndex = t => { const i = LEAVE_TYPES().indexOf(t); return i < 0 ? LEAVE_TYPES().length : i };
const commandPriority = id => {
  const roles = COMMAND_ROLES(), role = roles.find(r => (META.command || {})[r] === id);
  const i = roles.indexOf(role); return i < 0 ? roles.length : i;
};

function renderStats() {
  const t = curDate();
  const cur = LEAVES.filter(l => l.start <= t && t <= l.end).length;
  const up = LEAVES.filter(l => l.start > t).length;
  $("#leaveStats").innerHTML = `
    <div class="stat"><span>جارية الآن</span><strong>${cur}</strong></div>
    <div class="stat"><span>قادمة</span><strong>${up}</strong></div>
    <div class="stat"><span>منتهية</span><strong>${LEAVES.length - cur - up}</strong></div>
    <div class="stat"><span>إجمالي السجلات</span><strong>${LEAVES.length}</strong></div>`;
}

function leaveRow(l, t) {
  const live = l.start <= t && t <= l.end, up = l.start > t;
  const state = live ? `<span class="chip rest">جارية</span>`
    : up ? `<span class="chip soon">قادمة</span>` : `<span class="chip done">منتهية</span>`;
  const p = personById(l.person_id);
  const who = p ? `<span class="badge ${OFFICER_IDS.has(l.person_id) ? "" : "person"}">${esc(p.role)}</span>`
                : '<span class="muted">(محذوف)</span>';
  return `<tr>
    <td class="name">${esc(l.name)}<div class="sub">${who}</div></td>
    <td><span class="chip ${l.type === "شهرية" ? "m" : l.type === "نصف شهرية" ? "h" : "w"}">${esc(l.type)}</span></td>
    <td>${fmt(l.start)}<div class="sub">تقصيرة ${dayName(addDays(l.start, -1))}</div></td>
    <td>${fmt(l.end)}</td>
    <td>${fmt(l.return_date)}</td>
    <td class="num">${days(l.start, l.end)}</td>
    <td>${state}</td>
    <td class="wrap">${esc(l.note) || "<span class='muted'>—</span>"}</td>
    <td><div class="actions">
      <button class="mini" data-action="openLeaveEdit" data-id="${esc(l.id)}">تعديل</button>
      <button class="mini bad" data-action="deleteLeave" data-id="${esc(l.id)}" data-extra="${dataAttr({name: l.name})}">حذف</button>
    </div></td></tr>`;
}

function render() {
  renderStats();
  const t = curDate();
  let rows = [...LEAVES];
  if (LEAVE_TAB === "current") rows = rows.filter(l => l.start <= t && t <= l.end);
  if (LEAVE_TAB === "upcoming") rows = rows.filter(l => l.start > t);
  const q = $("#leaveSearch").value.trim().toLowerCase();
  if (q) rows = rows.filter(l => String(l.name || "").toLowerCase().includes(q));
  const tf = $("#leaveTypeFilter").value;
  if (tf) rows = rows.filter(l => l.type === tf);

  // ترتيب: النوع، وجوّه كل نوع القيادة الأول ثم بالرتبة
  rows.sort((a, b) => {
    const ta = leaveTypeIndex(a.type), tb = leaveTypeIndex(b.type);
    if (ta !== tb) return ta - tb;
    const ca = commandPriority(a.person_id), cb = commandPriority(b.person_id);
    if (ca !== cb) return ca - cb;
    const pa = personById(a.person_id), pb = personById(b.person_id);
    const ra = rankIndex(pa?.role), rb = rankIndex(pb?.role);
    if (ra !== rb) return ra - rb;
    return (pa?.name || a.name).localeCompare(pb?.name || b.name, "ar");
  });

  let lastType = null;
  const body = rows.map(l => {
    const divider = l.type !== lastType
      ? `<tr class="grouprow"><td colspan="9">${esc(l.type)}</td></tr>` : "";
    lastType = l.type;
    return divider + leaveRow(l, t);
  });
  $("#leaveWrap").innerHTML = tableBlock(
    ["الاسم","النوع","من","إلى","العودة","الأيام","الحالة","ملاحظات","الإجراء"],
    body, `عدد النتائج: ${rows.length}`, "لا توجد راحات مسجلة.");
}

ACTIONS.openLeaveEdit = id => openLeave(id);
ACTIONS.deleteLeave = async (id, extra) => {
  if (!confirm(`حذف سجل راحة «${extra.name}»؟`)) return;
  if (await api(`/api/leaves/${encodeURIComponent(id)}`, {method: "DELETE"})) {
    showToast("تم حذف الراحة"); load();
  }
};

$$("[data-lv]").forEach(b => b.onclick = () => {
  $$("[data-lv]").forEach(x => x.classList.remove("active"));
  b.classList.add("active"); LEAVE_TAB = b.dataset.lv; render();
});
$("#leaveSearch").oninput = render;
$("#leaveTypeFilter").onchange = render;
$("#addLeaveBtn").onclick = () => openLeave(null);

async function load() {
  const d = await bootstrap();
  if (!d) return;
  LEAVES = d.leaves || []; PEOPLE = d.people || [];
  OFFICER_IDS = new Set(d.officer_ids || []);
  setLeavePeople(PEOPLE);
  setLeaveLookup(id => LEAVES.find(l => l.id === id));
  fillSelect($("#leaveTypeFilter"), [["", "كل الأنواع"], ...LEAVE_TYPES().map(x => [x, x])], true);
  render();
}
load();
