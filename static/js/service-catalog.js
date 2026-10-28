/* دليل الخدمات — كرت لكل خدمة أساسية (اسمها، فترتها، قوامها، تعليماتها،
   وموقعها بالنص والصور). بيتولّد أول مرة من قالب اعداد الخدمات وبعدها
   بيتعدّل حر — مستقل تمامًا عن القالب بعد كده.

   صور الموقع بترفع كملفات (مش base64) — مباشرة لو صورة، أو تختار صفحة
   من PDF (بيترسم في المتصفح بـPDF.js وتترفع كصورة PNG، السيرفر ملوش أي
   دخل بمعالجة PDF خالص). */
let CATALOG = [], PERIODS = [], SVC_KINDS = [], SVC_POST_TYPES = [], SVC_TAGS = [], SVC_ENTRY_TAGS = [], SERVICE_LINES = [], SERVICE_LINES_REVISION = "";
const CAMPAIGN_LORRIES = [["", "بدون لوري"], ["LOR-1", "المحور + المحكمة"], ["LOR-2", "القنصلية"], ["LOR-3", "فيصل"], ["LOR-4", "كـ109"]];
let INSPECTIONS = {}, INSP_WEEKDAYS = [];
const SERVICE_PERIOD_LABELS = {
  "صباحية بس": "صباحية فقط",
  "ليلية بس": "ليلية فقط",
};
const servicePeriodLabel = period => SERVICE_PERIOD_LABELS[period] || period;

/* مكتبة PDF تقيلة (313KB + worker) ومحتاجينها بس لما حد يرفع PDF — بتتحمّل
   ساعتها مرة واحدة بدل ما تتنزّل مع كل فتح للصفحة (فرق كبير على الموبايل). */
const _pdfScript = document.currentScript;
let _pdfjsReady = null;
function loadPdfJs() {
  if (window.pdfjsLib) return Promise.resolve(window.pdfjsLib);
  if (!_pdfjsReady) {
    _pdfjsReady = new Promise((resolve, reject) => {
      const tag = document.createElement("script");
      tag.src = _pdfScript.dataset.pdfjs;
      tag.onload = () => {
        pdfjsLib.GlobalWorkerOptions.workerSrc = _pdfScript.dataset.pdfWorker;
        resolve(window.pdfjsLib);
      };
      tag.onerror = () => { _pdfjsReady = null; tag.remove(); reject(new Error("load")) };
      document.head.appendChild(tag);
    });
  }
  return _pdfjsReady;
}

function serviceCard(s) {
  const bits = [];
  if (s.has_command) {
    const who = [];
    if (s.command_officers) who.push(countLabel(s.command_officers, "ضابط"));
    if (s.command_individuals) who.push(countLabel(s.command_individuals, "فرد"));
    bits.push(`برئاسة ${who.length ? who.join(" و") : "—"}`);
  } else {
    bits.push("بلا رئاسة");
  }
  bits.push(s.count ? countLabel(s.count, "مجند") : "بدون مجندين");
  if (s.weapon) bits.push(esc(s.weapon));
  const hasLocation = !!(s.location_text || s.location_images?.length);
  const reports = [s.report_am ? `صباحية: ${formatTimeAr(s.report_am)}` : "", s.report_pm ? `ليلية: ${formatTimeAr(s.report_pm)}` : ""].filter(Boolean);
  return `<div class="service-card">
    <div class="service-head">
      <div class="service-head-main">
        <h3 class="service-name">${esc(s.name)}
          <span class="svc-location-flag ${hasLocation ? "on" : "off"}"
            role="img" aria-label="${hasLocation ? "له موقع مسجّل" : "لا يوجد موقع مسجّل"}"
            title="${hasLocation ? "الموقع محفوظ" : "لا يوجد موقع محفوظ"}">${icon("pin")}${hasLocation ? "" : '<span class="sr-only">لا يوجد موقع مسجّل</span>'}</span>
        </h3>
        <div class="service-meta">
          ${s.post_type ? `<span class="chip m">${esc(s.post_type)}</span>` : ""}
          ${s.period ? `<span class="chip w">${esc(servicePeriodLabel(s.period))}</span>` : ""}
          ${s.kind ? `<span class="chip ${s.kind === "داخلية" ? "h" : "w"}">${esc(s.kind)}</span>` : ""}
          ${(s.tags || []).map(t => `<span class="chip soon">#${esc(t)}</span>`).join("")}
        </div>
      </div>
    </div>
    <p class="service-bits">${bits.join(" · ")}</p>
    ${reports.length ? `<p class="service-reports" aria-label="مواعيد الانتظام">${reports.join(" · ")}</p>` : ""}
    ${s.instructions ? `<p class="hint service-hint">${esc(s.instructions)}</p>` : ""}
    <div class="service-bar">
      ${hasLocation ? `<button class="mini" data-action="openLocation" data-id="${esc(s.id)}"
        title="عرض موقع الخدمة">${icon("pin")} الموقع</button>` : ""}
      <div class="actions">
        <button class="mini" data-action="openService" data-id="${esc(s.id)}">تعديل</button>
        ${rowMenu([{action: "deleteService", id: s.id, extra: {name: s.name},
          label: "حذف", danger: true}], {label: "إجراءات الخدمة"})}
      </div>
    </div>
  </div>`;
}

/* فلاتر الدليل — نص حر (اسم/تعليمات) + تصنيف + فترة + وسم، الأربعة
   بتتطبّق مع بعض (AND) زي فلاتر صفحة القوة بالظبط. */
function filteredCatalog() {
  const q = $("#svcSearch").value.trim();
  const kind = $("#svcKindFilter").value;
  const period = $("#svcPeriodFilter").value;
  const tag = $("#svcTagFilter").value;
  return CATALOG.filter(s => {
    if (q && !arIncludes(s.name, q) && !arIncludes(s.instructions, q)) return false;
    if (kind && s.kind !== kind) return false;
    if (period && s.period !== period) return false;
    if (tag && !(s.tags || []).includes(tag)) return false;
    return true;
  });
}

function render() {
  const rows = filteredCatalog();
  if (!CATALOG.length) {
    $("#catalogWrap").innerHTML = emptyState({title: "لا توجد خدمات في الدليل", hint: "اضغط «إنشاء الدليل» أو «خدمة جديدة» للبدء."});
  } else if (!rows.length) {
    $("#catalogWrap").innerHTML = emptyState({icon: "search", title: "لا توجد خدمة مطابقة للتصفية", hint: "حاول تعديل البحث أو عوامل التصفية."});
  } else {
    const assigned = new Set();
    let groups = SERVICE_LINES.map(line => {
      const ids = new Set((line.members || []).map(m => m.id));
      const members = rows.filter(s => ids.has(s.id));
      members.forEach(s => assigned.add(s.id));
      if (!members.length) return "";
      return `<section class="service-line-group"><header class="service-line-head"><h2>${esc(line.name || "خط سير")}</h2><span>${esc(line.lorry_name || "")}</span></header><div class="service-grid">${members.map(serviceCard).join("")}</div></section>`;
    }).filter(Boolean).join("");
    const singles = rows.filter(s => !assigned.has(s.id));
    if (singles.length) groups += `<section class="service-line-group"><header class="service-line-head"><h2>خدمات منفردة</h2></header><div class="service-grid">${singles.map(serviceCard).join("")}</div></section>`;
    $("#catalogWrap").innerHTML = groups;
  }
}

function lineMembersForTag(tag, order = []) {
  const available = CATALOG.filter(service => (service.tags || []).includes(tag));
  const byId = new Map(available.map(service => [service.id, service]));
  return [...order.filter(id => byId.has(id)).map(id => byId.get(id)),
    ...available.filter(service => !order.includes(service.id))];
}

function renderServiceLineMembers() {
  const tag = $("#serviceLineTag").value;
  const current = $("#serviceLineId").value
    ? [...document.querySelectorAll("#serviceLineMembers .service-line-member")].map(x => x.dataset.id)
    : [];
  const order = current.length ? current : (SERVICE_LINES.find(line => line.id === $("#serviceLineId").value)?.order || []);
  const members = lineMembersForTag(tag, order);
  $("#serviceLineMembers").innerHTML = members.length ? members.map((service, index) => `
    <div class="service-line-member" data-id="${esc(service.id)}">
      <span class="service-line-number">${index + 1}</span><span>${esc(service.name)}</span>
      <span class="service-line-move">
        <button type="button" class="mini" data-action="moveServiceLineMember" data-id="${esc(service.id)}" data-extra="${dataAttr({direction: "up"})}" ${index ? "" : "disabled"} aria-label="رفع ${esc(service.name)}">↑</button>
        <button type="button" class="mini" data-action="moveServiceLineMember" data-id="${esc(service.id)}" data-extra="${dataAttr({direction: "down"})}" ${index === members.length - 1 ? "disabled" : ""} aria-label="خفض ${esc(service.name)}">↓</button>
      </span>
    </div>`).join("") : `<p class="hint">لا توجد خدمات تحمل هذا الوسم حتى الآن.</p>`;
}

function renderServiceLinesList() {
  $("#serviceLinesList").innerHTML = SERVICE_LINES.length ? SERVICE_LINES.map(line => `
    <div class="service-line-row"><div><strong>${esc(line.name)}</strong><span>${esc(line.lorry_name || "بدون لوري")} · ${line.members.length} خدمة</span></div>
      <div class="actions"><button type="button" class="mini" data-action="editServiceLine" data-id="${esc(line.id)}">تعديل</button>
        <button type="button" class="mini danger" data-action="deleteServiceLine" data-id="${esc(line.id)}" data-extra="${dataAttr({name: line.name})}">حذف</button></div>
    </div>`).join("") : `<p class="hint">لا توجد خطوط سير مسجّلة.</p>`;
}

function openServiceLine(id = null) {
  const line = id ? SERVICE_LINES.find(item => item.id === id) : null;
  $("#serviceLineId").value = line?.id || "";
  $("#serviceLineFormTitle").textContent = line ? "تعديل خط السير" : "خط سير جديد";
  fillSelect($("#serviceLineTag"), [["", "— اختَر وسمًا —"], ...SVC_TAGS.map(tag => [tag, `#${tag}`])]);
  fillSelect($("#serviceLineLorry"), CAMPAIGN_LORRIES);
  $("#serviceLineName").value = line?.name || "";
  $("#serviceLineTag").value = line?.tag || "";
  $("#serviceLineLorry").value = line?.lorry_id || "";
  setTimeInputValue($("#serviceLineAm"), line?.depart_am || "");
  setTimeInputValue($("#serviceLinePm"), line?.depart_pm || "");
  $("#serviceLineMembers").innerHTML = "";
  renderServiceLineMembers();
}

function openServiceLines() {
  renderServiceLinesList();
  openServiceLine(null);
  openModal("serviceLinesModal");
}

ACTIONS.editServiceLine = id => openServiceLine(id);
ACTIONS.moveServiceLineMember = (id, extra) => {
  const node = $("#serviceLineMembers").querySelector(`[data-id="${CSS.escape(id)}"]`);
  const other = node?.[extra.direction === "up" ? "previousElementSibling" : "nextElementSibling"];
  if (node && other) extra.direction === "up" ? node.parentNode.insertBefore(node, other) : node.parentNode.insertBefore(other, node);
  renderServiceLineMembers();
};
ACTIONS.deleteServiceLine = async (id, extra) => {
  if (!(await confirmDialog({title: "حذف خط السير", body: `سيُحذف خط «${extra.name}» فقط، وتظل الخدمات وسجل التشغيل كما هما.`, confirmLabel: "حذف الخط", danger: true}))) return;
  const out = await api(`/api/service-lines/${encodeURIComponent(id)}`, {method: "DELETE", headers: {"Content-Type": "application/json", "X-Requested-With": "fetch",}, body: JSON.stringify({revision: SERVICE_LINES_REVISION})});
  if (!out) return;
  SERVICE_LINES = SERVICE_LINES.filter(line => line.id !== id);
  renderServiceLinesList(); render(); showToast("تم حذف خط السير");
};
$("#manageServiceLinesBtn").onclick = openServiceLines;
$("#newServiceLineBtn").onclick = () => openServiceLine(null);
$("#serviceLineTag").onchange = renderServiceLineMembers;
$("#serviceLineForm").onsubmit = async event => {
  event.preventDefault();
  const id = $("#serviceLineId").value;
  const body = {name: $("#serviceLineName").value.trim(), tag: $("#serviceLineTag").value,
    lorry_id: $("#serviceLineLorry").value, depart_am: $("#serviceLineAm").dataset.hhmm || "",
    depart_pm: $("#serviceLinePm").dataset.hhmm || "",
    order: [...document.querySelectorAll("#serviceLineMembers .service-line-member")].map(node => node.dataset.id),
    revision: SERVICE_LINES_REVISION};
  const out = await api(id ? `/api/service-lines/${encodeURIComponent(id)}` : "/api/service-lines",
    jsonReq(id ? "PATCH" : "POST", body));
  if (!out) return;
  if (id) SERVICE_LINES = SERVICE_LINES.map(line => line.id === id ? out : line);
  else SERVICE_LINES.push(out);
  renderServiceLinesList(); render(); openServiceLine(out.id); showToast("تم حفظ خط السير");
};

function syncCatalogFilters() {
  fillSelect($("#svcKindFilter"), [["", "كل التصنيفات"], ...SVC_KINDS.map(k => [k, k])], true);
  fillSelect($("#svcPeriodFilter"), [["", "كل الفترات"], ...PERIODS.map(p => [p, servicePeriodLabel(p)])], true);
  fillSelect($("#svcTagFilter"), [["", "كل الوسوم"], ...SVC_TAGS.map(t => [t, `#${t}`])], true);
}
["input", "change"].forEach(evt => {
  $("#svcSearch").addEventListener(evt, render);
  $("#svcKindFilter").addEventListener(evt, render);
  $("#svcPeriodFilter").addEventListener(evt, render);
  $("#svcTagFilter").addEventListener(evt, render);
});

/* ---------- نافذة عرض موقع خدمة (منبثقة للعرض بس) ---------- */
const locationImageAlt = (name, i, n) =>
  n > 1 ? `صورة موقع ${name} (${i + 1} من ${n})` : `صورة موقع ${name}`;
function openLocationModal(id) {
  const s = CATALOG.find(x => x.id === id);
  if (!s) return;
  $("#locationModalTitle").textContent = `موقع: ${s.name}`;
  $("#locationModalText").textContent = s.location_text || "";
  $("#locationModalText").classList.toggle("hidden", !s.location_text);
  const images = s.location_images || [];
  $("#locationModalGallery").innerHTML = images.length
    ? images.map((f, i) => `<button type="button" class="location-thumb"
        data-action="zoomLocationImage" data-extra="${dataAttr({filename: f})}"
        aria-label="تكبير ${esc(locationImageAlt(s.name, i, images.length))}">
        <img src="/uploads/service-catalog/${esc(f)}" alt="${esc(locationImageAlt(s.name, i, images.length))}"></button>`).join("")
    : emptyState({compact: true, title: "لا توجد صور موقع مسجّلة بعد"});
  openModal("locationModal");
}
ACTIONS.openLocation = id => openLocationModal(id);
ACTIONS.zoomLocationImage = (id, extra, el) => {
  // src بيتحط قبل فتح النافذة (الصورة مخفية قبلها)؛ والبديل النصي من صورة المصغّرة
  $("#locationZoomImg").alt = el?.querySelector("img")?.alt || "صورة موقع الخدمة";
  $("#locationZoomImg").src = `/uploads/service-catalog/${extra.filename}`;
  openModal("locationZoomModal");
};

async function load() {
  const d = await bootstrap();
  if (!d) return;
  const c = await api("/api/service-catalog");
  if (!c) return;
  CATALOG = c.entries; PERIODS = c.periods; SVC_KINDS = c.kinds; SVC_POST_TYPES = c.post_types;
  SVC_TAGS = c.service_tags || [];
  $("#svcSeedBanner").classList.toggle("hidden", c.seeded);
  syncCatalogFilters();
  const lines = await api("/api/service-lines");
  SERVICE_LINES = lines?.lines || [];
  SERVICE_LINES_REVISION = lines?.revision || "";
  render();

  const s = await api("/api/inspection-schedule");
  if (!s) return;
  INSPECTIONS = s.schedule; INSP_WEEKDAYS = s.weekdays;
  renderInspectionSchedule();
}

function syncCommandVisibility() {
  const on = $("#svcHasCommand").checked;
  $("#svcCommandWrap").classList.toggle("hidden", !on);
  $("#svcHasCommandPick").classList.toggle("is-on", on);
  if (!on) { $("#svcCommandOfficers").value = 0; $("#svcCommandIndividuals").value = 0; }
}
$("#svcHasCommand").onchange = syncCommandVisibility;
function syncReportVisibility() {
  const period = $("#svcPeriod").value;
  $("#svcReportAmWrap").classList.toggle("hidden", period === "ليلية بس");
  $("#svcReportPmWrap").classList.toggle("hidden", period === "صباحية بس");
}
$("#svcPeriod").addEventListener("change", syncReportVisibility);

function renderSvcTagChips() {
  $("#svcTagChips").innerHTML = SVC_ENTRY_TAGS.map((t, i) =>
    `<span class="chip soon">#${esc(t)} <a data-action="removeSvcTag" data-id="${i}">×</a></span>`).join(" ");
}
ACTIONS.removeSvcTag = i => { SVC_ENTRY_TAGS.splice(Number(i), 1); renderSvcTagChips() };
$("#svcTags").addEventListener("keydown", e => {
  if (e.key !== "Enter") return;
  e.preventDefault();
  const v = $("#svcTags").value.trim();
  if (v && !SVC_ENTRY_TAGS.includes(v)) { SVC_ENTRY_TAGS.push(v); renderSvcTagChips() }
  $("#svcTags").value = "";
});

/* ---------- صور الموقع ---------- */
function renderGallery(images) {
  $("#svcImageGallery").innerHTML = images.length
    ? images.map(f => `<div class="svc-thumb-wrap">
        <img src="/uploads/service-catalog/${esc(f)}" alt="">
        <button type="button" class="svc-thumb-del" data-action="deleteServiceImage"
          data-id="${esc($("#svcId").value)}" data-extra="${dataAttr({filename: f})}"
          title="حذف الصورة">×</button>
      </div>`).join("")
    : emptyState({compact: true, title: "لا توجد صور بعد"});
}

function syncEntryEverywhere(entry) {
  const i = CATALOG.findIndex(x => x.id === entry.id);
  if (i >= 0) CATALOG[i] = entry; else CATALOG.push(entry);
  render();
  renderGallery(entry.location_images || []);
}

async function uploadImageBlob(blob, filename) {
  const id = $("#svcId").value;
  if (!id || !blob) return;
  const form = new FormData();
  form.append("image", blob, filename);
  const out = await api(`/api/service-catalog/entries/${encodeURIComponent(id)}/images`,
    {method: "POST", body: form});
  if (!out) return;
  markModalSaved("serviceModal");
  showToast("تم رفع الصورة");
  syncEntryEverywhere(out);
}

ACTIONS.deleteServiceImage = async (id, extra) => {
  if (!(await confirmDialog({
    title: "حذف الصورة",
    body: "ستُحذف الصورة نهائيًا من دليل الخدمة ولا يمكن التراجع عن ذلك.",
    confirmLabel: "حذف الصورة",
    danger: true,
  }))) return;
  const out = await api(`/api/service-catalog/entries/${encodeURIComponent(id)}/images/${encodeURIComponent(extra.filename)}`,
    {method: "DELETE"});
  if (!out) return;
  showToast("تم حذف الصورة");
  syncEntryEverywhere(out);
};

/* الصفحة بتترسم وهي مخفية أحيانًا (تبويب تاني مفتوح، أو النافذة مصغّرة)
   بتخلي رسم الـcanvas يستنى للفريم اللي بعده وممكن يتعلّق لحد ما
   التبويب يبان تاني — مهلة هنا بدل ما المستخدم يفضل مستني من غير أي
   رسالة توضح له إيه اللي بيحصل. */
const PDF_RENDER_TIMEOUT_MS = 15000;
function withTimeout(promise, ms, message) {
  return Promise.race([
    promise,
    new Promise((_, reject) => setTimeout(() => reject(new Error(message)), ms)),
  ]);
}

async function renderPdfPageThumbs(pdf) {
  const wrap = $("#svcPdfPages");
  wrap.innerHTML = "";
  for (let i = 1; i <= pdf.numPages; i++) {
    const page = await pdf.getPage(i);
    const viewport = page.getViewport({scale: 0.35});
    const canvas = document.createElement("canvas");
    canvas.width = viewport.width;
    canvas.height = viewport.height;
    await withTimeout(
      page.render({canvasContext: canvas.getContext("2d"), viewport}).promise,
      PDF_RENDER_TIMEOUT_MS,
      "استغرق رسم صفحات PDF وقتًا أطول من اللازم — تأكد من ظهور هذا التبويب وحاول مرة أخرى.");
    canvas.className = "svc-pdf-thumb";
    canvas.title = `صفحة ${i} — اضغط للاختيار`;
    canvas.onclick = () => pickPdfPage(pdf, i);
    wrap.appendChild(canvas);
  }
  $("#svcPdfPicker").classList.remove("hidden");
}

async function pickPdfPage(pdf, pageNum) {
  const page = await pdf.getPage(pageNum);
  const viewport = page.getViewport({scale: 2});
  const canvas = document.createElement("canvas");
  canvas.width = viewport.width;
  canvas.height = viewport.height;
  await withTimeout(
    page.render({canvasContext: canvas.getContext("2d"), viewport}).promise,
    PDF_RENDER_TIMEOUT_MS,
    "استغرق رسم الصفحة وقتًا أطول من اللازم — تأكد من ظهور هذا التبويب وحاول مرة أخرى.");
  const blob = await new Promise(res => canvas.toBlob(res, "image/png"));
  $("#svcPdfPicker").classList.add("hidden");
  $("#svcPdfPages").innerHTML = "";
  await uploadImageBlob(blob, `page-${pageNum}.png`);
}

$("#svcImageFile").onchange = async e => {
  const file = e.target.files[0];
  e.target.value = "";
  if (!file) return;
  if (file.type === "application/pdf") {
    try { await loadPdfJs() }
    catch (err) { showToast("تعذّر تحميل مكتبة قراءة PDF — تحقق من الاتصال وحاول مرة أخرى.", true); return }
    try {
      const buf = await file.arrayBuffer();
      const pdf = await pdfjsLib.getDocument({data: buf}).promise;
      await renderPdfPageThumbs(pdf);
    } catch (err) {
      showToast(err.message || "تعذّرت قراءة ملف PDF هذا.", true);
    }
    return;
  }
  await uploadImageBlob(file, file.name);
};

/* ---------- نموذج الخدمة ---------- */
function openService(id) {
  const s = id ? CATALOG.find(x => x.id === id) : null;
  $("#svcId").value = id || "";
  $("#serviceModalTitle").textContent = s ? "تعديل خدمة" : "خدمة جديدة";
  $("#svcName").value = s?.name || "";
  fillSelect($("#svcPeriod"), [["", "— اختَر —"], ...PERIODS.map(p => [p, servicePeriodLabel(p)])]);
  $("#svcPeriod").value = s?.period || "";
  fillSelect($("#svcKind"), [["", "— اختَر —"], ...SVC_KINDS.map(k => [k, k])]);
  $("#svcKind").value = s?.kind || "";
  fillSelect($("#svcPostType"), [["", "— اختَر —"], ...SVC_POST_TYPES.map(p => [p, p])]);
  $("#svcPostType").value = s?.post_type || "";
  $("#svcHasCommand").checked = !!s?.has_command;
  $("#svcCommandOfficers").value = s?.command_officers ?? 0;
  $("#svcCommandIndividuals").value = s?.command_individuals ?? 0;
  syncCommandVisibility();
  $("#svcCount").value = s?.count ?? 0;
  $("#svcWeapon").value = s?.weapon || "";
  setTimeInputValue($("#svcReportAm"), s?.report_am || "");
  setTimeInputValue($("#svcReportPm"), s?.report_pm || "");
  syncReportVisibility();
  $("#svcInstructions").value = s?.instructions || "";
  $("#svcLocationText").value = s?.location_text || "";
  $("#svcTagList").innerHTML = SVC_TAGS.map(t => `<option value="${esc(t)}">`).join("");
  SVC_ENTRY_TAGS = [...(s?.tags || [])];
  renderSvcTagChips();

  $("#svcPdfPicker").classList.add("hidden");
  $("#svcPdfPages").innerHTML = "";
  $("#svcImageFile").value = "";
  $("#svcImagesSection").classList.toggle("hidden", !s);
  $("#svcImagesHint").classList.toggle("hidden", !!s);
  if (s) renderGallery(s.location_images || []);

  openModal("serviceModal");
}
ACTIONS.openService = id => openService(id || null);
ACTIONS.deleteService = async (id, extra) => {
  if (!(await confirmDialog({
    title: "حذف الخدمة من الدليل",
    body: `ستُحذف خدمة «${extra.name}» من الدليل نهائيًا، بما في ذلك بياناتها وصورها، ولا يمكن التراجع عن ذلك.`,
    confirmLabel: "حذف الخدمة",
    danger: true,
  }))) return;
  if (await api(`/api/service-catalog/entries/${encodeURIComponent(id)}`, {method: "DELETE"})) {
    showToast("تم الحذف"); load();
  }
};
$("#addServiceBtn").onclick = () => openService(null);

$("#serviceForm").onsubmit = async e => {
  e.preventDefault();
  const body = {
    name: $("#svcName").value.trim(),
    period: $("#svcPeriod").value,
    kind: $("#svcKind").value,
    post_type: $("#svcPostType").value,
    has_command: $("#svcHasCommand").checked,
    command_officers: parseInt($("#svcCommandOfficers").value) || 0,
    command_individuals: parseInt($("#svcCommandIndividuals").value) || 0,
    count: parseInt($("#svcCount").value) || 0,
    weapon: $("#svcWeapon").value.trim(),
    report_am: $("#svcPeriod").value === "ليلية بس" ? "" : ($("#svcReportAm").dataset.hhmm || ""),
    report_pm: $("#svcPeriod").value === "صباحية بس" ? "" : ($("#svcReportPm").dataset.hhmm || ""),
    instructions: $("#svcInstructions").value.trim(),
    location_text: $("#svcLocationText").value.trim(),
    tags: SVC_ENTRY_TAGS,
  };
  const id = $("#svcId").value;
  const out = id
    ? await api(`/api/service-catalog/entries/${encodeURIComponent(id)}`, jsonReq("PATCH", body))
    : await api("/api/service-catalog/entries", jsonReq("POST", body));
  if (!out) return;
  markModalSaved("serviceModal");
  showToast(id ? "تم الحفظ" : "تمت الإضافة — يمكنك إضافة صور الموقع الآن");
  if (id) {
    syncEntryEverywhere(out);
  } else {
    // خدمة جديدة اتحفظت — الفورم يفضل مفتوح بنفس البيانات عشان يقدر
    // يضيف صور الموقع على طول من غير ما يفتح المودال تاني.
    CATALOG.push(out);
    render();
    $("#svcId").value = out.id;
    $("#serviceModalTitle").textContent = "تعديل خدمة";
    $("#svcImagesSection").classList.remove("hidden");
    $("#svcImagesHint").classList.add("hidden");
    renderGallery([]);
  }
};

$("#btnSeedCatalog").onclick = async () => {
  if (!(await api("/api/service-catalog/seed", {method: "POST"}))) return;
  showToast("تم توليد الدليل");
  load();
};

/* ---------- نظام التفتيشات — جدول تفتيشات زيارات الأهالي الأسبوعي ----------
   كل يوم في الأسبوع ليه تفتيشاته الثابتة (اسم + تسليح + عدد مجندين)،
   وبتتحط تلقائيًا على اليومية التفصيلية أول ما يوم الأسبوع ده يتفتح لأول
   مرة (`backend/inspection_schedule.py::seed_board_day`) — هنا إدارة
   الجدول نفسه بس، مش تكليف يوم بعينه. */
const INSP_DEFAULT_WEAPON = "دونك", INSP_DEFAULT_COUNT = 5;

function inspectionRow(weekday, entry) {
  return `<div class="insp-row">
    <span class="insp-name">${esc(entry.name)}</span>
    <div class="insp-bits">
      <div class="insp-tags">
        ${entry.weapon ? `<span class="insp-tag">${esc(entry.weapon)}</span>` : ""}
        <span class="insp-tag">${countLabel(entry.count, "مجند")}</span>
      </div>
      <div class="actions">
        <button class="mini" data-action="openInspection"
          data-extra="${dataAttr({weekday})}" data-id="${esc(entry.id)}">تعديل</button>
        ${rowMenu([{action: "deleteInspection", id: entry.id, extra: {weekday, name: entry.name},
          label: "حذف", danger: true}], {label: "إجراءات التفتيش"})}
      </div>
    </div>
  </div>`;
}

function renderInspectionSchedule() {
  const box = $("#inspectionScheduleBar"); if (!box) return;
  const wasOpen = box.querySelector("details")?.open;
  const total = INSP_WEEKDAYS.reduce((n, day) => n + (INSPECTIONS[day] || []).length, 0);

  box.innerHTML = `
    <details class="settings-fold"${wasOpen ? " open" : ""}>
      <summary>
        <span class="fold-title">نظام التفتيشات</span>
        <span class="fold-now">${total
          ? `${countLabel(total, "تفتيش")} على مدار الأسبوع`
          : "<span class='muted'>لا توجد تفتيشات معرّفة</span>"}</span>
        <span class="fold-hint">تعديل</span>
      </summary>
      <p class="hint generated-hint">تفتيشات تأمين زيارات الأهالي — تُضاف
        تلقائيًا إلى اليومية التفصيلية عند فتح يومها لأول مرة، ثم
        يمكن تعديلها أو إزالتها كأي خانة أخرى دون التأثير في الجدول هنا.</p>
      <div class="insp-days">${INSP_WEEKDAYS.map(day => {
        const entries = INSPECTIONS[day] || [];
        return `<div class="insp-day">
          <h4>${esc(day)}</h4>
          ${entries.length ? entries.map(e => inspectionRow(day, e)).join("")
            : `<p class="muted insp-empty">لا يوجد تفتيش يوم ${esc(day)}</p>`}
          <button type="button" class="mini" data-action="addInspection"
            data-extra="${dataAttr({weekday: day})}">${icon("plus")} إضافة تفتيش</button>
        </div>`;
      }).join("")}</div>
    </details>`;
}

function openInspection(weekday, id) {
  const entry = id ? (INSPECTIONS[weekday] || []).find(e => e.id === id) : null;
  $("#inspWeekday").value = weekday;
  $("#inspId").value = id || "";
  $("#inspectionModalTitle").textContent = entry ? "تعديل تفتيش" : "تفتيش جديد";
  $("#inspectionModalDay").textContent = `يوم ${weekday}`;
  $("#inspName").value = entry?.name || "";
  $("#inspWeapon").value = entry?.weapon ?? INSP_DEFAULT_WEAPON;
  $("#inspCount").value = entry?.count ?? INSP_DEFAULT_COUNT;
  openModal("inspectionModal");
}
ACTIONS.openInspection = (id, extra) => openInspection(extra.weekday, id);
ACTIONS.addInspection = (_id, extra) => openInspection(extra.weekday, null);
ACTIONS.deleteInspection = async (id, extra) => {
  if (!(await confirmDialog({
    title: "حذف التفتيش",
    body: `سيُحذف تفتيش «${extra.name}» من جدول يوم ${extra.weekday} نهائيًا ولا يمكن التراجع عن ذلك.`,
    confirmLabel: "حذف التفتيش",
    danger: true,
  }))) return;
  const out = await api(
    `/api/inspection-schedule/${encodeURIComponent(extra.weekday)}/${encodeURIComponent(id)}`,
    {method: "DELETE"});
  if (!out) return;
  INSPECTIONS[extra.weekday] = (INSPECTIONS[extra.weekday] || []).filter(e => e.id !== id);
  showToast("تم الحذف"); renderInspectionSchedule();
};

$("#inspectionForm").onsubmit = async e => {
  e.preventDefault();
  const weekday = $("#inspWeekday").value;
  const id = $("#inspId").value;
  const body = {
    name: $("#inspName").value.trim(),
    weapon: $("#inspWeapon").value.trim(),
    count: parseInt($("#inspCount").value) || 0,
  };
  const out = id
    ? await api(`/api/inspection-schedule/${encodeURIComponent(weekday)}/${encodeURIComponent(id)}`,
                jsonReq("PATCH", body))
    : await api(`/api/inspection-schedule/${encodeURIComponent(weekday)}`, jsonReq("POST", body));
  if (!out) return;
  const list = INSPECTIONS[weekday] || (INSPECTIONS[weekday] = []);
  if (id) {
    const i = list.findIndex(e => e.id === id);
    if (i >= 0) list[i] = out;
  } else {
    list.push(out);
  }
  showToast(id ? "تم الحفظ" : "تمت الإضافة");
  closeModal("inspectionModal", true);
  renderInspectionSchedule();
};

load();
