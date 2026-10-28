/* يومية تشغيل الضباط — جدول الإجمالي وحالة الضابط.
   التكليف بخدمة بقى في اليومية التفصيلية (نفس السجل)، والصفحة دي بتعدّل
   حالة الضابط بس: تقصيرة / انتداب / غياب / مرضي / طارئة، وتشغيل إضافي
   بيتضاف على خدمته التلقائية، وإضافته للعمل بالإدارة في اللوحة.
   «فرقة» بتيجي من التحاق الفرق المسجّل وتفاصيلها بتتعرض تحت الخانة. */
let DUTY = null;

// نفس `backend/status_periods.py`: المستمرة لحد الإنهاء، والباقي لحد يوم محدد
const CONTINUOUS_STATUSES = ["مرضي", "غياب"];
const BOUNDED_STATUSES = ["طارئة", "مأمورية", "انتداب"];
const DETAILED_STATUSES = ["مأمورية", "انتداب"];   // معاهم اسم وتفاصيل

/* سطر مدى الحالة الممتدة: المفتوحة تعرض يوم البداية فقط، والمحددة تعرض المدى. */
function periodSpan(p) {
  return p.end ? `من ${fmt(p.start)} حتى ${fmt(p.end)}` : `من يوم ${fmt(p.start)}`;
}

/* ما يظهر تحت الخانة: «مأمورية: الاسم — التفاصيل — من … حتى …» أو المدى بس */
function periodLine(p) {
  return p.title && p.label ? p.label : periodSpan(p);
}

/* الفرقة: الجملة الرسمية (الاسم + المدة + المكان) ثم النوع والملاحظات لو موجودة */
function courseLine(c) {
  return [c.text, c.kind && `(${c.kind})`, c.term_note, c.course_note].filter(Boolean).join(" — ");
}

window.exportDocxUrl = () => DUTY ? `/api/duty/${DUTY.date}/export.docx` : null;

function renderSummary(s) {
  const cell = v => `<td>${v}</td>`;
  const x = s["خارجية"], dl = s["داخلية"], tb = s["طبية"], kh = s["خوارج"];
  $("#balanceTag").innerHTML = s.balanced
    ? `<span class="chip on">متوازن ${s.counted}/${s["أصل القوة"]}</span>`
    : `<span class="chip taq">غير متوازن ${s.counted}/${s["أصل القوة"]}</span>`;
  /* شريط أرقام مضغوط بدل جدول الإجمالي: خلية «الصافي» كان فيها 25 اسم
     فالصف كان طوله ~680 بكسل والجدول الأساسي بيبدأ تحت حافة الشاشة. الأسماء
     بقت قايمة مطوية تحت الشريط. الجدول الكامل بيفضل مخفي كمصدر للتصدير. */
  const tile = (label, v) => `<div class="sum-tile${v ? "" : " zero"}"><span>${label}</span><b>${v}</b></div>`;
  const group = (title, tiles) => `<div class="sum-group"><h4>${title}</h4><div class="sum-tiles">${tiles}</div></div>`;
  const single = (title, v, cls = "") => `<div class="sum-group single ${cls}"><h4>${title}</h4><b>${v}</b></div>`;
  const externalMorning = x["بحث"]
    ? (x["صباحية"] ? `${x["صباحية"]} + ${x["بحث"]} بحث` : `${x["بحث"]} بحث`)
    : `${x["صباحية"]}`;
  // المعسكر الفرعي سطر تحت أرقام الداخلية زي الورد، مش جزء من رقم الصباحية
  const internalMorning = `${dl["صباحية"]}`;
  const subcampNote = s["معسكر فرعي"] ? `<small class="sum-note">${s["معسكر فرعي"]} معسكر فرعي</small>` : "";
  const outsideOrder = ["تقصيرة", "راحة", "طارئة", "غياب", "مرضي", "فرقة", "انتداب", "مأمورية"];
  outsideOrder.push(...Object.keys(kh).filter(key => !outsideOrder.includes(key)));
  const strip = `<div class="duty-strip">
    ${single("أصل القوة", s["أصل القوة"])}
    ${group("الخدمات الخارجية", tile("صباحية", externalMorning) + tile("ليلية", x["ليلية"]))}
    ${group("الخدمات الداخلية", tile("صباحية", internalMorning) + tile("ليلية", dl["ليلية"]) + subcampNote)}
    ${group("الخدمات الطبية", tile("موجود", tb["موجود"]) + tile("راحة", tb["راحة"]))}
    ${group("الخوارج", outsideOrder.map(k => tile(k, kh[k] || 0)).join(""))}
    ${single("الحراسات المشددة", s["حراسات"])}
    ${single("الصافي", s["صافي"], "key")}
  </div>
  <details class="net-names"><summary>عرض أسماء الصافي (${s.net_names.length})</summary>
    <ol>${s.net_names.map(n => `<li>${esc(n)}</li>`).join("")}</ol></details>`;
  $("#dutySummary").innerHTML = strip + `<div class="table-scroll export-only" hidden><table class="table sum">
   <thead>
    <tr><th rowspan="2">أصل القوة</th><th colspan="2">الخدمات الخارجية</th><th colspan="2">الخدمات الداخلية</th>
        <th colspan="2">الخدمات الطبية</th><th colspan="${outsideOrder.length}">الخوارج</th>
        <th rowspan="2">الحراسات المشددة</th><th rowspan="2">الصافي (${s["صافي"]})</th></tr>
    <tr><th>صباحية</th><th>ليلية</th><th>صباحية</th><th>ليلية</th>
        <th>موجود</th><th>راحة</th>
        ${outsideOrder.map(key => `<th>${esc(key)}</th>`).join("")}</tr>
   </thead>
   <tbody><tr class="sumrow">
     <td><b>${s["أصل القوة"]}</b></td>
     ${cell(externalMorning)}${cell(x["ليلية"])}
     ${cell(internalMorning)}${cell(dl["ليلية"])}
     ${cell(tb["موجود"])}${cell(tb["راحة"])}
     ${outsideOrder.map(key => cell(kh[key] || 0)).join("")}
     ${cell(s["حراسات"])}
     <td class="wrap">${s.net_names.map(esc).join("<br>") || "—"}</td>
   </tr></tbody></table></div>`;
}

/* أقسام جدول الوورد الثلاثة — القسم تابع لوضع الضابط التنظيمي مش لتشغيله */
function sectionRows(rows) {
  const order = META.officer_sections || ["القوة", "الحراسات المشددة", "الخوارج"];
  const out = [];
  for (const section of order) {
    const mine = rows.filter(r => (r.section || order[0]) === section);
    if (!mine.length) continue;
    if (section !== order[0]) {
      out.push(`<tr class="section-row"><td colspan="7">${esc(section)}</td></tr>`);
    }
    out.push(...mine.map(officerRow));
  }
  // أي قسم مش في القايمة يتعرض في الآخر بدل ما يختفي
  out.push(...rows.filter(r => !order.includes(r.section || order[0])).map(officerRow));
  return out;
}

function officerRow(r) {
  const svc = r.services.length
    ? r.services.map(s => `<span class="chip ${KIND_CLS[s.kind] || "w"}">${esc(s.name)}<i>${esc(s.shift)}</i></span>`).join(" ")
    : `<span class="muted">—</span>`;
  const grp = r.leave ? `<span class="chip rest leave-kind-chip">${esc(r.leave.type)}</span><div class="sub">حتى ${fmt(r.leave.end)}</div>`
    : r.group === "صافي" ? `<span class="chip on">صافي</span>`
    : `<span class="chip ${KIND_CLS[r.group] || "done"}">${esc(r.group)}${r.bucket ? " · " + esc(r.bucket) : ""}</span>`
      + (r.status_source === "period" && r.persistent_status
        ? `<div class="sub wrap">${esc(periodLine(r.persistent_status))}</div>` : "")
      + (r.course ? `<div class="sub wrap">${esc(courseLine(r.course))}</div>` : "");
  const gone = r.later_left ? `<span class="chip done" title="خرج من القوة يوم ${fmt(r.later_left)}">خرج ${fmt(r.later_left)}</span>` : "";
  const search = r.search_attached ? ` <span class="chip soon" title="تشغيل من إدارة البحث">بحث</span>` : "";
  return `<tr class="${r.later_left ? "was" : ""}">
    <td class="name">${esc(r.name)}<div class="sub">${esc(r.role)}${search} ${gone}</div></td>
    <td class="phone-col"><span dir="ltr">${esc(fmtPhone(r.phone)) || "—"}</span></td>
    <td class="wrap">${esc(r.post) || "<span class='muted'>—</span>"}</td>
    <td>${svc}${r.taqseera ? ' <span class="chip taq">تقصيرة</span>' : ""}</td>
    <td>${grp}</td>
    <td class="wrap">${esc(r.text) || "<span class='muted'>—</span>"}${r.admin_work ? ' <span class="chip m" title="يظهر كمان في «عمل بالإدارة» في اليومية التفصيلية">+ عمل بالإدارة</span>' : ""}</td>
    <td><button class="mini" data-action="openAssign" data-id="${esc(r.id)}">الحالة</button></td>
  </tr>`;
}

function render() {
  if (!DUTY) { $("#dutyBoard").innerHTML = skeleton("rows", 10); return }
  renderSummary(DUTY.summary);
  const gone = DUTY.rows.filter(r => r.later_left).length;
  $("#dutyBoard").innerHTML = tableBlock(
    ["الضابط", "الهاتف", "العمل المسند إليه", "الخدمات", "الخانة في الإجمالي", "نص التشغيل", "الإجراء"],
    sectionRows(DUTY.rows),
    `قوة اليوم: ${countLabel(DUTY.rows.length, "ضابط")}${gone ? ` — عدد من خرجوا من القوة لاحقًا: ${gone}` : ""}`);
}

ACTIONS.openAssign = id => {
  const row = DUTY.rows.find(r => r.id === id); if (!row) return;
  $("#assignPerson").value = id;
  $("#assignTitle").textContent = `حالة: ${row.name}`;
  $("#assignHint").textContent =
    `يوم ${dayName(DUTY.date)} ${fmt(DUTY.date)} — التكليف بالخدمات من اليومية التفصيلية.`
    + (row.leave ? ` تنبيه: الضابط في ${row.leave.type} حتى ${fmt(row.leave.end)}.` : "");
  const choices = [...(META.officer_statuses || [])];
  // صف أرشيفي بحالة مش متاحة للاختيار («فرقة» يدوية قديمة) بيفضل بقيمته
  // عشان حفظ ملاحظته مايمسحهاش — لكنها مش معروضة لأي ضابط تاني.
  if (row.status && !choices.includes(row.status)) choices.push(row.status);
  fillSelect($("#assignStatus"), [["", "— بدون —"], ...choices.map(x => [x, x])]);
  // الحالة المسجّلة بس — مش الخانة المحسوبة. الضابط بيقع في «خوارج/فرقة»
  // لأن مدى التحاقه بفرقة بيغطي اليوم، من غير ما يكون فيه حالة متكتبة.
  // ملء الحقل من row.bucket كان بيخلي أي حفظ (حتى لو المستخدم داخل يكتب
  // ملاحظة بس) يثبّت «فرقة» كحالة يدوية تفضل بعد ما الفرقة نفسها تتمسح.
  $("#assignStatus").value = row.status || "";
  const period = row.status_source === "period" ? row.persistent_status : null;
  $("#assignStatusEnd").value = period && BOUNDED_STATUSES.includes(period.status) ? (period.end || "") : "";
  $("#assignStatusEnd").min = DUTY.date;
  $("#assignStatusTitle").value = period && DETAILED_STATUSES.includes(period.status) ? (period.title || "") : "";
  $("#assignStatusDetails").value = period && DETAILED_STATUSES.includes(period.status) ? (period.details || "") : "";
  updatePersistentHint();
  $("#assignResearch").classList.toggle("hidden", !row.research);
  $("#assignResearchService").value = row.research_service || "";
  setTimeInputValue($("#assignResearchTime"), row.research_time || "");
  $("#assignMedical").classList.toggle("hidden", !row.medical);
  if (row.medical) {
    const medical = document.querySelector(`input[name="assignMedicalState"][value="${row.medical_state || "عمل"}"]`);
    if (medical) medical.checked = true;
    $("#assignMedicalText").value = row.medical_deputation_text || "";
    $("#assignMedicalHint").textContent = row.medical_state_from
      ? `الحالة سارية من ${fmt(row.medical_state_from)} وتستمر لحد ما تتغيّر.`
      : "الحالة الافتراضية «عمل»، والاختيار يستمر في الأيام التالية لحد ما يتغيّر.";
    updateMedicalFields();
  }
  $("#assignTaq").checked = !!row.taqseera;
  $("#assignExtra").value = row.extra || "";
  // النص القديم الكامل بيظهر بس لو موجود — الأيام الجديدة مفيهاش غير الإضافي
  $("#assignNote").value = row.note || "";
  $("#assignNoteRow").classList.toggle("hidden", !row.note);
  // التقصيرة علامة على تشغيل الضابط وليست «خارج» في اليومية التفصيلية.
  // مدير/وكيل الإدارة يظهران تلقائيًا، وباقي الصافي يمكن نقله لعمل الإدارة
  // صراحةً بعد كتابة نصه التشغيلي.
  const outside = row.group === "خوارج" && row.bucket !== "تقصيرة";
  const automaticAdmin = ["مدير الإدارة", "وكيل الإدارة"].includes(row.command_role);
  const net = row.group === "صافي" || (row.bucket === "تقصيرة" && !row.services.length);
  $("#assignAdmin").checked = !outside && (automaticAdmin || !!row.admin_work);
  $("#assignAdmin").disabled = outside || automaticAdmin;
  $("#assignAdminHint").textContent = outside
    ? "الضابط في الخوارج النهارده — مفيش نص تشغيلي يتضاف"
    : automaticAdmin ? `${row.command_role} — يظهر تلقائيًا في «عمل بالإدارة» ما لم يكن من الخوارج`
    : net ? "الضابط صافي — فعّل الخيار بعد كتابة تشغيله لنقله إلى «عمل بالإدارة»"
    : "النص التشغيلي الكامل (خدمته + الإضافي) يظهر كمان في «عمل بالإدارة» في اليومية التفصيلية، ويفضل في مكان خدمته";
  updateAssignPreview();
  // الضابط في راحة اليوم ده — إيقافها من هنا مباشرة، من غير ما تروح صفحة الراحات
  const lv = row.leave;
  $("#assignRest").classList.toggle("hidden", !lv?.id);
  if (lv?.id) {
    $("#assignRestText").textContent = `في ${lv.type} حتى ${fmt(lv.end)}`;
    $("#assignStopRest").onclick = async () => {
      if(!(await closeModal("assignModal"))) return;
      openStopLeave({id: lv.id, name: row.name, type: lv.type, start: lv.start, end: lv.end},
                    () => loadDay(DUTY.date));
    };
  }
  const persistent = row.persistent_status;
  $("#assignPersistent").classList.toggle("hidden", !persistent?.id);
  if (persistent?.id) {
    const bounded = persistent.kind === "bounded";
    $("#assignPersistentTitle").textContent = bounded ? "حالة لمدة محددة" : "حالة مستمرة";
    $("#assignPersistentText").textContent = (persistent.title ? persistent.label : `${persistent.status} ${periodSpan(persistent)}`)
      + (persistent.legacy_open ? " — سجل قديم بلا يوم نهاية؛ أنهِه أو احفظه بيوم نهاية" : "");
    // الحالة بنهاية بتخلص لوحدها — تعديل «حتى يوم» من النموذج بدل الإنهاء
    $("#assignStopPersistent").classList.toggle("hidden", bounded && !persistent.open_ended);
    $("#assignStopPersistent").onclick = async () => {
      const yes = await confirmDialog({
        title: `إنهاء حالة ${persistent.status} من هذا اليوم`,
        body: `ستنتهي الحالة قبل ${fmt(DUTY.date)} ويعود ${row.name} إلى الحالة العادية بداية من هذا اليوم. `
          + "الأيام السابقة تبقى مسجلة كما هي.",
        confirmLabel: "إنهاء الحالة من هذا اليوم",
        danger: true,
      });
      if (!yes) return;
      const out = await api(`/api/duty/${DUTY.date}/${encodeURIComponent(row.id)}/stop-status`,
        jsonReq("POST", {}));
      if (!out) return;
      DUTY = out; closeModal("assignModal", true); showToast("تم إنهاء الحالة من هذا اليوم"); render();
    };
    $("#assignCancelPersistent").onclick = async () => {
      const yes = await confirmDialog({
        title: `إلغاء تسجيل حالة ${persistent.status} بالكامل`,
        body: `سيُحذف تسجيل الحالة بالكامل (${periodSpan(persistent)}) من كل الأيام، السابقة واللاحقة، `
          + "كأنه لم يُسجَّل. استخدمه فقط إذا كان التسجيل خطأ. لا يمكن التراجع عن ذلك.",
        confirmLabel: "إلغاء تسجيل الحالة بالكامل",
        danger: true,
      });
      if (!yes) return;
      const out = await api(`/api/duty/${DUTY.date}/${encodeURIComponent(row.id)}/cancel-status`,
        jsonReq("POST", {}));
      if (!out) return;
      DUTY = out; closeModal("assignModal", true); showToast("تم إلغاء تسجيل الحالة بالكامل"); render();
    };
  }
  openModal("assignModal");
};

function updatePersistentHint() {
  const value = $("#assignStatus").value;
  const continuous = CONTINUOUS_STATUSES.includes(value);
  const bounded = BOUNDED_STATUSES.includes(value);
  const hint = $("#assignStatusHint");
  hint.classList.toggle("is-persistent", continuous || bounded);
  const detailed = DETAILED_STATUSES.includes(value);
  $("#assignEndRow").classList.toggle("hidden", !bounded);
  $("#assignStatusEnd").required = bounded;
  $("#assignTitleRow").classList.toggle("hidden", !detailed);
  $("#assignDetailsRow").classList.toggle("hidden", !detailed);
  $("#assignStatusTitle").required = detailed;
  $("#assignStatusDetails").required = detailed;
  hint.textContent = continuous
    ? `حالة «${value}» تبدأ من هذا اليوم وتستمر تلقائيًا حتى إنهائها.`
    : bounded ? `حالة «${value}» من هذا اليوم حتى اليوم المحدد، وتنتهي تلقائيًا بعده.`
    : value ? `حالة «${value}» لهذا اليوم فقط.`
    : "مرضي وغياب تستمر حتى إنهائها؛ طارئة ومأمورية وانتداب حتى يوم محدد؛ باقي الحالات ليوم واحد.";
}
$("#assignStatus").addEventListener("change", updatePersistentHint);

function updateMedicalFields() {
  const value = document.querySelector('input[name="assignMedicalState"]:checked')?.value || "عمل";
  $("#assignMedicalTextRow").classList.toggle("hidden", value !== "انتداب");
  updateAssignPreview();
}
$$('input[name="assignMedicalState"]').forEach(input => input.addEventListener("change", updateMedicalFields));

/* معاينة النص الكامل زي ما هيتطبع: خدمته التلقائية (أو النص القديم) + الإضافي */
function updateAssignPreview() {
  const row = DUTY?.rows.find(r => r.id === $("#assignPerson").value);
  if (!row) return;
  if (!row.leave && !row.status) {
    if (row.medical) {
      const state = document.querySelector('input[name="assignMedicalState"]:checked')?.value || "عمل";
      const text = state === "انتداب" ? ($("#assignMedicalText").value.trim() || "انتداب") : state;
      $("#assignPreview").textContent = `النص الكامل: ${text}`;
      return;
    }
    if (row.research) {
      const service = $("#assignResearchService").value.trim();
      const time = $("#assignResearchTime").value.trim();
      const text = service ? `${service}${time ? ` — انتظام ${time}` : ""}` : "تشغيله ـــــــــــــــــــــ";
      $("#assignPreview").textContent = `النص الكامل: ${text}`;
      return;
    }
  }
  const note = $("#assignNote").value.trim();
  // نفس صياغة الباك إند (`duty.service_line`): الأهداف «عمل بهدف …»
  const line = s => {
    let t = s.name || "";
    if (s.section === "الأهداف" && t) t = t === "مشرف الأهداف" ? "متابعة اعمال الاهداف" : `عمل بهدف ${t}`;
    return t + (s.shift ? ` فترة ${s.shift}` : "");
  };
  const base = note || row.services.map(line).filter(Boolean).join(" + ");
  const full = [base, $("#assignExtra").value.trim()].filter(Boolean).join(" + ");
  $("#assignPreview").textContent = full ? `النص الكامل: ${full}` : "مفيش نص تشغيلي لليوم ده.";
}
$("#assignExtra").oninput = updateAssignPreview;
$("#assignNote").oninput = updateAssignPreview;
$("#assignResearchService").oninput = updateAssignPreview;
$("#assignResearchTime").addEventListener("change", updateAssignPreview);
$("#assignMedicalText").oninput = updateAssignPreview;

$("#assignForm").onsubmit = async e => {
  e.preventDefault();
  const status = $("#assignStatus").value;
  const row = DUTY.rows.find(r => r.id === $("#assignPerson").value);
  const automaticAdmin = ["مدير الإدارة", "وكيل الإدارة"].includes(row?.command_role);
  if (!automaticAdmin && $("#assignAdmin").checked
      && ![$("#assignNote").value.trim(), $("#assignExtra").value.trim(), ...(row?.services || []).map(s => s.name)]
        .some(Boolean)) {
    showToast("اكتب النص التشغيلي قبل إضافة الضابط إلى عمل بالإدارة", true);
    $("#assignExtra").focus(); return;
  }
  const body = {taqseera: $("#assignTaq").checked, status, note: $("#assignNote").value,
    extra: $("#assignExtra").value,
    admin_work: automaticAdmin ? !!row.admin_work : $("#assignAdmin").checked};
  if (row?.research) {
    const service = $("#assignResearchService").value.trim();
    const time = $("#assignResearchTime").value.trim();
    if (!service && time) {
      showToast("اكتب اسم خدمة البحث قبل معاد الانتظام", true);
      $("#assignResearchService").focus(); return;
    }
    body.research_service = service;
    body.research_time = service ? time : "";
  }
  if (row?.medical) {
    body.medical_state = document.querySelector('input[name="assignMedicalState"]:checked')?.value || "عمل";
    body.medical_deputation_text = body.medical_state === "انتداب" ? $("#assignMedicalText").value : "";
  }
  if (BOUNDED_STATUSES.includes(status)) {
    const end = $("#assignStatusEnd").value;
    if (!end) { showToast(`حدد «حتى يوم» لحالة ${status}`, true); $("#assignStatusEnd").focus(); return; }
    if (end < DUTY.date) { showToast("«حتى يوم» قبل يوم البداية", true); $("#assignStatusEnd").focus(); return; }
    body.status_end = end;
  }
  if (DETAILED_STATUSES.includes(status)) {
    const title = $("#assignStatusTitle").value.trim(), details = $("#assignStatusDetails").value.trim();
    if (!title) { showToast(`اكتب اسم ${status}`, true); $("#assignStatusTitle").focus(); return; }
    if (!details) { showToast(`اكتب تفاصيل ${status}`, true); $("#assignStatusDetails").focus(); return; }
    body.status_title = title; body.status_details = details;
  }
  if (!status && row?.status_source === "period") {
    // «بدون» مابيغيّرش الحالة الممتدة — الإنهاء والإلغاء لهم زرارين صريحين فوق
    showToast("لإنهاء الحالة استخدم «إنهاء الحالة من هذا اليوم»، ولإلغاء تسجيلها استخدم «إلغاء تسجيل الحالة بالكامل»", true); return;
  }
  const out = await api(`/api/duty/${DUTY.date}/${encodeURIComponent($("#assignPerson").value)}`,
    jsonReq("PUT", body));
  if (!out) return;
  if (out.officer_statuses) META.officer_statuses = out.officer_statuses;
  DUTY = out; closeModal("assignModal", true); showToast("تم حفظ الحالة"); render();
};

async function loadDay(day) {
  const d = await api(`/api/duty/${day}`); if (!d) return;
  if (d.officer_statuses) META.officer_statuses = d.officer_statuses;
  DUTY = d; setPageDay(day); render();
  renderRestStrip($("#restStrip"), day);
}
const shiftDay = n => { const d = addDays($("#dutyDate").value || curDate(), n); $("#dutyDate").value = d; loadDay(d) };
$("#dayPrev").onclick = () => shiftDay(-1);
$("#dayNext").onclick = () => shiftDay(1);
$("#dayToday").onclick = () => { $("#dutyDate").value = curDate(); loadDay(curDate()) };
$("#dutyDate").onchange = () => loadDay($("#dutyDate").value);

async function load() {
  const d = await bootstrap();
  if (!d) return;
  const days = d.days || [];
  $("#dutyDate").value = days.includes(curDate()) ? curDate() : (days[days.length - 1] || curDate());
  loadDay($("#dutyDate").value);
}
load();

// الطباعة بتفتح قايمة أسماء الصافي عشان الورقة تطلع كاملة
window.addEventListener("beforeprint", () => $$(".net-names").forEach(d => d.open = true));
