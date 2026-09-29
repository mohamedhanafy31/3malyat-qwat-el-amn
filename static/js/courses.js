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
/* ألوان تصنيفية مستقلة، و«أخرى» تبقى محايدة لأنها غير مصنفة. */
const KIND_CHIP_CLS = {"تأهيلية": "cat1", "تخصصية": "cat2", "قادة": "cat3", "تدريبية": "cat4", "أخرى": "done"};
const kindChipCls = k => KIND_CHIP_CLS[k] || "done";

/* يوم/شهر مختصر بالأرقام بدل "١٤ أغسطس ٢٠٢٦" — الاسم الكامل للشهر كان
   بياخد مساحة الكرت الضيق كله لما يتكرر مرتين (من/إلى) جنب بعض. */
const shortDate = iso => {
  if (!iso) return "";
  const [, m, d] = iso.split("-");
  return `${d}/${m}`;
};

function termRosterRow(t) {
  const note = t.note || t.source || "";
  const hasPeriod = t.start && t.end;
  return `<div class="roster-row">
    <div class="roster-top">
      <div class="roster-who">
        <button class="linkish roster-name" data-action="openDetail" data-id="${esc(t.id)}"
          >${esc(t.officer_name)}</button>
        <span class="roster-role">${esc(t.officer_role)}</span>
      </div>
      <div class="roster-meta">
        ${hasPeriod
          ? `<span class="roster-period num">${shortDate(t.start)} – ${shortDate(t.end)}</span>
             <span class="chip w">${t.days} يوم</span>`
          : `<span class="roster-period muted">بدون تاريخ</span>`}
        <div class="roster-actions">
          <button class="mini" data-action="openTerm" data-id="${esc(t.id)}"
            title="تعديل الالتحاق">تعديل</button>
          <button class="mini bad" data-action="deleteTerm" data-id="${esc(t.id)}"
            data-extra="${dataAttr({name: t.officer_name})}" title="حذف الالتحاق">حذف</button>
        </div>
      </div>
    </div>
    ${note ? `<div class="roster-note">${esc(note)}</div>` : ""}
  </div>`;
}


/* ---------- حسب الضابط ---------- */

function officerRow(o) {
  const chips = o.courses.length
    ? o.courses.map(termChip).join(" ")
    : `<span class="muted">لسه ماخدش فرقة</span>`;
  return `<tr class="${o.count ? "" : "dim"}">
    <td class="name">${esc(o.name)}<div class="sub">${esc(o.role)}</div></td>
    <td><span class="badge">${esc(o.role)}</span></td>
    <td class="wrap">${esc(o.post) || "<span class='muted'>—</span>"}</td>
    <td>${o.count ? `<b>${o.count}</b>` : "<span class='muted'>0</span>"}</td>
    <td>${o.days ? `<span class="chip w">${o.days} يوم</span>` : "<span class='muted'>—</span>"}</td>
    <td class="wrap chip-cell">${chips}</td>
    <td><div class="actions">
      <button class="mini" data-action="openTerm"
        data-extra="${dataAttr({officer_id: o.id})}">${icon("plus")} فرقة</button>
    </div></td></tr>`;
}

/* ---------- العرض ---------- */
const OFFICER_COURSE_COLS = {
  name:  { label: "الضابط",            fn: o => o.name,                type: "text" },
  role:  { label: "الرتبة",            fn: o => rankIndex(o.role),     type: "num"  },
  post:  { label: "العمل المسند إليه", fn: o => o.post || "",          type: "text" },
  count: { label: "عدد الفرق",         fn: o => o.count,               type: "num"  },
  days:  { label: "إجمالي الأيام",     fn: o => o.days || 0,           type: "num"  },
};

function courseCard(c) {
  const body = c.terms.length
    ? `<div class="course-roster">${c.terms.map(termRosterRow).join("")}</div>`
    : `<div class="mempty">مفيش التحاقات مسجّلة لسه</div>`;
  return `<div class="course-card" data-kind="${esc(c.kind || "")}">
    <div class="course-head">
      <div class="course-head-main">
        <h3 class="course-name">${esc(c.name)}</h3>
        <div class="course-meta">
          <span class="chip ${kindChipCls(c.kind)}">${esc(c.kind || "بدون تصنيف")}</span>
          ${c.place ? `<span class="course-place">${esc(c.place)}</span>` : ""}
        </div>
      </div>
      <span class="course-count">${c.officers}<i>ضابط</i></span>
    </div>
    ${c.note ? `<p class="hint course-hint">${esc(c.note)}</p>` : ""}
    <div class="course-bar">
      <button class="mini" data-action="openTerm"
        data-extra="${dataAttr({course_id: c.id})}">${icon("plus")} التحاق</button>
      <div class="actions">
        <button class="mini" data-action="openCourse" data-id="${esc(c.id)}"
          title="تعديل بيانات الفرقة">تعديل</button>
        <button class="mini bad" data-action="deleteCourse" data-id="${esc(c.id)}"
          data-extra="${dataAttr({name: c.name})}" title="حذف الفرقة">حذف</button>
      </div>
    </div>
    ${body}</div>`;
}

/* ---------- الفلترة والإحصائيات — مشتركة بين العرض والكروت الإحصائية ---------- */
function filteredCourses() {
  const q = $("#crsSearch").value.trim();
  const kindF = $("#crsKindFilter")?.value || "";
  let list = COURSES;
  if (q) list = list.filter(c => arIncludes(c.name, q) || arIncludes(c.place, q)
      || c.terms.some(t => arIncludes(t.officer_name, q)));
  if (kindF === "__none") list = list.filter(c => !c.kind);
  else if (kindF) list = list.filter(c => c.kind === kindF);
  // الأكتر ضباطًا أولًا — فرقة فيها 6 ضباط أهم تشغيليًا من فرقة فيها واحد،
  // ومفيش ترتيب أصلي ذو معنى أصلًا (البيانات جاية بترتيب الاستيراد من الأرشيف).
  return [...list].sort((a, b) => (b.officers - a.officers) || a.name.localeCompare(b.name, "ar"));
}
function filteredOfficers() {
  const q = $("#crsSearch").value.trim();
  return q
    ? BY_OFFICER.filter(o => arIncludes(o.name, q) || o.courses.some(c => arIncludes(c.course_name, q)))
    : BY_OFFICER;
}

function renderCrsStats() {
  const box = $("#crsStats"); if (!box) return;
  if (VIEW === "course") {
    const list = filteredCourses();
    const termsCount = list.reduce((n, c) => n + c.terms.length, 0);
    const officerIds = new Set();
    list.forEach(c => c.terms.forEach(t => officerIds.add(t.officer_id)));
    const noKind = list.filter(c => !c.kind).length;
    box.innerHTML = `
      <div class="stat"><span>الفرق</span><strong>${list.length}</strong></div>
      <div class="stat"><span>الالتحاقات</span><strong>${termsCount}</strong></div>
      <div class="stat"><span>ضباط شاركوا</span><strong>${officerIds.size}</strong></div>
      <div class="stat ${noKind ? "stat-accent-orange" : ""}"><span>فرق بلا تصنيف</span><strong>${noKind}</strong></div>`;
    return;
  }
  const list = filteredOfficers();
  const withCourses = list.filter(o => o.count).length;
  const totalDays = list.reduce((n, o) => n + o.days, 0);
  box.innerHTML = `
    <div class="stat"><span>الضباط</span><strong>${list.length}</strong></div>
    <div class="stat"><span>خدوا فرق</span><strong>${withCourses}</strong></div>
    <div class="stat"><span>إجمالي أيام التدريب</span><strong>${totalDays}</strong></div>`;
}

function render() {
  renderCrsStats();
  if (VIEW === "course") {
    const list = filteredCourses();
    const emptyMsg = COURSES.length
      ? "مفيش فرق مطابقة للبحث أو الفلتر الحالي."
      : "مفيش فرق مسجّلة — اضغط «فرقة جديدة» فوق عشان تبدأ.";
    $("#coursesWrap").innerHTML = list.length
      ? `<div class="courses-grid">${list.map(courseCard).join("")}</div>`
      : `<div class="empty">${emptyMsg}</div>`;
    return;
  }
  const list = filteredOfficers();
  const withCourses = list.filter(o => o.count).length;
  $("#coursesWrap").innerHTML = sortableTableBlock(
    "coursesWrap", OFFICER_COURSE_COLS, list, officerRow,
    ["الفرق اللي خدها", "الإجراء"],
    `${withCourses} من ${list.length} ضابط خدوا فرق`,
    "مفيش ضباط.", render);
}


$$("#viewTabs .vtab").forEach(btn => btn.onclick = () => {
  VIEW = btn.dataset.view;
  $$("#viewTabs .vtab").forEach(b => b.classList.toggle("active", b === btn));
  $("#crsKindFilter")?.classList.toggle("hidden", VIEW !== "course");
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
    // شرط الوجود هنا مش بس دفاعي — كتير من التحاقات الأرشيف مالهاش تاريخ
    // بداية/نهاية مسجّل أصلًا، فسطر "من يوم: - -" كان هيبان في كل مرة
    // من غير أي معلومة حقيقية فيه.
    line("من يوم", t.start ? `${dayName(t.start)} ${fmt(t.start)}` : ""),
    line("إلى يوم", t.end ? `${dayName(t.end)} ${fmt(t.end)}` : ""),
    line("المدة", t.days ? `${t.days} يوم` : ""),
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
$("#crsSearch").oninput = debounce(render);
$("#crsKindFilter").onchange = render;

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
