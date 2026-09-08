/* نموذج تسجيل/تعديل الراحة — مشترك بين صفحة الضباط وصفحة الراحات.
   بيتحمّل قبل ملف الصفحة، والصفحة بتغذّيه بقايمة الأشخاص عبر setLeavePeople. */
let LEAVE_PEOPLE = [];
let LEAVE_LOOKUP = null;   // الصفحة بتحدد إزاي تلاقي سجل راحة بالـid

function setLeavePeople(people) { LEAVE_PEOPLE = people || [] }
function setLeaveLookup(fn) { LEAVE_LOOKUP = fn }

/* WEEKDAYS بيبدأ بالسبت، وgetDay بيبدأ بالأحد */
const weekdayIndex = name => { const i = WEEKDAYS().indexOf(name); return i < 0 ? -1 : (i + 6) % 7 };
function nextWeekday(name, from) {
  const target = weekdayIndex(name); if (target < 0) return null;
  const d = new Date(from + "T12:00:00");
  let diff = (target - d.getDay() + 7) % 7;
  if (diff === 0) diff = 7;                    // الراحة الجاية مش النهاردة
  d.setDate(d.getDate() + diff); return iso(d);
}

function openLeave(leaveId, personId, personHint) {
  const lv = leaveId && LEAVE_LOOKUP ? LEAVE_LOOKUP(leaveId) : null;
  $("#leaveId").value = leaveId || "";
  $("#leaveModalTitle").textContent = lv ? "تعديل الراحة" : "تسجيل راحة";
  fillSelect($("#lvPerson"), LEAVE_PEOPLE.map(p => [p.id, `${p.name} — ${p.role}`]));
  fillSelect($("#lvType"), LEAVE_TYPES().map(x => [x, x]));

  const pid = lv ? lv.person_id : personId;
  if (pid) $("#lvPerson").value = pid;
  const p = personHint || LEAVE_PEOPLE.find(x => x.id === pid);

  $("#lvNote").value = lv?.note || "";
  $("#lvType").value = lv ? lv.type
    : (p?.rest_system && p.rest_system !== "—" ? p.rest_system : "راحة");
  if (lv) {
    $("#lvStart").value = lv.start; $("#lvEnd").value = lv.end;
  } else {
    // للراحة الأسبوعية ابدأ من أقرب يوم راحة، وطبّق المدة القياسية
    const w = (p?.rest_system === "أسبوعية" && p.rest_day) ? nextWeekday(p.rest_day, curDate()) : null;
    $("#lvStart").value = w || curDate();
    $("#lvEnd").value = $("#lvStart").value;
    applyDuration();
  }
  updateHint(); openModal("leaveModal");
}

/* المدة القياسية: شهرية 7 أيام، نصف شهرية 3، أسبوعية يوم واحد */
function applyDuration() {
  const n = DURATIONS()[$("#lvType").value], s = $("#lvStart").value;
  if (!n || !s) return false;
  $("#lvEnd").value = addDays(s, n - 1);
  return true;
}
function updateHint() {
  const s = $("#lvStart").value, e = $("#lvEnd").value, t = $("#lvType").value;
  if (!s || !e || e < s) { $("#lvHint").textContent = ""; return }
  const std = DURATIONS()[t], n = days(s, e);
  let msg = `المدة ${n} يوم — العودة يوم ${dayName(addDays(e, 1))} ${fmt(addDays(e, 1))}`;
  msg += ` • التقصيرة يوم ${dayName(addDays(s, -1))} ${fmt(addDays(s, -1))}`;
  if (std && n !== std) msg += ` ⚠ المدة القياسية لـ«${t}» ${std} أيام`;
  $("#lvHint").textContent = msg;
}

$("#lvStart").oninput = () => {
  if (!applyDuration() && $("#lvEnd").value < $("#lvStart").value) $("#lvEnd").value = $("#lvStart").value;
  updateHint();
};
$("#lvEnd").oninput = updateHint;
$("#lvType").onchange = () => { applyDuration(); updateHint() };
$("#lvPerson").onchange = () => {
  const p = LEAVE_PEOPLE.find(x => x.id === $("#lvPerson").value);
  if (p?.rest_system && p.rest_system !== "—" && !$("#leaveId").value) {
    $("#lvType").value = p.rest_system;
    if (p.rest_system === "أسبوعية" && p.rest_day) {
      const w = nextWeekday(p.rest_day, curDate());
      if (w) $("#lvStart").value = w;
    }
    applyDuration(); updateHint();
  }
};
$("#leaveForm").onsubmit = async e => {
  e.preventDefault();
  const id = $("#leaveId").value;
  const body = {person_id: $("#lvPerson").value, type: $("#lvType").value,
    start: $("#lvStart").value, end: $("#lvEnd").value, note: $("#lvNote").value};
  const out = id
    ? await api(`/api/leaves/${encodeURIComponent(id)}`, jsonReq("PATCH", body))
    : await api("/api/leaves", jsonReq("POST", body));
  if (!out) return;
  closeModal("leaveModal"); showToast(id ? "تم تعديل الراحة" : "تم تسجيل الراحة"); load();
};
