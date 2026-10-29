/* يومية الأفراد — نفس شكل ورقة «افراد» الحقيقية: جدول واحد متواصل،
   الخدمات الأساسية قايمة مؤرخة (تبدأ بأسماء `22-6-2026 افراد.docx`
   ويمكن تعديلها من صفحة الأفراد) وكل تفاصيلها
   بتتغيّر يوميًا، والخدمات الطارئة (+ أي قسم مخصّص) بتيجي جاهزة من
   اليومية التفصيلية مرتبة بمعاد الانتظام — نفس منطق `board.js`/
   `counts.js` بس بعرض «الدفتر الورقي» زي `/board`. */
let AF = null, DAY = null;
let PERSONNEL_VALUES = new Map();
let AF_OCR = null;
let AF_DAY_OPEN = true;

/* زرار «Word» العام (export.js) بيلف الـHTML الظاهر — هنا لازم يبقى
   ملف Word حقيقي بنفس شكل ورقة «افراد» الحقيقية، فبيتولّد من السيرفر
   (`backend/afraad_export.py`) بدل نسخ الشاشة، نفس فكرة board.js. */
window.exportDocxUrl = () => `/api/afraad/${DAY}/export.docx`;

function personCell(p) {
  if (!p?.name && !p?.phone) return `<span class="cell-vacant">${icon("alert")} شاغرة</span>`;
  return `${esc(p.name) || "<span class='muted'>—</span>"}${p.phone ? `<div class="sub">${esc(p.phone)}</div>` : ""}`;
}

function basicRow(r) {
  const inherited = r.inherited_fields?.length
    ? `<div class="sub">موروث من ${fmt(r.inherited_from)}</div>` : "";
  return `<tr>
    <td class="name">${esc(r.name)}</td>
    <td>${personCell(r.morning)}</td>
    <td>${personCell(r.night)}</td>
    <td>${esc(r.count) || "<span class='muted'>—</span>"}${inherited}</td>
    <td>${esc(r.weapon) || "<span class='muted'>—</span>"}</td>
    <td>${esc(r.schedule) || "<span class='muted'>—</span>"}</td>
    <td><div class="actions"><button class="mini" data-action="openAfEntry"
      data-id="${esc(r.id)}">تعديل</button></div></td>
  </tr>`;
}

const BASIC_HEAD = ["الخدمة", "الخدمة الصباحية", "الخدمة الليلية", "قوام الخدمة", "التسليح", "الانتظام", "الإجراء"];

const whoText = (list, cls) => (list || []).map(p =>
  `<span class="chip ${cls}">${esc(p.role ? p.role + "/ " + p.name : p.name)}</span>`).join(" ");

function occRow(r) {
  const who = [whoText(r.officers, "m"), whoText(r.personnel, "h")].filter(Boolean).join(" ")
    || (r.vacant ? `<span class="cell-vacant">${icon("alert")} شاغرة</span>` : `<span class="muted">—</span>`);
  const count = r.conscript_count || (r.conscripts || []).reduce((n, c) => n + (c.count || 1), 0);
  return `<tr>
    <td class="name">${esc(r.label)}</td>
    <td class="wrap">${who}</td>
    <td>${count || "<span class='muted'>—</span>"}</td>
    <td>${esc(r.weapon) || "<span class='muted'>—</span>"}</td>
    <td>${esc(r.time) || "<span class='muted'>—</span>"}</td>
  </tr>`;
}

const OCC_HEAD = ["الخدمة", "القائم بها", "العدد", "التسليح", "الانتظام"];

function render() {
  const wrap = $("#afWrap");
  if (!AF) { wrap.innerHTML = skeleton("rows", 10); return }
  // الشواغر كانت نص رمادي زي أي خانة فاضية — الحالة الأهم في الصفحة بتبان
  // دلوقتي كتحذير، وعددها الكلي فوق الجدول
  const empty = p => !p?.name && !p?.phone;
  const vacant = AF.basic.reduce((n, r) => n + empty(r.morning) + empty(r.night), 0)
    + AF.occasional.filter(r => r.vacant && !(r.officers || []).length && !(r.personnel || []).length).length;
  const total = AF.basic.length * 2 + AF.occasional.length;
  const summary = vacant
    ? `<p class="vacancy-summary warn"><span class="status-dot warn" aria-hidden="true"></span>
        <b>الخانات الشاغرة: ${countLabel(vacant, "خانة")}</b> من ${total}</p>`
    : `<p class="vacancy-summary ok"><span class="status-dot ok" aria-hidden="true"></span>لا توجد خانات شاغرة</p>`;
  wrap.innerHTML = summary + `
    <div class="ledger-board">
      <div class="ledger-head">
        <h2>يومية الأفراد</h2>
        <div class="ledger-sub">${dayName(AF.date)} الموافق ${fmt(AF.date)}</div>
      </div>
      <div class="mcard">
        <h3>الخدمات الأساسية<span class="mcount">${AF.basic.length}</span></h3>
        ${mtable(BASIC_HEAD, AF.basic.map(basicRow))}
      </div>
      ${AF.officer_pairs?.length ? `<div class="mcard af-officer-pairs"><h3>ضباط الخدمات الأساسية (من اليومية التفصيلية)</h3><div class="chips">${AF.officer_pairs.map(p => `<div class="sub"><b>${esc(p.label)}</b> ← ${esc(p.person)}</div>`).join("")}</div></div>` : ""}
      <div class="mcard">
        <h3>الخدمات الطارئة<span class="mcount">${AF.occasional.length}</span></h3>
        ${AF.occasional.length ? mtable(OCC_HEAD, AF.occasional.map(occRow))
          : emptyState({compact: true, title: "لا توجد خدمات طارئة اليوم", hint: "تُضاف من اليومية التفصيلية."})}
      </div>
    </div>`;
}

function personnelLabel(person) {
  return [person.role, person.name].filter(Boolean).join("/ ");
}

function preparePersonnelChoices() {
  PERSONNEL_VALUES = new Map();
  const options = ['<option value=""></option>'];
  for (const person of AF?.personnel || []) {
    const label = personnelLabel(person);
    PERSONNEL_VALUES.set(label, person);
    PERSONNEL_VALUES.set(person.name, person);
    options.push(`<option value="${esc(label)}">${esc(label)}</option>`);
  }
  const html = options.join("");
  $("#afMorningName").innerHTML = html;
  $("#afNightName").innerHTML = html;
}

function syncPersonnel(shift) {
  const name = $(`#af${shift}Name`);
  const phone = $(`#af${shift}Phone`);
  const personId = $(`#af${shift}PersonId`);
  const person = PERSONNEL_VALUES.get(name.value.trim());
  personId.value = person?.id || "";
  if (person) phone.value = person.phone || "";
  else if (!name.value.trim() || personId.dataset.lastName !== name.value.trim()) phone.value = "";
  personId.dataset.lastName = name.value.trim();
}

async function loadDayStatus() {
  const s = await api(`/api/day-status/${DAY}`);
  if (!s) return;
  const badge = $("#dayLockBadge");
  if (s.closed) {
    badge.innerHTML = `<span class="chip err">${icon("lock")} مغلق${s.auto ? " (تلقائي)" : ""}</span>`;
  } else if (s.stage === "not_open") {
    badge.innerHTML = `<span class="chip w">${icon("clock")} لم يُفتح بعد</span>`;
  } else {
    badge.innerHTML = `<span class="chip on"><span class="status-dot ok" aria-hidden="true"></span> مفتوح</span>`;
  }
  AF_DAY_OPEN = !s.closed;
  $("#afBasicOpen").disabled = !AF_DAY_OPEN;
  $$("[data-action='openAfEntry']").forEach(button => { button.disabled = !AF_DAY_OPEN; });
}

async function loadDay(day) {
  const v = await api(`/api/afraad/${day}`);
  if (!v) return;
  AF = v; DAY = day; $("#dutyDate").value = day; setPageDay(day); render();
  preparePersonnelChoices();
  loadDayStatus();
}

const shiftDay = n => loadDay(addDays($("#dutyDate").value || curDate(), n));
$("#dayPrev").onclick = () => shiftDay(-1);
$("#dayNext").onclick = () => shiftDay(1);
$("#dayToday").onclick = () => loadDay(curDate());
$("#dutyDate").onchange = () => loadDay($("#dutyDate").value);

function openAfEntry(id) {
  const row = AF.basic.find(r => r.id === id);
  if (!row) return;
  $("#afEntryId").value = id;
  $("#afEntryTitle").textContent = row.name;
  $("#afMorningPersonId").value = row.morning.person_id || "";
  $("#afNightPersonId").value = row.night.person_id || "";
  $("#afMorningName").value = row.morning.name || "";
  $("#afMorningPhone").value = row.morning.phone || "";
  $("#afNightName").value = row.night.name || "";
  $("#afNightPhone").value = row.night.phone || "";
  $("#afCount").value = row.count || "";
  $("#afWeapon").value = row.weapon || "";
  $("#afSchedule").value = row.schedule || "";
  $("#afMorningPersonId").dataset.lastName = $("#afMorningName").value.trim();
  $("#afNightPersonId").dataset.lastName = $("#afNightName").value.trim();
  openModal("afEntryModal");
}
ACTIONS.openAfEntry = id => openAfEntry(id);

function renderBasicModal() {
  $("#afBasicEffective").textContent = `التعديل يسري من يوم ${fmt(DAY)} وما بعده`;
  $("#afBasicList").innerHTML = (AF.basic || []).map(row => `<div class="list-row"><span>${esc(row.name)}</span><input data-basic-location="${esc(row.id)}" maxlength="120" value="${esc(row.location_text || "")}" placeholder="المكان"><input data-basic-count="${esc(row.id)}" type="number" min="0" step="1" value="${row.conscript_count ?? ""}" placeholder="عدد المجندين"><button type="button" class="mini" data-basic-save="${esc(row.id)}">حفظ</button><button type="button" class="mini bad" data-basic-remove="${esc(row.id)}">حذف</button></div>`).join("");
}

$("#afBasicOpen").onclick = () => { renderBasicModal(); openModal("afBasicModal"); };
$("#afBasicList").onclick = async event => {
  const button = event.target.closest("[data-basic-remove]");
  const save = event.target.closest("[data-basic-save]");
  if (save) {
    const id = save.dataset.basicSave;
    const count = $(`[data-basic-count="${CSS.escape(id)}"]`).value;
    const location_text = $(`[data-basic-location="${CSS.escape(id)}"]`).value.trim();
    const out = await api(`/api/afraad/${DAY}/basic-services/${encodeURIComponent(id)}`, jsonReq("PUT", {location_text, conscript_count: count, revision: AF.revision}));
    if (out) { AF = out; render(); renderBasicModal(); showToast("تم حفظ تعريف الخدمة"); }
    return;
  }
  if (!button) return;
  const row = AF.basic.find(item => item.id === button.dataset.basicRemove);
  if (!row || !(await confirmDialog({title: "إزالة الخدمة الأساسية", body: `هتتشال «${row.name}» من اليوم ورايح، وبيتم مسح البيانات المُدخلة ليها في اليوم ده.`, confirmLabel: "إزالة", danger: true}))) return;
  const out = await api(`/api/afraad/${DAY}/basic-services/${encodeURIComponent(row.id)}`, jsonReq("DELETE", {revision: AF.revision}));
  if (!out) return;
  AF = out; render(); renderBasicModal(); showToast("تمت إزالة الخدمة");
};

$("#afBasicForm").onsubmit = async event => {
  event.preventDefault();
  const input = $("#afBasicName"), name = input.value.trim();
  if (!name) { showToast("اكتب اسم الخدمة", true); return; }
  const out = await api(`/api/afraad/${DAY}/basic-services`, jsonReq("POST", {name, revision: AF.revision}));
  if (!out) return;
  AF = out; input.value = ""; render(); renderBasicModal(); showToast("تمت إضافة الخدمة");
};

for (const shift of ["Morning", "Night"]) {
  $(`#af${shift}Name`).addEventListener("input", () => syncPersonnel(shift));
  $(`#af${shift}Name`).addEventListener("change", () => syncPersonnel(shift));
}

$("#afEntryForm").onsubmit = async e => {
  e.preventDefault();
  const id = $("#afEntryId").value;
  const body = {
    morning_name: $("#afMorningName").value.trim(),
    morning_person_id: $("#afMorningPersonId").value,
    morning_phone: $("#afMorningPhone").value.trim(),
    night_name: $("#afNightName").value.trim(),
    night_person_id: $("#afNightPersonId").value,
    night_phone: $("#afNightPhone").value.trim(),
    count: $("#afCount").value.trim(),
    weapon: $("#afWeapon").value.trim(),
    schedule: $("#afSchedule").value.trim(),
  };
  const out = await api(`/api/afraad/${DAY}/basic/${encodeURIComponent(id)}`, jsonReq("PUT", body));
  if (!out) return;
  AF = out; closeModal("afEntryModal", true); showToast("تم الحفظ"); render();
};

/* ===== قراءة صورة اليومية (OCR بالذكاء الاصطناعي) =====
   نافذة واحدة بثلاث مراحل (data-stage): scan ← review أو error.
   السيرفر بيرد مرة واحدة في الآخر من غير تقدّم فعلي، فمراحل القراءة هنا
   تقديرية بالوقت (والواجهة بتقول كده) — مش أرقام مختلقة عن الخلايا. */
const OCR_STEPS = [["upload", 0], ["grid", 2], ["read", 9], ["match", 45]];   // ثانية تقريبية لبداية كل مرحلة
const OCR_TIMEOUT_MS = 190000;
let OCR_RUN = null;          // {controller, url, started, timer}
let OCR_FILE_URL = "";       // الصورة الأصلية لعرضها في المراجعة

const ocrCard = () => $("#afOcrModal .af-ocr-modal");
function ocrStage(stage, sub) {
  ocrCard().dataset.stage = stage;
  $("#afOcrSub").textContent = sub || "";
}

function ocrOptions(items, selected, label, candidates) {
  const text = item => item.role ? `${item.role}/ ${item.name}` : item.name;
  const suggested = (candidates || []).filter(c => c.id && c.id !== selected);
  return `<option value="">— ${esc(label)} —</option>`
    + (suggested.length ? `<optgroup label="اقتراحات القراءة">${suggested.map(c =>
        `<option value="${esc(c.id)}">${esc(text(c))} (${Math.round((c.score || 0) * 100)}%)</option>`).join("")}</optgroup>` : "")
    + `<optgroup label="كل الأفراد">${(items || []).map(item =>
        `<option value="${esc(item.id)}"${item.id === selected ? " selected" : ""}>${esc(text(item))}</option>`).join("")}</optgroup>`;
}

function ocrTick() {
  if (!OCR_RUN) return;
  const seconds = (performance.now() - OCR_RUN.started) / 1000;
  const current = OCR_STEPS.filter(([, at]) => seconds >= at).length - 1;
  $$("#afOcrSteps li").forEach((li, i) => {
    li.classList.toggle("done", i < current);
    li.classList.toggle("active", i === current);
  });
  // منحنى بيقرّب من 92% ويستنى الرد الفعلي بدل ما يوصل 100% ويفضل واقف
  const percent = Math.round(92 * (1 - Math.exp(-seconds / 22)));
  $("#afOcrBar i").style.width = percent + "%";
  $("#afOcrBar").setAttribute("aria-valuenow", percent);
  $("#afOcrElapsed").textContent = seconds < 60 ? `${Math.floor(seconds)} ث`
    : `${Math.floor(seconds / 60)} د ${Math.floor(seconds % 60)} ث`;
}

function ocrCleanup() {
  if (!OCR_RUN) return;
  clearInterval(OCR_RUN.timer);
  OCR_RUN.controller.abort("closed");
  OCR_RUN = null;
}

function ocrFail(title, text) {
  $("#afOcrErrorTitle").textContent = title;
  $("#afOcrErrorText").textContent = text;
  ocrStage("error", "");
}

async function startOcr(file) {
  ocrCleanup();
  if (OCR_FILE_URL) URL.revokeObjectURL(OCR_FILE_URL);
  OCR_FILE_URL = URL.createObjectURL(file);
  $("#afOcrPreviewImg").src = OCR_FILE_URL;
  AF_OCR = null;
  const controller = new AbortController();
  const run = OCR_RUN = {controller, started: performance.now(), timer: setInterval(ocrTick, 250)};
  ocrStage("scan", `بيقرا «${file.name}» — لا تقفل الصفحة.`);
  ocrTick();
  openModal("afOcrModal");

  const timeout = setTimeout(() => controller.abort("timeout"), OCR_TIMEOUT_MS);
  let response, out = {};
  try {
    const body = new FormData(); body.append("image", file);
    response = await fetch(`/api/afraad/${DAY}/ocr/preview`, {
      method: "POST", body, signal: controller.signal, headers: {"X-Requested-With": "fetch"}});
    out = await response.json().catch(() => ({}));
  } catch (error) {
    if (OCR_RUN !== run) return;                       // المستخدم قفل النافذة أو بدأ قراءة جديدة
    clearInterval(run.timer); OCR_RUN = null;
    ocrFail(controller.signal.reason === "timeout" ? "القراءة أخدت وقت أطول من المسموح" : "تعذر الاتصال بالخادم",
      controller.signal.reason === "timeout" ? "جرّب صورة أوضح أو أصغر حجمًا." : "تأكد من الاتصال وجرّب تاني.");
    return;
  } finally { clearTimeout(timeout); }
  if (OCR_RUN !== run) return;
  clearInterval(run.timer); OCR_RUN = null;

  if (response.status === 401) { location.href = "/login?next=" + encodeURIComponent(location.pathname); return; }
  if (response.status === 403) { ocrFail("مفيش صلاحية", "ليس لديك صلاحية لقراءة الصور."); return; }
  if (!response.ok) { ocrFail("تعذّرت قراءة الصورة", out.error || "حدث خطأ غير متوقع."); return; }

  // خلّص كل المراحل وبعدين افتح المراجعة بانتقال هادي
  $$("#afOcrSteps li").forEach(li => { li.classList.remove("active"); li.classList.add("done"); });
  $("#afOcrBar i").style.width = "100%"; $("#afOcrBar").setAttribute("aria-valuenow", 100);
  await new Promise(resolve => setTimeout(resolve, 450));
  if (ocrCard().dataset.stage !== "scan" || $("#afOcrModal").classList.contains("hidden")) return;
  AF_OCR = out;
  renderOcrPreview();
  ocrStage("review", "راجع النتيجة: الخانات الصفراء والحمراء محتاجة نظرة منك قبل التسكين.");
}

function ocrBadge(score, matchedText) {
  const pct = Math.round((score || 0) * 100);
  const cls = pct >= 85 ? "ok" : pct >= 60 ? "mid" : "low";
  return `<span class="ocr-conf ${cls}" title="${esc(matchedText || "ثقة المطابقة")}">${pct}%</span>`;
}

function ocrSlot(title, read, match, attr, personnel) {
  const picked = match?.matched ? match.id : "";
  const state = !read ? `<span class="ocr-conf none">فاضية</span>`
    : match?.matched ? ocrBadge(match.score, "مطابق: " + (match.name || ""))
    : `<span class="ocr-conf low" title="مفيش مطابقة مؤكدة — اختار الفرد يدويًا">غير مطابق</span>`;
  return `<div class="ocr-slot">
    <div class="ocr-slot-head"><h5>${title}</h5>${state}</div>
    <div class="ocr-read" title="النص المقروء من الصورة">${read ? esc(read) : "<span class='muted'>—</span>"}</div>
    <select ${attr} aria-label="الفرد — ${title}">${ocrOptions(personnel, picked, "اختر الفرد", match?.candidates)}</select>
  </div>`;
}

/* حالة الصف: جاهز (مطابقة مؤكدة) / يحتاج مراجعة / ناقص (مفيش خدمة أو فرد) */
function ocrRowState(card) {
  const filled = ocrRowPayload(card);
  const ready = !!AF_OCR.rows[Number(card.dataset.ocrRow)].auto_selected;
  return filled ? (ready ? "ready" : "review") : "missing";
}

function ocrUpdateCount() {
  const cards = $$("#afOcrRows [data-ocr-row]");
  const checked = cards.filter(card => card.querySelector("[data-ocr-use]").checked);
  const valid = checked.filter(card => ocrRowPayload(card));
  const states = {ready: 0, review: 0, missing: 0};
  cards.forEach(card => {
    const state = ocrRowState(card); states[state]++;
    card.dataset.state = state;
    card.classList.toggle("is-off", !card.querySelector("[data-ocr-use]").checked);
    card.querySelector(".ocr-state").textContent = {ready: "جاهز", review: "راجعه", missing: "ناقص"}[state];
  });
  const missing = checked.length - valid.length;
  $("#afOcrCount").innerHTML = `<b>${valid.length}</b> جاهز للتسكين من ${cards.length} صف`
    + (missing ? ` · <span class="ocr-warn-text">${missing} محدد ناقص (الخدمة أو الفرد)</span>` : "");
  $("#afOcrApply").textContent = valid.length ? `تسكين المختار (${valid.length})` : "تسكين المختار";
  $("#afOcrApply").disabled = !valid.length;
  const counts = {all: cards.length, ready: states.ready, review: states.review + states.missing};
  $$("#afOcrFilter button").forEach(btn => { btn.querySelector("i").textContent = counts[btn.dataset.filter]; });
}

function ocrRowPayload(card) {
  const payload = {
    service_id: card.querySelector("[data-ocr-service]").value,
    morning_person_id: card.querySelector("[data-ocr-morning]").value,
    night_person_id: card.querySelector("[data-ocr-night]").value,
  };
  return payload.service_id && (payload.morning_person_id || payload.night_person_id) ? payload : null;
}

function ocrFilter(which) {
  $$("#afOcrFilter button").forEach(btn => btn.classList.toggle("on", btn.dataset.filter === which));
  $$("#afOcrRows [data-ocr-row]").forEach(card => {
    const state = card.dataset.state;
    card.hidden = which === "ready" ? state !== "ready" : which === "review" ? state === "ready" : false;
  });
}

function ocrView(which) {
  const overlay = $("#afOcrOverlay");
  const useOverlay = which === "overlay" && AF_OCR?.overlay_png;
  overlay.src = useOverlay ? AF_OCR.overlay_png : OCR_FILE_URL;
  $$("#afOcrModal [data-view]").forEach(btn => {
    const on = btn.dataset.view === (useOverlay ? "overlay" : "original");
    btn.classList.toggle("on", on); btn.setAttribute("aria-selected", on);
  });
}

function renderOcrPreview() {
  const summary = AF_OCR?.summary || {};
  const stat = (label, value) => `<span class="ocr-stat"><b>${value}</b> ${label}</span>`;
  $("#afOcrSummary").innerHTML = `<div class="ocr-stats">
    ${stat("صف مقروء", summary.detected_rows || 0)}${stat("خدمة مطابقة", summary.matched_services || 0)}
    ${stat("فرد مطابق", summary.matched_people || 0)}${stat("ثقة الجدول", Math.round((AF_OCR?.grid?.confidence || 0) * 100) + "%")}</div>`;
  $("#afOcrOverlayTab").classList.toggle("hidden", !AF_OCR?.overlay_png);
  $("#afOcrOverlay").closest(".ocr-viewer").classList.remove("zoomed");
  $("#afOcrZoom").textContent = "تكبير";
  ocrView("original");

  const services = AF?.basic || [], personnel = AF?.personnel || [];
  const rows = AF_OCR?.rows || [];
  $("#afOcrRows").innerHTML = rows.length ? rows.map((row, index) => `
    <article class="ocr-card" data-ocr-row="${index}">
      <header class="ocr-card-head">
        <label class="ocr-check" title="استيراد الصف"><input type="checkbox" data-ocr-use${row.auto_selected ? " checked" : ""} aria-label="استيراد الصف"></label>
        <span class="ocr-no">${index + 1}</span>
        <div class="ocr-svc"><b>${esc(row.service || "خدمة غير مقروءة")}</b>
          ${row.service ? ocrBadge(row.service_score, "ثقة مطابقة اسم الخدمة") : ""}</div>
        <span class="ocr-state"></span>
      </header>
      <select data-ocr-service aria-label="الخدمة في السيستم">${ocrOptions(services, row.service_id, "اختر الخدمة في السيستم")}</select>
      <div class="ocr-slots">
        ${ocrSlot("الصباحية", row.morning, row.morning_match, "data-ocr-morning", personnel)}
        ${ocrSlot("الليلية", row.evening, row.night_match, "data-ocr-night", personnel)}
      </div>
    </article>`).join("")
    : emptyState({title: "لم تُستخرج صفوف قابلة للتسكين", hint: "راجع صورة الجدول والملاحظات، وجرّب صورة أوضح أو قصّ الجدول بس."});
  // الصفوف بتترسم بعد تحميل الصفحة، فـ upgradeSelects الأولانية ماشافتهاش —
  // من غيرها خانة الفرد والخدمة كانت قايمة عادية من غير كتابة وبحث.
  upgradeSelects($("#afOcrRows"));
  const warnings = [...new Set([...(AF_OCR?.warnings || []), ...(AF_OCR?.grid?.warnings || [])])];
  $("#afOcrWarnings").innerHTML = warnings.length
    ? `<details class="alert warn ocr-warnings"><summary>ملاحظات القراءة (${warnings.length})</summary><ul>${warnings.map(v => `<li>${esc(v)}</li>`).join("")}</ul></details>` : "";
  ocrUpdateCount();
  ocrFilter("all");
}

/* ---- تجهيز الصورة: صفحة من PDF + قص (للصورة بس) قبل القراءة ---- */
const _afPdfScript = document.currentScript;
let _afPdfReady = null;
function loadPdfJs() {                       // المكتبة تقيلة — بتتحمّل أول ما حد يختار PDF
  if (window.pdfjsLib) return Promise.resolve(window.pdfjsLib);
  if (!_afPdfReady) {
    _afPdfReady = new Promise((resolve, reject) => {
      const tag = document.createElement("script");
      tag.src = _afPdfScript.dataset.pdfjs;
      tag.onload = () => { pdfjsLib.GlobalWorkerOptions.workerSrc = _afPdfScript.dataset.pdfWorker; resolve(window.pdfjsLib); };
      tag.onerror = () => { _afPdfReady = null; tag.remove(); reject(new Error("load")); };
      document.head.appendChild(tag);
    });
  }
  return _afPdfReady;
}

const OCR_MAX_BYTES = 9.5 * 1024 * 1024;     // حد السيرفر 10MB
const OCR_PDF_WIDTH = 2200;                  // عرض رسم صفحة الـPDF بالبكسل
let OCR_SRC = null;                          // {file, isPdf, pdf, url, page}
let CROP = {l: 0, t: 0, r: 1, b: 1};         // القص كنسب من أبعاد الصورة

function ocrSrcCleanup() {
  if (OCR_SRC?.url) URL.revokeObjectURL(OCR_SRC.url);
  OCR_SRC?.pdf?.destroy?.();
  OCR_SRC = null;
}

function cropRender() {
  const img = $("#afOcrCropImg"), w = img.clientWidth, h = img.clientHeight;
  Object.assign($("#afOcrCrop").style, {
    left: CROP.l * w + "px", top: CROP.t * h + "px",
    width: (CROP.r - CROP.l) * w + "px", height: (CROP.b - CROP.t) * h + "px"});
  const full = CROP.l <= 0.001 && CROP.t <= 0.001 && CROP.r >= 0.999 && CROP.b >= 0.999;
  const px = (CROP.r - CROP.l) * img.naturalWidth, py = (CROP.b - CROP.t) * img.naturalHeight;
  $("#afOcrCropInfo").textContent = full ? "اسحب الحواف لقص الجزء اللي فيه الجدول بس."
    : `المنطقة المقصوصة ${Math.round(px)}×${Math.round(py)} بكسل`;
  $("#afOcrCropReset").disabled = full;
}

function setPrepImage(url) {
  const img = $("#afOcrCropImg");
  if (OCR_SRC.url && OCR_SRC.url !== url) URL.revokeObjectURL(OCR_SRC.url);
  OCR_SRC.url = url;
  CROP = {l: 0, t: 0, r: 1, b: 1};
  img.onload = cropRender;
  img.src = url;
}

async function renderPdfPage(number) {
  const pdf = OCR_SRC.pdf;
  OCR_SRC.page = number;
  $$("#afOcrPages button").forEach(b => b.classList.toggle("on", Number(b.dataset.page) === number));
  const page = await pdf.getPage(number);
  const base = page.getViewport({scale: 1});
  const viewport = page.getViewport({scale: Math.min(3, OCR_PDF_WIDTH / base.width)});
  const canvas = document.createElement("canvas");
  canvas.width = Math.ceil(viewport.width); canvas.height = Math.ceil(viewport.height);
  await Promise.race([
    page.render({canvasContext: canvas.getContext("2d"), viewport}).promise,
    new Promise((_, reject) => setTimeout(() => reject(new Error("استغرق رسم الصفحة وقتًا أطول من اللازم — تأكد إن التبويب ظاهر وجرّب تاني.")), 15000)),
  ]);
  const blob = await new Promise(resolve => canvas.toBlob(resolve, "image/png"));
  if (OCR_SRC?.pdf !== pdf || OCR_SRC.page !== number) return;      // اختار صفحة تانية في الأثناء
  setPrepImage(URL.createObjectURL(blob));
}

async function renderPdfThumbs(pdf) {
  const strip = $("#afOcrPages");
  strip.innerHTML = "";
  for (let n = 1; n <= pdf.numPages; n++) {
    const button = document.createElement("button");
    button.type = "button"; button.dataset.page = n; button.setAttribute("role", "option");
    button.innerHTML = `<canvas></canvas><span>${n}</span>`;
    strip.appendChild(button);
    const page = await pdf.getPage(n);
    const viewport = page.getViewport({scale: 120 / page.getViewport({scale: 1}).width});
    const canvas = button.querySelector("canvas");
    canvas.width = Math.ceil(viewport.width); canvas.height = Math.ceil(viewport.height);
    page.render({canvasContext: canvas.getContext("2d"), viewport});
    if (OCR_SRC?.pdf !== pdf) return;
  }
}

async function prepareFile(file) {
  ocrCleanup(); ocrSrcCleanup();
  const isPdf = file.type === "application/pdf" || /\.pdf$/i.test(file.name);
  OCR_SRC = {file, isPdf, pdf: null, url: "", page: 0};
  $("#afOcrPdfBar").classList.toggle("hidden", !isPdf);
  $("#afOcrCropImg").removeAttribute("src");
  ocrStage("prepare", isPdf ? "اختر الصفحة اللي فيها اليومية، وبعدين اقصّ الجزء اللي فيه الجدول بس."
    : "اقصّ الجزء اللي فيه الجدول بس (اختياري) وبعدين ابدأ القراءة.");
  openModal("afOcrModal");
  if (!isPdf) { setPrepImage(URL.createObjectURL(file)); return; }
  try {
    try { await loadPdfJs(); }
    catch (error) { throw new Error("تعذّر تحميل مكتبة قراءة PDF — تحقق من الاتصال وجرّب تاني."); }
    const pdf = await pdfjsLib.getDocument({data: await file.arrayBuffer()}).promise;
    if (OCR_SRC?.file !== file) { pdf.destroy?.(); return; }
    OCR_SRC.pdf = pdf;
    renderPdfThumbs(pdf);
    await renderPdfPage(1);
  } catch (error) {
    if (OCR_SRC?.file !== file) return;
    ocrFail("تعذّرت قراءة ملف PDF", error.message || "الملف تالف أو محمي بكلمة مرور.");
  }
}

async function croppedFile() {
  const img = $("#afOcrCropImg");
  const full = CROP.l <= 0.001 && CROP.t <= 0.001 && CROP.r >= 0.999 && CROP.b >= 0.999;
  if (!OCR_SRC.isPdf && full) return OCR_SRC.file;                  // من غير قص: الأصل زي ما هو
  const sx = Math.round(CROP.l * img.naturalWidth), sy = Math.round(CROP.t * img.naturalHeight);
  const sw = Math.max(1, Math.round((CROP.r - CROP.l) * img.naturalWidth));
  const sh = Math.max(1, Math.round((CROP.b - CROP.t) * img.naturalHeight));
  const canvas = document.createElement("canvas");
  canvas.width = sw; canvas.height = sh;
  canvas.getContext("2d").drawImage(img, sx, sy, sw, sh, 0, 0, sw, sh);
  let blob = await new Promise(resolve => canvas.toBlob(resolve, "image/png"));
  let name = OCR_SRC.isPdf ? `${OCR_SRC.file.name.replace(/\.pdf$/i, "")}-p${OCR_SRC.page}.png` : "crop.png";
  if (blob && blob.size > OCR_MAX_BYTES) {                          // PNG كبير: JPEG بجودة عالية
    blob = await new Promise(resolve => canvas.toBlob(resolve, "image/jpeg", 0.92));
    name = name.replace(/\.png$/, ".jpg");
  }
  return blob ? new File([blob], name, {type: blob.type}) : null;
}

function cropPointerDown(event) {
  const handle = event.target.closest("[data-h]");
  const box = $("#afOcrCrop");
  if (!handle && event.target !== box) return;
  event.preventDefault();
  const img = $("#afOcrCropImg"), w = img.clientWidth, h = img.clientHeight;
  const dir = handle ? handle.dataset.h : "move", start = {x: event.clientX, y: event.clientY, ...CROP};
  const MIN = 0.04, clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
  box.setPointerCapture(event.pointerId);
  const move = e => {
    const dx = (e.clientX - start.x) / w, dy = (e.clientY - start.y) / h;
    let {l, t, r, b} = start;
    if (dir === "move") {
      const mx = clamp(dx, -l, 1 - r), my = clamp(dy, -t, 1 - b);
      l += mx; r += mx; t += my; b += my;
    } else {
      if (dir.includes("w")) l = clamp(l + dx, 0, r - MIN);
      if (dir.includes("e")) r = clamp(r + dx, l + MIN, 1);
      if (dir.includes("n")) t = clamp(t + dy, 0, b - MIN);
      if (dir.includes("s")) b = clamp(b + dy, t + MIN, 1);
    }
    CROP = {l, t, r, b}; cropRender();
  };
  const up = () => { box.removeEventListener("pointermove", move); box.removeEventListener("pointerup", up); box.removeEventListener("pointercancel", up); };
  box.addEventListener("pointermove", move); box.addEventListener("pointerup", up); box.addEventListener("pointercancel", up);
}
$("#afOcrCrop").addEventListener("pointerdown", cropPointerDown);
$("#afOcrCropReset").onclick = () => { CROP = {l: 0, t: 0, r: 1, b: 1}; cropRender(); };
window.addEventListener("resize", () => { if (OCR_SRC?.url) cropRender(); });
$("#afOcrPages").addEventListener("click", event => {
  const button = event.target.closest("[data-page]");
  if (button && OCR_SRC?.pdf) renderPdfPage(Number(button.dataset.page)).catch(error =>
    showToast(error.message || "تعذّر رسم الصفحة", true));
});
$("#afOcrGo").onclick = async () => {
  if (!OCR_SRC?.url) return;
  const file = await croppedFile();
  if (!file) { showToast("تعذّر تجهيز الصورة المقصوصة.", true); return; }
  startOcr(file);
};

$("#afOcrOpen").onclick = () => $("#afOcrImage").click();
$("#afOcrImage").onchange = event => {
  const file = event.target.files?.[0];
  event.target.value = "";
  if (file && DAY) prepareFile(file);
};
$("#afOcrRetry").onclick = $("#afOcrAgain").onclick = () => $("#afOcrImage").click();
$("#afOcrCancel").onclick = () => closeModal("afOcrModal");
$("#afOcrModal").addEventListener("click", event => {
  const view = event.target.closest("[data-view]");
  if (view) ocrView(view.dataset.view);
  const pick = event.target.closest("[data-ocr-select]");
  if (pick) {
    $$("#afOcrRows [data-ocr-row]").forEach(card => {
      const index = Number(card.dataset.ocrRow), mode = pick.dataset.ocrSelect;
      card.querySelector("[data-ocr-use]").checked = mode === "all" ? true
        : mode === "none" ? false : !!AF_OCR.rows[index].auto_selected;
    });
    ocrUpdateCount();
  }
  const filter = event.target.closest("[data-filter]");
  if (filter) ocrFilter(filter.dataset.filter);
  if (event.target.closest("#afOcrZoom")) {
    const viewer = event.target.closest(".ocr-viewer");
    viewer.classList.toggle("zoomed");
    $("#afOcrZoom").textContent = viewer.classList.contains("zoomed") ? "تصغير" : "تكبير";
  }
});
$("#afOcrRows").addEventListener("change", () => { ocrUpdateCount(); const on = $("#afOcrFilter .on"); if (on) ocrFilter(on.dataset.filter); });
// قفل النافذة بأي طريقة بيوقف القراءة الجارية ويحرر الصورة المؤقتة
new MutationObserver(() => {
  if ($("#afOcrModal").classList.contains("hidden")) {
    ocrCleanup(); ocrSrcCleanup();
    if (OCR_FILE_URL) { URL.revokeObjectURL(OCR_FILE_URL); OCR_FILE_URL = ""; }
  }
}).observe($("#afOcrModal"), {attributes: true, attributeFilter: ["class"]});

$("#afOcrApply").onclick = async () => {
  const rows = $$("#afOcrRows [data-ocr-row]").filter(card => card.querySelector("[data-ocr-use]").checked)
    .map(ocrRowPayload).filter(Boolean);
  if (!rows.length) { showToast("اختر صفًا واحدًا على الأقل وحدد الفرد.", true); return; }
  // كل الصفوف المقروءة (حتى غير المحددة) بتتبعت عشان تتسجّل كعيّنة تدريب
  const review = $$("#afOcrRows [data-ocr-row]").map(card => ({
    index: Number(card.dataset.ocrRow), selected: card.querySelector("[data-ocr-use]").checked,
    service_id: card.querySelector("[data-ocr-service]").value,
    morning_person_id: card.querySelector("[data-ocr-morning]").value,
    night_person_id: card.querySelector("[data-ocr-night]").value,
  }));
  const out = await api(`/api/afraad/${DAY}/ocr/apply`, jsonReq("POST", {
    revision: AF_OCR?.revision || AF?.revision, rows, sample_id: AF_OCR?.sample_id || "", review,
  }));
  if (!out) return;
  AF = out.data; preparePersonnelChoices(); render(); closeModal("afOcrModal", true);
  showToast(`تم تسكين ${out.applied} من خانات اليومية`);
};

async function load() {
  const d = await bootstrap();
  if (!d) return;
  loadDay(curDate());
}
load();
