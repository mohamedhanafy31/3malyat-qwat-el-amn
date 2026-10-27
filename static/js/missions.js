/* كشف المأموريات والتراحيل اليومي — عرض مباشر للخدمات المعلّمة في اليومية. */
let MISSION_DAY = "", MISSION_ROWS = [];

const missionPersonName = person => `${person.role ? person.role + "/ " : ""}${person.name || "غير مسجل"}`;

function missionPeople(row) {
  const officers = (row.officers || []).map(person => `<span class="chip m">${esc(missionPersonName(person))}</span>`).join(" ");
  const personnel = (row.personnel || []).map(person => `<span class="chip h">${esc(missionPersonName(person))}</span>`).join(" ");
  return [officers, personnel].filter(Boolean).join(" ")
    || (row.source_manning ? `<span class="source-roster-text">${esc(row.source_manning)}</span>` : "")
    || `<span class="muted">لم يُعيَّن قائم بالخدمة</span>`;
}

function missionConscripts(row) {
  const slots = (row.conscripts || []).map(slot => `<span class="chip w">${esc(slot.class || "مجند")}${slot.count ? ` ×${Number(slot.count)}` : ""}</span>`).join(" ");
  const total = row.conscript_count ? `<span class="chip w">${esc(countLabel(row.conscript_count, "مجند"))}</span>` : "";
  return [slots, total].filter(Boolean).join(" ");
}

const missionFact = (label, value) => value ? `<div><span>${esc(label)}</span><strong>${esc(value)}</strong></div>` : "";

function missionCard(row) {
  const conscripts = missionConscripts(row);
  return `<article class="mission-service-card">
    <div class="mission-card-head"><div><span class="mission-section">${esc(row.section || "خدمات اليوم")}</span><h4>${esc(row.name)}</h4></div>
      ${row.shift ? `<span class="mission-shift">${esc(row.shift)}</span>` : ""}</div>
    <div class="mission-staff"><span>القائمون بها</span><div>${missionPeople(row)}</div></div>
    ${conscripts ? `<div class="mission-conscripts"><span>المجندون</span><div>${conscripts}</div></div>` : ""}
    <div class="mission-facts">${missionFact("الانتظام", row.time)}${missionFact("الجهة", row.party)}${missionFact("التسليح", row.weapon)}</div>
    <div class="mission-card-actions">
      <button type="button" class="mini" data-action="editMission" data-id="${esc(row.id)}">تعديل التصنيف</button>
      ${row.note ? `<button type="button" class="mini mission-note-btn" data-action="showMissionNote" data-id="${esc(row.id)}">ملاحظات</button>` : ""}
    </div>
  </article>`;
}

function missionEmpty(kind) {
  return `<div class="mission-empty">${icon("inbox")}<strong>لا توجد تحركات ${esc(kind)} في هذا اليوم</strong>
    <span>علِّم الخدمة من اليومية التفصيلية بخيار «مأمورية / ترحيلة» لتظهر هنا.</span></div>`;
}

function renderMissionGroup(target, rows, kind) {
  $(target).innerHTML = rows.length ? rows.map(missionCard).join("") : missionEmpty(kind);
}

async function loadMissionDay(day) {
  const data = await api(`/api/missions/day/${encodeURIComponent(day)}`);
  if (!data) return;
  MISSION_DAY = data.date;
  MISSION_ROWS = [...data.external, ...data.internal];
  $("#missionDay").value = MISSION_DAY;
  setPageDay(MISSION_DAY);
  $("#missionDayLabel").textContent = `${dayName(MISSION_DAY)} ${fmt(MISSION_DAY)} — الخدمات المحددة من اليومية التفصيلية`;
  $("#missionTotal").textContent = data.counts.total;
  $("#missionExternalCount").textContent = data.counts.external;
  $("#missionInternalCount").textContent = data.counts.internal;
  $("#externalBadge").textContent = data.counts.external;
  $("#internalBadge").textContent = data.counts.internal;
  renderMissionGroup("#externalMissions", data.external, "خارجية");
  renderMissionGroup("#internalMissions", data.internal, "داخلية");
}

ACTIONS.showMissionNote = id => {
  const row = MISSION_ROWS.find(item => item.id === id);
  if (!row?.note) return;
  $("#missionNoteTitle").textContent = `ملاحظات — ${row.name}`;
  $("#missionNoteBody").textContent = row.note;
  openModal("missionNoteModal");
};

/* تعديل التصنيف (داخلية / خارجية) على نفس تكليف اليومية التفصيلية — مفيش سجل
   موازي: الحفظ بـ PATCH /api/assignments، والباقي (الأشخاص، الفترة، الملاحظات…)
   مابيتبعتش فبيفضل زي ما هو. */
ACTIONS.editMission = id => {
  const row = MISSION_ROWS.find(item => item.id === id);
  if (!row) { showToast("الخدمة لم تعد موجودة — تم تحديث الكشف", true); loadMissionDay(MISSION_DAY || curDate()); return; }
  $("#missionEditId").value = row.id;
  $("#missionEditDay").value = MISSION_DAY;
  $("#missionEditTitle").textContent = `تعديل تصنيف: ${row.name}`;
  $("#missionEditKind").value = row.kind === "داخلية" ? "داخلية" : "خارجية";
  openModal("missionEditModal");
};

$("#missionEditForm").onsubmit = async event => {
  event.preventDefault();
  const id = $("#missionEditId").value, day = $("#missionEditDay").value;
  const kind = $("#missionEditKind").value;
  if (!id || !day || !["داخلية", "خارجية"].includes(kind)) { showToast("اختر تصنيفًا صحيحًا", true); return; }
  const row = MISSION_ROWS.find(item => item.id === id);
  if (row && row.kind === kind) { closeModal("missionEditModal", true); return; }
  const out = await api(`/api/assignments/${encodeURIComponent(day)}/${encodeURIComponent(id)}`,
    jsonReq("PATCH", {kind}));
  if (!out) { await loadMissionDay(day); return; }   // الخطأ ظهر للمستخدم؛ نعيد التحميل لو الحالة تغيّرت
  closeModal("missionEditModal", true);
  showToast(`تم نقل الخدمة إلى «${kind}»`);
  loadMissionDay(day);
};

$("#missionDay").addEventListener("change", event => { if (event.target.value) loadMissionDay(event.target.value); });
$("#missionPrev").onclick = () => loadMissionDay(addDays(MISSION_DAY || curDate(), -1));
$("#missionNext").onclick = () => loadMissionDay(addDays(MISSION_DAY || curDate(), 1));

async function load() {
  const data = await bootstrap();
  if (!data) return;
  loadMissionDay(curDate());
}
load();
