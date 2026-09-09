/* فرق الضباط — عرضين على نفس البيانات:
     «حسب الفرقة»  كل فرقة والضباط اللي خدوها
     «حسب الضابط»  كل ضابط والفرق اللي خدها
   والضغط على أي التحاق في العرضين بيفتح نفس نافذة التفاصيل. */
let COURSES = [], BY_OFFICER = [], OFFICERS = [], VIEW = "course";

const KINDS_C = () => ["", "تأهيلية", "تخصصية", "قادة", "تدريبية", "أخرى"];
const termChip = t =>
  `<button class="chip-btn" data-action="openDetail" data-id="${esc(t.id)}">
    ${esc(t.course_name)}<i>${fmt(t.start)}</i></button>`;

/* ---------- حسب الفرقة ---------- */
function termRow(t) {
  return `<tr>
    <td class="name"><button class="linkish" data-action="openDetail" data-id="${esc(t.id)}"
      >${esc(t.officer_name)}</button><div class="sub">${esc(t.officer_role)}</div></td>
    <td>${fmt(t.start)}</td><td>${fmt(t.end)}</td>
    <td>${t.days ? `<span class="chip w">${t.days} يوم</span>` : "<span class='muted'>—</span>"}</td>
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
  const meta = [c.kind, c.place].filter(Boolean)
    .map(x => `<span class="chip w">${esc(x)}</span>`).join(" ");
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

/* ---------- حسب الضابط ---------- */
function officerRow(o) {
  const chips = o.courses.length
    ? o.courses.map(termChip).join(" ")
    : `<span class="muted">لسه ماخدش فرقة</span>`;
  return `<tr class="${o.count ? "" : "dim"}">
    <td class="name">${esc(o.name)}<div class="sub">${esc(o.role)}</div></td>
    <td class="wrap">${esc(o.post) || "<span class='muted'>—</span>"}</td>
    <td>${o.count ? `<b>${o.count}</b>` : "<span class='muted'>0</span>"}</td>
    <td>${o.days ? `<span class="chip w">${o.days} يوم</span>` : "<span class='muted'>—</span>"}</td>
    <td class="wrap chip-cell">${chips}</td>
    <td><div class="actions">
      <button class="mini ok" data-action="openTerm"
        data-extra="${dataAttr({officer_id: o.id})}">＋ فرقة</button>
    </div></td></tr>`;
}

/* ---------- العرض ---------- */
function render() {
  const q = $("#crsSearch").value.trim();
  if (VIEW === "course") {
    const list = q
      ? COURSES.filter(c => c.name.includes(q) || c.place.includes(q)
          || c.terms.some(t => t.officer_name.includes(q)))
      : COURSES;
    $("#crsCount").textContent =
      `${list.length} فرقة · ${list.reduce((n, c) => n + c.terms.length, 0)} التحاق`;
    $("#coursesWrap").innerHTML = list.length
      ? `<div class="match-grid">${list.map(courseCard).join("")}</div>`
      : `<div class="empty">مفيش فرق مسجّلة — اضغط «فرقة جديدة».</div>`;
    return;
  }
  const list = q
    ? BY_OFFICER.filter(o => o.name.includes(q)
        || o.courses.some(c => c.course_name.includes(q)))
    : BY_OFFICER;
  const withCourses = list.filter(o => o.count).length;
  $("#crsCount").textContent = `${list.length} ضابط · ${withCourses} خدوا فرق`;
  $("#coursesWrap").innerHTML = tableBlock(
    ["الضابط", "العمل المسند إليه", "عدد الفرق", "إجمالي الأيام", "الفرق اللي خدها", "الإجراء"],
    list.map(officerRow),
    `${withCourses} من ${list.length} ضابط خدوا فرق`, "مفيش ضباط.");
}

$$("#viewTabs .vtab").forEach(btn => btn.onclick = () => {
  VIEW = btn.dataset.view;
  $$("#viewTabs .vtab").forEach(b => b.classList.toggle("active", b === btn));
  render();
});

/* ---------- تفاصيل الالتحاق ---------- */
function findTerm(id) {
  for (const c of COURSES) { const t = c.terms.find(x => x.id === id); if (t) return t }
  return null;
}
ACTIONS.openDetail = id => {
  const t = findTerm(id); if (!t) return;
  $("#tdTitle").textContent = t.course_name;
  $("#tdWho").textContent =
    `${t.officer_role} / ${t.officer_name}${t.officer_post ? " — " + t.officer_post : ""}`;
  const line = (label, value) => value
    ? `<tr><td class="name">${label}</td><td class="wrap">${esc(value)}</td></tr>` : "";
  $("#tdBody").innerHTML = mtable(["البيان", "القيمة"], [
    line("المكان", t.course_place),
    line("النوع", t.course_kind),
    line("من يوم", `${dayName(t.start)} ${fmt(t.start)}`),
    line("إلى يوم", `${dayName(t.end)} ${fmt(t.end)}`),
    line("المدة", `${t.days} يوم`),
    line("رتبته وقتها", t.officer_role),
    line("ملاحظات", t.note),
    line("ملاحظات الفرقة", t.course_note),
    line("النص الأصلي في اليومية", t.source),
  ].filter(Boolean));
  $("#tdEdit").onclick = () => { closeModal("termDetailModal"); openTerm(id) };
  $("#tdDelete").onclick = () => {
    closeModal("termDetailModal");
    ACTIONS.deleteTerm(id, {name: t.officer_name});
  };
  openModal("termDetailModal");
};

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
function openTerm(id, extra) {
  const t = id ? findTerm(id) : null;
  $("#trmId").value = id || "";
  $("#termTitle").textContent = t ? "تعديل التحاق" : "التحاق بفرقة";
  fillSelect($("#trmOfficer"), OFFICERS.map(o => [o.id, `${o.role} / ${o.name}`]));
  fillSelect($("#trmCourse"), COURSES.map(c => [c.id, c.name]));
  $("#trmOfficer").value = t?.officer_id || extra?.officer_id || OFFICERS[0]?.id || "";
  $("#trmCourse").value = t?.course_id || extra?.course_id || COURSES[0]?.id || "";
  $("#trmStart").value = t?.start || "";
  $("#trmEnd").value = t?.end || "";
  $("#trmNote").value = t?.note || "";
  openModal("termModal");
}
ACTIONS.openTerm = (id, extra) => {
  if (!COURSES.length) { showToast("اعمل فرقة الأول", true); return }
  openTerm(id, extra);
};
ACTIONS.deleteTerm = async (id, extra) => {
  if (!confirm(`حذف التحاق «${extra.name}»؟`)) return;
  if (await api(`/api/course-terms/${encodeURIComponent(id)}`, {method: "DELETE"})) {
    showToast("تم الحذف"); load();
  }
};
$("#addTermBtn").onclick = () => ACTIONS.openTerm(null);
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
  BY_OFFICER = out.officers || [];
  const el = $("#navCourses"); if (el) el.textContent = COURSES.length;
  render();
}
load();
