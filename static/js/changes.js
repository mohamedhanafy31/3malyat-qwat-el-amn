/* سجل التغييرات — مين عدّل إيه وإمتى، بجملة مقروءة مش JSON خام.

   تغييرات اليومية التفصيلية بتتسجّل وقت **تأكيد** اليومية مش وقت الحفظ،
   فالوقت اللي في العمود ده هو لحظة التأكيد، وكل تغييرات نفس التأكيد
   بتحمل نفس اللحظة بالظبط. */
let ENTRIES = [];

const ACTION_LABEL = {
  create: "إضافة", update: "تعديل", delete: "حذف",
  assign: "تكليف", unassign: "رفع تكليف",
  confirm: "تأكيد", close: "قفل يوم", reopen: "فتح استثنائي",
  stop: "إيقاف راحة", cancel: "إلغاء راحة", suspend: "وقف الراحات", lift: "فتح الراحات",
  restore: "رجوع راحة",
  retro: "بأثر رجعي",
};
const ENTITY_LABEL = {
  duty_move: "حركة ضابط/فرد", assignment: "خدمة", day_confirm: "تأكيد يومية",
  day_lock: "قفل يوم", officer_state: "حالة ضابط", leave: "راحة", mission: "مأمورية",
  rest_suspension: "وقف الراحات",
};
/* لون شارة «العملية» بيقول معناها (نفس دلالة الألوان في style.css):
   حذف/إلغاء أحمر، تأكيد أخضر، قفل/فتح/وقف كهرماني، والإضافة والتعديل
   معلومة محايدة. «النوع» شارة محايدة من غير لون. */
const ACTION_CLS = {
  delete: "err", cancel: "err", unassign: "err",
  confirm: "on",
  close: "taq", reopen: "taq", suspend: "taq", lift: "taq", stop: "taq", retro: "taq",
};

/* "2026-09-16T14:30:00" -> "١٦ سبتمبر ٢٠٢٦ — 14:30" */
function stamp(ts) {
  if (!ts) return "—";
  const [d, t] = String(ts).split("T");
  return `${fmt(d)}<div class="sub">${(t || "").slice(0, 5)}</div>`;
}

function diffLine(before, after) {
  if (!before && after) return "<span class='muted'>إضافة جديدة</span>";
  if (before && !after) return "<span class='muted'>حُذف</span>";
  const keys = [...new Set([...Object.keys(before || {}), ...Object.keys(after || {})])];
  const changed = keys.filter(k => JSON.stringify(before?.[k]) !== JSON.stringify(after?.[k]));
  if (!changed.length) return "<span class='muted'>—</span>";
  return changed.map(k =>
    `<div><b>${esc(k)}</b>: ${esc(humanizeDates(JSON.stringify(before?.[k])))} ← ${esc(humanizeDates(JSON.stringify(after?.[k])))}</div>`
  ).join("");
}

function changeRow(e) {
  // السجلات القديمة (قبل ما التسجيل يبقى بجملة جاهزة) مالهاش text — بتتعرض
  // بفرق الحقول الخام زي ما كانت
  const body = e.text ? esc(humanizeDates(e.text))
    : e.entity === "day_lock" ? esc(humanizeDates(`${ACTION_LABEL[e.action] || e.action} ${e.entity_id}`))
    : diffLine(e.before, e.after);
  return `<tr>
    <td class="wrap">${stamp(e.ts)}</td>
    <td>${e.day ? fmt(e.day) : "<span class='muted'>—</span>"}</td>
    <td><span class="badge">${esc(ENTITY_LABEL[e.entity] || e.entity)}</span></td>
    <td><span class="chip ${ACTION_CLS[e.action] || "w"}">${esc(ACTION_LABEL[e.action] || e.action)}</span></td>
    <td class="wrap">${body}</td>
    <td>${esc(e.edited_by) || "<span class='muted'>—</span>"}</td>
  </tr>`;
}

function render() {
  $("#changesWrap").innerHTML = tableBlock(
    ["وقت التسجيل", "اليومية", "النوع", "العملية", "التغيير", "المُعدِّل"],
    ENTRIES.map(changeRow), `عدد السجلات: ${ENTRIES.length}`,
    {title: "لا توجد تغييرات مسجّلة", hint: "تُسجَّل تغييرات اليومية التفصيلية بعد الضغط على «تأكيد اليومية»."},
    "changesWrap", render);
}

async function loadEntries() {
  const q = new URLSearchParams();
  const entity = $("#chgEntityFilter").value;
  const day = $("#chgDayFilter").value;
  if (entity) q.set("entity", entity);
  if (day) q.set("day", day);
  const d = await api(`/api/changes${q.toString() ? "?" + q : ""}`);
  if (!d) return;
  ENTRIES = d.entries;
  render();
}

$("#chgEntityFilter").onchange = loadEntries;
$("#chgDayFilter").onchange = loadEntries;
$("#chgClearDay").onclick = () => { $("#chgDayFilter").value = ""; loadEntries() };

async function load() {
  const d = await bootstrap();
  if (!d) return;
  loadEntries();
}
load();
