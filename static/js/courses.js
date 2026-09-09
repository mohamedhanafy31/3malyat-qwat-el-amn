/* فرق الضباط — الفرقة نفسها والتحاق الضباط بيها. */
let COURSES = [], OFFICERS = [];

const KINDS_C = () => ["", "تأهيلية", "تخصصية", "قادة", "تدريبية", "أخرى"];
const spanDays = (a, b) => Math.round((new Date(b) - new Date(a)) / 864e5) + 1;

function termRow(t) {
  return `<tr>
    <td class="name">${esc(t.officer_name)}<div class="sub">${esc(t.officer_role)}</div></td>
    <td>${fmt(t.start)}</td><td>${fmt(t.end)}</td>
    <td><span class="chip w">${spanDays(t.start, t.end)} يوم</span></td>
    <td class="wrap">${esc(t.note || t.source) || "<span class='muted'>—</span>"}</td>
    <td><div class="actions">
      <button class="mini" data-action="openTerm" data-id="${esc(t.id)}">تعديل</button>
      <button class="mini bad" data-action="deleteTerm" data-id="${esc(t.id)}"
        data-extra="${dataAttr({name: t.officer_name})}">حذف</button>
    </div></td></tr>`;
}

function courseCard(c) {
  const body = c.terms.length
    ? mtable(["الضابط", "من", "إلى", "المدة", "ملاحظات", "الإجراء"], c.terms.map(termRow))
    : `<div class="mempty">مفيش التحاقات مسجّلة</div>`;
  const meta = [c.kind, c.place].filter(Boolean).map(x => `<span class="chip w">${esc(x)}</span>`).join(" ");
  return `<div class="mcard">
    <h3>${esc(c.name)}<span class="mcount">${c.officers} ضابط</span>
      ${meta}
      <button class="mini" data-action="openCourse" data-id="${esc(c.id)}">تعديل</button>
      <button class="mini bad" data-action="deleteCourse" data-id="${esc(c.id)}"
        data-extra="${dataAttr({name: c.name})}">حذف</button>
      <button class="mini ok" data-action="openTerm"
        data-extra="${dataAttr({course_id: c.id})}">＋ التحاق</button></h3>
    ${c.note ? `<p class="hint" style="margin:10px 16px 0">${esc(c.note)}</p>` : ""}
    ${body}</div>`;
}

function render() {
  const q = $("#crsSearch").value.trim();
  const list = q
    ? COURSES.filter(c => c.name.includes(q) || c.place.includes(q)
        || c.terms.some(t => t.officer_name.includes(q)))
    : COURSES;
  $("#crsCount").textContent =
    `${list.length} فرقة · ${list.reduce((n, c) => n + c.terms.length, 0)} التحاق`;
  $("#coursesWrap").innerHTML = list.length
    ? `<div class="match-grid">${list.map(courseCard).join("")}</div>`
    : `<div class="empty">مفيش فرق مسجّلة — اضغط «فرقة جديدة».</div>`;
}

/* ---------- الفرقة ---------- */
function openCourse(id) {
  const c = id ? COURSES.find(x => x.id === id) : null;
  $("#crsId").value = id || "";
  $("#courseTitle").textContent = c ? "تعديل فرقة" : "فرقة جديدة";
  fillSelect($("#crsKind"), KINDS_C().map(x => [x, x || "— بدون —"]));
  $("#crsName").value = c?.name || "";
  $("#crsKind").value = c?.kind || "";
  $("#crsPlace").value = c?.place || "";
  $("#crsNote").value = c?.note || "";
  openModal("courseModal");
}
ACTIONS.openCourse = id => openCourse(id);
ACTIONS.deleteCourse = async (id, extra) => {
  if (!confirm(`حذف فرقة «${extra.name}»؟`)) return;
  if (await api(`/api/courses/${encodeURIComponent(id)}`, {method: "DELETE"})) {
    showToast("تم الحذف"); load();
  }
};
$("#addCrsBtn").onclick = () => openCourse(null);
$("#courseForm").onsubmit = async e => {
  e.preventDefault();
  const id = $("#crsId").value;
  const body = {name: $("#crsName").value, kind: $("#crsKind").value,
                place: $("#crsPlace").value, note: $("#crsNote").value};
  const out = id
    ? await api(`/api/courses/${encodeURIComponent(id)}`, jsonReq("PATCH", body))
    : await api("/api/courses", jsonReq("POST", body));
  if (!out) return;
  closeModal("courseModal"); showToast("تم الحفظ"); load();
};

/* ---------- الالتحاق ---------- */
function findTerm(id) {
  for (const c of COURSES) { const t = c.terms.find(x => x.id === id); if (t) return t }
  return null;
}
function openTerm(id, extra) {
  const t = id ? findTerm(id) : null;
  $("#trmId").value = id || "";
  $("#termTitle").textContent = t ? "تعديل التحاق" : "التحاق بفرقة";
  fillSelect($("#trmOfficer"), OFFICERS.map(o => [o.id, `${o.role} / ${o.name}`]));
  fillSelect($("#trmCourse"), COURSES.map(c => [c.id, c.name]));
  $("#trmOfficer").value = t?.officer_id || OFFICERS[0]?.id || "";
  $("#trmCourse").value = t?.course_id || extra?.course_id || COURSES[0]?.id || "";
  $("#trmStart").value = t?.start || curDate();
  $("#trmEnd").value = t?.end || curDate();
  $("#trmNote").value = t?.note || "";
  openModal("termModal");
}
ACTIONS.openTerm = (id, extra) => openTerm(id, extra);
ACTIONS.deleteTerm = async (id, extra) => {
  if (!confirm(`حذف التحاق «${extra.name}»؟`)) return;
  if (await api(`/api/course-terms/${encodeURIComponent(id)}`, {method: "DELETE"})) {
    showToast("تم الحذف"); load();
  }
};
$("#addTermBtn").onclick = () => {
  if (!COURSES.length) { showToast("اعمل فرقة الأول", true); return }
  openTerm(null);
};
$("#termForm").onsubmit = async e => {
  e.preventDefault();
  const id = $("#trmId").value;
  const body = {officer_id: $("#trmOfficer").value, course_id: $("#trmCourse").value,
                start: $("#trmStart").value, end: $("#trmEnd").value,
                note: $("#trmNote").value};
  const out = id
    ? await api(`/api/course-terms/${encodeURIComponent(id)}`, jsonReq("PATCH", body))
    : await api("/api/course-terms", jsonReq("POST", body));
  if (!out) return;
  closeModal("termModal"); showToast("تم الحفظ"); load();
};
$("#crsSearch").oninput = render;

async function load() {
  const d = await bootstrap();
  if (!d) return;
  OFFICERS = d.officer_index || [];
  const out = await api("/api/courses");
  if (!out) return;
  COURSES = out.courses || [];
  const el = $("#navCourses"); if (el) el.textContent = COURSES.length;
  render();
}
load();
