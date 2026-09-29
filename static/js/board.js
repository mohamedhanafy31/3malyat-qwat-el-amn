/* اليومية التفصيلية — أقسام الوورد العشرة على سجل تكليف واحد.
   اسم الخدمة حر بيكتبه المشغّل على الخانة نفسها، والتصنيف (خارجية/داخلية/
   حراسات/طبية) بيتحدد معاه — مفيش كتالوج منفصل يتربط بيه. */
let BOARD = null, DAY = null;
let SECTION_HISTORY = null, SECTION_HISTORY_TIMER = null, SECTION_HISTORY_SEQ = 0;
let SELECTED_ROW_ID = null, MOVING_ROW = false, ENTRY_AFTER_ID = null;

/* زرار «Word» العام (export.js) بيلف أي صفحة كـHTML متلبّس .doc — هنا
   لازم يبقى ملف Word حقيقي بنفس شكل الورقة الرسمية (نفس التقسيمة
   والحدود والتظليل)، فبيتولّد من السيرفر (`backend/board_export.py`)
   بدل نسخ الـHTML الظاهر على الشاشة. */
window.exportDocxUrl = () => `/api/board/${DAY}/export.docx`;

const nameOf = list => p => `${p.role ? p.role + "/ " : ""}${p.name}`;

/* ---------- العرض ---------- */
const chips = (list, cls) => list.map(p =>
  `<span class="chip ${cls}">${esc(nameOf()(p))}</span>`).join(" ");
const conChips = cons => (cons || []).map(c =>
  `<span class="chip w">${esc(c.class || "مجند")}${c.count ? " ×" + c.count : ""}</span>`).join(" ");

const SERVICE_HEAD = ["الخدمة", "القائم بها", "المجندين", "التسليح", "الانتظام", "الجهة", "الإجراء"];

/* الأهداف قايمة مغلقة بترتيب ثابت (مشرف الأهداف + سبعة أهداف)، عكس باقي
   الأقسام — مفيش «+ إضافة» حر ولا حذف. عمودين بس بيتغيّروا:
     قائد الهدف العام     محسوب من منصب الضابط الثابت، بيتغيّر من صفحة
                          بيانات الضابط مش من هنا
     الضابط المعيّن اليوم  تكليف يومي عادي — نفس الشخص أو حد تاني بيغطّي
   مفيش أفراد ولا مجندين ولا تفاصيل خدمة تانية جوّه الهدف. */
const TARGET_HEAD = ["الهدف", "قائد الهدف العام", "الضابط المعيّن اليوم", "الإجراء"];

function targetSlotRow(row) {
  const commander = row.commander?.length
    ? chips(row.commander, "h")
    : `<span class="muted">لسه محدّدش من صفحة بيانات الضابط</span>`;
  const assigned = row.officers.length
    ? chips(row.officers, "m")
    : `<span class="muted">مفيش حد معيّن</span>`;
  return `<tr class="${row.vacant ? "vacant" : ""}">
    <td class="name">${esc(row.label)}</td>
    <td class="wrap">${commander}</td>
    <td class="wrap">${assigned}</td>
    <td class="col-actions"><div class="actions">
      <button class="mini${row.vacant ? " ok" : ""}" data-action="openTargetAssign"
        data-id="${esc(row.name)}" data-extra="${dataAttr({officers: row.officers})}"
      >${row.vacant ? "تعيين" : "تعديل"}</button>
    </div></td></tr>`;
}

/* الكتل الثابتة الثلاثة (ضابط عظيم الإدارة/الأمن/المعسكر الفرعي) — نفس
   فكرة الأهداف بالظبط بس من غير عمود قائد ثابت: اسم القسم نفسه ثابت
   وواحد على الصفّين، فالعمود المتغيّر هو الفترة (صباحية/ليلية) بس. */
const SLOT_HEAD = ["الخدمة", "القائم بها", "الإجراء"];

function slotRow(row, sectionName) {
  const assigned = row.officers.length
    ? chips(row.officers, "m")
    : `<span class="muted">مفيش حد معيّن</span>`;
  return `<tr class="${row.vacant ? "vacant" : ""}">
    <td class="name">${esc(row.shift)}</td>
    <td class="wrap">${assigned}</td>
    <td class="col-actions"><div class="actions">
      <button class="mini${row.vacant ? " ok" : ""}" data-action="openSlotAssign"
        data-id="${esc(sectionName)}"
        data-extra="${dataAttr({shift: row.shift, officers: row.officers})}"
      >${row.vacant ? "تعيين" : "تعديل"}</button>
    </div></td></tr>`;
}

function serviceRow(row) {
  if (row.placeholder) {
    return `<tr class="vacant"><td class="name">${esc(row.shift)}</td>
      <td colspan="5"><span class="muted">شاغرة — محتاجة تكليف</span></td>
      <td class="col-actions"><div class="actions"><button class="mini" data-action="openEntry"
        data-extra="${dataAttr({shift: row.shift})}" aria-label="إضافة">${icon("plus")}</button></div></td></tr>`;
  }
  const who = [chips(row.officers, "m"), chips(row.personnel, "h")].filter(Boolean).join(" ")
    || `<span class='muted'>—</span>`;
  const selected = row.id === SELECTED_ROW_ID;
  return `<tr class="service-row${row.vacant ? " vacant" : ""}${selected ? " is-selected" : ""}"
    data-service-id="${esc(row.id)}" tabindex="-1" aria-selected="${selected}">
    <td class="name">${esc(row.label)}
      ${row.note ? `<div class="sub">${esc(row.note)}</div>` : ""}</td>
    <td class="wrap">${who}</td>
    <td>${conChips(row.conscripts)}${row.conscript_count ? ` <span class="chip w">${countLabel(row.conscript_count, "مجند")}</span>` : ""}
      ${!row.conscripts.length && !row.conscript_count ? "<span class='muted'>—</span>" : ""}</td>
    <td>${esc(row.weapon) || "<span class='muted'>—</span>"}</td>
    <td>${esc(row.time) || "<span class='muted'>—</span>"}</td>
    <td>${esc(row.party) || "<span class='muted'>—</span>"}</td>
    <td class="col-actions"><div class="actions service-actions">
      <button type="button" class="mini btn-xs move" data-action="moveEntry"
        data-id="${esc(row.id)}" data-extra="${dataAttr({direction: "up"})}"
        title="حرّك لفوق" aria-label="تحريك لأعلى">${icon("chevron-up")}</button>
      <button type="button" class="mini btn-xs move" data-action="moveEntry"
        data-id="${esc(row.id)}" data-extra="${dataAttr({direction: "down"})}"
        title="حرّك لتحت" aria-label="تحريك لأسفل">${icon("chevron-down")}</button>
      <button class="mini" data-action="openEntry" data-id="${esc(row.id)}">تعديل</button>
      ${rowMenu([
        {action: "duplicateEntry", id: row.id, label: "تكرار"},
        {action: "deleteEntry", id: row.id, extra: {name: row.label}, label: "حذف", danger: true},
      ], {label: "إجراءات الخدمة"})}
    </div></td></tr>`;
}

/* الأقسام المحسوبة — كل واحد بأعمدته بتاعته زي الوورد */
const OFFICER_VIEWS = {
  "عمل بالإدارة": [["الضابط", "العمل"], r =>
    `<tr><td class="name">${esc(nameOf()(r))}</td><td class="wrap">${esc(r.text) || "<span class='muted'>—</span>"}</td></tr>`],
  "الراحات": [["الضابط", "النوع", "من", "إلى", "العودة"], r =>
    `<tr><td class="name">${esc(nameOf()(r))}</td>
     <td><span class="chip ${r.type === "شهرية" ? "m" : r.type === "نصف شهرية" ? "h" : "w"}">${esc(r.type)}</span></td>
     <td>${fmtShort(r.start)}</td><td>${fmtShort(r.end)}</td>
     <td>${fmtShort(r.return_date)}</td></tr>`],
  "التقصيرات": [["الضابط", "العمل قبل التقصيرة"], r =>
    `<tr><td class="name">${esc(nameOf()(r))}</td><td class="wrap">${esc(r.note)}</td></tr>`],
  "الخوارج": [["الضابط", "السبب", "التفاصيل"], r =>
    `<tr><td class="name">${esc(nameOf()(r))}</td>
     <td><span class="chip taq">${esc(r.reason)}</span></td>
     <td class="wrap">${esc(r.note)}</td></tr>`],
};

const cardTable = (head, rows) => `<div class="mtable-wrap">${mtable(head, rows)}</div>`;

function sectionCard(sec) {
  const count = sec.rows.length;
  let body;
  if (sec.type === "officers") {
    const [head, render] = OFFICER_VIEWS[sec.name];
    body = count ? cardTable(head, sec.rows.map(render)) : `<div class="mempty">لا يوجد</div>`;
  } else if (sec.type === "targets") {
    body = cardTable(TARGET_HEAD, sec.rows.map(targetSlotRow));
  } else if (sec.type === "slots") {
    // الصفّين الثابتين (صباحية/ليلية بالاسم الرسمي) بأسلوب الأهداف —
    // تعيين سريع بس. أي دور تاني ضافه المشغّل بإيده لنفس القسم (`+
    // إضافة» تحت) بيتحط في جدول خدمات عادي تحتهم، عشان يفضل جوّه قسمه
    // الصح مش مضطر يتكتب في قسم تاني (زي الخدمات الطارئة) من غير مكان
    // يتحط فيه هنا.
    const fixed = sec.rows.filter(r => r.slot);
    const extra = sec.rows.filter(r => !r.slot);
    body = cardTable(SLOT_HEAD, fixed.map(r => slotRow(r, sec.name)))
      + (extra.length ? cardTable(SERVICE_HEAD, extra.map(serviceRow)) : "");
  } else {
    body = sec.rows.length ? cardTable(SERVICE_HEAD, sec.rows.map(serviceRow))
      : `<div class="mempty">لا توجد خدمات — اضغط «إضافة» فوق</div>`;
  }
  // الأهداف قايمة مقفولة بس — مفيش «+ إضافة» حر ليها زي الأقسام المحسوبة.
  // الكتل الثابتة عندها الصفّين الثابتين + إمكانية إضافة دور تاني حر.
  const addBtn = ["officers", "targets"].includes(sec.type) ? "" :
    `<button class="mini on-dark" data-action="openEntry"
      data-extra="${dataAttr({section: sec.name})}">${icon("plus")} إضافة</button>`;
  const seededNote = sec.type === "targets" && sec.seeded_from
    ? `<small class="target-default-note">مبدئيًا من تأكيد يوم ${fmt(sec.seeded_from)}</small>`
    : "";
  return `<div class="mcard">
    <h3>${esc(sec.name)}${seededNote}<span class="mcount">${count}</span>${addBtn}</h3>
    ${body}</div>`;
}

/* تنبيهات مش موانع: الأرشيف فيه ضباط على خدمتين في نفس الفترة فعلًا،
   فالفحص بيلفت النظر ومابيمنعش الحفظ. */
const LEVEL_ORDER = ["critical", "warning", "info"];
const LEVEL_LABEL = {critical: "تحذير حرج", warning: "تحذير", info: "معلومة"};
const LEVEL_CLS = {critical: "err", warning: "taq", info: "w"};

function warningsCard(list) {
  if (!list?.length) return "";
  const groups = LEVEL_ORDER.map(lv => ({lv, items: list.filter(w => (w.level || "info") === lv)}))
    .filter(g => g.items.length);
  const body = groups.map(g => `
    <div class="warn-group">
      <div class="warn-group-head"><span class="chip ${LEVEL_CLS[g.lv]}">${LEVEL_LABEL[g.lv]}</span>
        <span class="muted">${g.items.length}</span></div>
      <ul class="alert-list warn-list">${g.items.map(w => `
        <li><span class="w-ico">${icon("alert")}</span>
          <span class="chip taq">${esc(w.kind)}</span> ${esc(w.text)}</li>`).join("")}</ul>
    </div>`).join("");
  return `<div class="alert-card">
    <div class="alert-head"><span class="alert-ico">${icon("alert","ico-lg")}</span><strong>مراجعة اليوم</strong>
      <span class="muted">${list.length} ملاحظة — للفت النظر مش للمنع</span></div>
    ${body}</div>`;
}

/* التقسيمة زي الوورد بالظبط: عمود يمين للخدمات (أساسية/طارئة/عمل
   بالإدارة + أي قسم مخصّص المشغّل ضافه بإيده — نفس نوع «services»)،
   وعمود شمال للأهداف والمحسوبات والكتل الثابتة الثلاثة. */
const RIGHT_COLUMN_SECTIONS = ["الخدمات أساسية", "الخدمات الطارئة", "عمل بالإدارة"];

function splitColumns(sections) {
  const right = [], left = [];
  for (const s of sections) {
    const inRight = RIGHT_COLUMN_SECTIONS.includes(s.name)
      || (s.type === "services" && !RIGHT_COLUMN_SECTIONS.includes(s.name));
    (inRight ? right : left).push(s);
  }
  return [right, left];
}

function render() {
  const wrap = $("#matchBoard");
  if (!BOARD) { wrap.innerHTML = `<div class="empty">جارٍ التحميل...</div>`; return }
  if (SELECTED_ROW_ID && !findRow(SELECTED_ROW_ID)) SELECTED_ROW_ID = null;
  const [right, left] = splitColumns(BOARD.sections);
  wrap.innerHTML = `
    <div class="ledger-board">
      <div class="ledger-head">
        <h2>اليومية التفصيلية</h2>
        <div class="ledger-sub">${dayName(BOARD.date)} الموافق ${fmt(BOARD.date)}</div>
      </div>
      ${warningsCard(BOARD.warnings)}
      <div class="match-grid">
        <div class="match-col">${right.map(sectionCard).join("")}</div>
        <div class="match-col">${left.map(sectionCard).join("")}</div>
      </div>
    </div>`;
}

/* ---------- نموذج الخانة ---------- */
function findRow(id) {
  for (const s of BOARD.sections) {
    const hit = s.rows.find(r => r.id === id);
    if (hit) return hit;
  }
  return null;
}

function selectService(id, {scroll = false, focus = false} = {}) {
  if (!id || !findRow(id)) return;
  SELECTED_ROW_ID = id;
  $$(`#matchBoard tr[data-service-id]`).forEach(row => {
    const selected = row.dataset.serviceId === id;
    row.classList.toggle("is-selected", selected);
    row.setAttribute("aria-selected", String(selected));
  });
  const row = $$("#matchBoard tr[data-service-id]")
    .find(item => item.dataset.serviceId === id);
  if (scroll) row?.scrollIntoView({block: "nearest", behavior: "smooth"});
  if (focus) row?.focus({preventScroll: true});
}

$("#matchBoard").addEventListener("click", e => {
  const row = e.target.closest("tr[data-service-id]");
  if (row) selectService(row.dataset.serviceId);
});

function conRow(c) {
  return `<div class="req-row">
    <input class="con-class" placeholder="الفئة (قتالية/فض/حفظ نظام/رياضي)" value="${esc(c.class || "")}">
    <input class="con-count" type="number" min="0" placeholder="العدد" value="${c.count || ""}">
    <button type="button" class="mini bad" data-action="removeConRow">حذف</button>
  </div>`;
}
function fillMulti(el, people, chosen) {
  el.innerHTML = people.map(p =>
    `<option value="${esc(p.id)}" ${chosen.includes(p.id) ? "selected" : ""}>${esc(nameOf()(p))}</option>`).join("");
}
const readMulti = el => [...el.selectedOptions].map(o => o.value);

function renderShiftToggle() {
  $("#enShift").innerHTML = SHIFTS().map(shift => `<label>
    <input type="radio" name="enShift" value="${esc(shift)}">
    <span>${esc(shift)}</span>
  </label>`).join("");
}

function selectedShift() {
  return $("#enShift input:checked")?.value || "";
}

function selectShift(value) {
  const shifts = SHIFTS();
  const selected = shifts.includes(value) ? value : (shifts[0] || "");
  $$("#enShift input").forEach(input => { input.checked = input.value === selected; });
}

function syncShiftOptions(preferredShift) {
  const isTarget = $("#enKind").value === "حراسات";
  // الأهداف هدف ثابت طول اليوم فمالهاش فترة
  $("#enShiftWrap").classList.toggle("hidden", isTarget);
  if (isTarget) {
    $$("#enShift input").forEach(input => { input.checked = false; });
    return;
  }
  selectShift(preferredShift ?? selectedShift());
}

function hideSectionHistory() {
  SECTION_HISTORY = null;
  const panel = $("#enSectionHistory");
  panel.classList.add("hidden");
  panel.innerHTML = "";
}

function sectionHasDedicatedUi(name) {
  const section = (BOARD?.sections || []).find(item => item.name === name);
  return section && ["targets", "slots", "officers"].includes(section.type);
}

function historyConscriptCount(row) {
  return Number(row.conscript_count) || (row.conscripts || [])
    .reduce((total, item) => total + (Number(item.count) || 0), 0);
}

function renderSectionHistory(history, expanded) {
  const panel = $("#enSectionHistory");
  const rows = history.rows || [];
  if (!history.source_day || !rows.length) { hideSectionHistory(); return }
  SECTION_HISTORY = history;
  panel.innerHTML = `<div class="section-history-head">
      <div class="section-history-summary">آخر خدمات «${esc(history.section)}» يوم
        ${fmt(history.source_day)} <span>— ${rows.length} خدمة</span></div>
      <button type="button" class="mini section-history-toggle"
        aria-expanded="${expanded}">${expanded ? "إخفاء" : "عرض"}</button>
    </div>
    <div class="section-history-details${expanded ? "" : " hidden"}">
      <div class="section-history-list">${rows.map(row => {
        return `<label class="section-history-service">
          <input type="checkbox" class="section-history-choice" value="${esc(row.id)}" checked>
          <span class="section-history-body"><b>${esc(row.name)}</b>
            <span class="section-history-meta">
              <span>الفترة: ${esc(row.shift || "—")}</span>
              <span>التصنيف: ${esc(row.kind || "—")}</span>
              <span>المجندين: ${historyConscriptCount(row)}</span>
              <span>التسليح: ${esc(row.weapon || "—")}</span>
            </span>
          </span>
        </label>`;
      }).join("")}</div>
      <div class="section-history-actions">
        <button type="button" class="mini" id="copySectionHistory"></button>
      </div>
    </div>`;
  panel.classList.remove("hidden");
  panel.querySelectorAll(".section-history-choice").forEach(input =>
    input.addEventListener("change", syncSectionCopyCount));
  panel.querySelector(".section-history-toggle").onclick = toggleSectionHistory;
  $("#copySectionHistory").onclick = copySelectedSectionHistory;
  syncSectionCopyCount();
}

function toggleSectionHistory() {
  const details = $("#enSectionHistory .section-history-details");
  const button = $("#enSectionHistory .section-history-toggle");
  const expanded = details.classList.contains("hidden");
  details.classList.toggle("hidden", !expanded);
  button.textContent = expanded ? "إخفاء" : "عرض";
  button.setAttribute("aria-expanded", String(expanded));
}

function syncSectionCopyCount() {
  const button = $("#copySectionHistory");
  if (!button) return;
  const count = $$("#enSectionHistory .section-history-choice:checked").length;
  button.textContent = `إضافة الخدمات المختارة (${count})`;
  button.disabled = count === 0;
}

function queueSectionHistory(expanded) {
  clearTimeout(SECTION_HISTORY_TIMER);
  const seq = ++SECTION_HISTORY_SEQ;
  hideSectionHistory();
  const section = $("#enSection").value.trim();
  if ($("#enId").value || !section || sectionHasDedicatedUi(section)) return;
  SECTION_HISTORY_TIMER = setTimeout(async () => {
    const out = await api(`/api/board/${DAY}/section-history?section=${encodeURIComponent(section)}`);
    if (seq !== SECTION_HISTORY_SEQ || $("#enId").value
        || $("#enSection").value.trim() !== section) return;
    if (out?.rows?.length) renderSectionHistory(out, expanded);
  }, 180);
}

async function copySelectedSectionHistory() {
  if (!SECTION_HISTORY) return;
  const ids = $$("#enSectionHistory .section-history-choice:checked").map(input => input.value);
  if (!ids.length) { showToast("اختار خدمة واحدة على الأقل", true); return }
  const button = $("#copySectionHistory");
  button.disabled = true;
  const out = await api(`/api/board/${DAY}/section-copy`, jsonReq("POST", {
    section: $("#enSection").value.trim(),
    source_day: SECTION_HISTORY.source_day,
    ids,
  }));
  if (!out) { button.disabled = false; return }
  closeModal("entryModal", true);
  showToast(`تمت إضافة ${out.added} خدمة، واتخطت ${out.skipped} موجودة بالفعل`);
  loadDay(DAY);
}

function openEntry(rowId, preset, duplicate = false) {
  const row = rowId ? findRow(rowId) : null;
  const editingId = duplicate ? "" : rowId || "";
  ENTRY_AFTER_ID = duplicate ? rowId : null;
  $("#enId").value = editingId;
  $("#entryTitle").textContent = duplicate ? "تكرار خدمة" : row ? "تعديل خانة" : "إضافة خانة";

  $("#enName").value = row?.name || "";
  fillSelect($("#enKind"), KINDS().map(x => [x, x]));
  $("#enKind").value = row?.kind || KINDS()[0] || "";
  // القايمة جاية من كل الأيام، والقسم الحالي بيتضاف لها وقت التعديل لو كان
  // هدفًا/كتلة ثابتة قديمة مستبعدة من الاقتراحات العامة. الـcombobox العام
  // بيفتح كل الاختيارات مهما كانت القيمة الحالية ويسمح باسم جديد كمان.
  const currentSection = row?.section || preset?.section || "";
  const sectionOptions = [...(BOARD.section_names || META.service_sections || [])];
  if (currentSection && !sectionOptions.includes(currentSection)) sectionOptions.push(currentSection);
  fillSelect($("#enSection"), sectionOptions.map(x => [x, x]));
  $("#enSection").value = currentSection || sectionOptions[1] || sectionOptions[0] || "";
  renderShiftToggle();
  syncShiftOptions(row?.shift ?? preset?.shift ?? SHIFTS()[0] ?? "");
  // الاختيار بيقتصر على اللي كانوا على القوة في يوم اللوحة المفتوح بس —
  // مش كل ضابط/فرد اتسجّل في السيستم يومًا. لو الخانة بتتعدّل ولسه فيها
  // شخص اتشال من القوة بعد كده، بيتضاف لقايمة الاختيار برضه (بدل ما
  // يختفي من غير ما ننبّه حد) عشان الحفظ ما يمسحوش من الخانة بالغلط.
  const roster = BOARD.roster || {officers: [], personnel: []};
  const withCurrent = (list, current) => {
    const extra = (current || []).filter(c => !list.some(p => p.id === c.id));
    return [...list, ...extra];
  };
  const currentOfficers = duplicate ? [] : row?.officers || [];
  const currentPersonnel = duplicate ? [] : row?.personnel || [];
  fillMulti($("#enOfficers"), withCurrent(roster.officers, currentOfficers),
            currentOfficers.map(o => o.id));
  fillMulti($("#enPersonnel"), withCurrent(roster.personnel, currentPersonnel),
            currentPersonnel.map(p => p.id));
  // الاختيار مقفول وراه checkbox — الخانة تنفع تفضل من غير ضابط أو فرد،
  // فالمربّعين دول بيبانوا بس لو الخانة فعلًا فيها رئاسة (تعديل) أو
  // المستخدم فعّلها بنفسه (إضافة).
  $("#enHasOfficers").checked = !!currentOfficers.length;
  $("#enHasPersonnel").checked = !!currentPersonnel.length;
  syncCommandWraps();
  $("#conRows").innerHTML = (row?.conscripts || []).map(conRow).join("");
  $("#enConCount").value = row?.conscript_count || "";
  $("#enWeapon").value = row?.weapon || "";
  $("#enTime").value = row?.time || "";
  $("#enParty").value = row?.party || "";
  $("#enNote").value = row?.note || "";
  openModal("entryModal");
  queueSectionHistory(false);
}

function syncCommandWraps() {
  const officersOn = $("#enHasOfficers").checked, personnelOn = $("#enHasPersonnel").checked;
  $("#enOfficersWrap").classList.toggle("hidden", !officersOn);
  $("#enPersonnelWrap").classList.toggle("hidden", !personnelOn);
  $("#enHasOfficersPick").classList.toggle("is-on", officersOn);
  $("#enHasPersonnelPick").classList.toggle("is-on", personnelOn);
}
$("#enHasOfficers").addEventListener("change", syncCommandWraps);
$("#enHasPersonnel").addEventListener("change", syncCommandWraps);

ACTIONS.openEntry = (id, extra) => openEntry(id || null, extra);
ACTIONS.duplicateEntry = id => openEntry(id, {section: findRow(id)?.section}, true);

async function deleteService(id, name) {
  if (!(await confirmDialog({
    title: "حذف الخدمة من اليومية",
    body: `ستُحذف خدمة «${name}» من يومية ${fmt(DAY)} نهائيًا ولا يمكن التراجع عن ذلك.`,
    confirmLabel: "حذف الخدمة",
    danger: true,
  }))) return;
  if (await api(`/api/assignments/${DAY}/${encodeURIComponent(id)}`, {method: "DELETE"})) {
    showToast("تم الحذف"); loadDay(DAY);
  }
}
ACTIONS.deleteEntry = (id, extra) => deleteService(id, extra.name);

async function moveService(id, direction) {
  if (MOVING_ROW) return;
  MOVING_ROW = true;
  SELECTED_ROW_ID = id;
  const out = await api(`/api/assignments/${DAY}/${encodeURIComponent(id)}/move`,
                        jsonReq("POST", {direction}));
  MOVING_ROW = false;
  if (!out) return;
  BOARD = out;
  render();
  renderConfirmBadge();
  requestAnimationFrame(() => selectService(id, {scroll: true, focus: true}));
}
ACTIONS.moveEntry = (id, extra) => moveService(id, extra.direction);
ACTIONS.removeConRow = (id, extra, el) => el.closest(".req-row").remove();

$("#addConRow").onclick = () => $("#conRows").insertAdjacentHTML("beforeend", conRow({}));
$("#enKind").addEventListener("change", () => syncShiftOptions());
$("#enSection").addEventListener("input", () => queueSectionHistory(true));
$("#enSection").addEventListener("change", () => queueSectionHistory(true));

$("#entryForm").onsubmit = async e => {
  e.preventDefault();
  const conscripts = $$("#conRows .req-row").map(r => ({
    class: r.querySelector(".con-class").value.trim(),
    count: parseInt(r.querySelector(".con-count").value) || 0,
  })).filter(c => c.class || c.count);
  const body = {
    name: $("#enName").value.trim(),
    kind: $("#enKind").value,
    section: $("#enSection").value.trim(),
    shift: selectedShift(),
    officer_ids: $("#enHasOfficers").checked ? readMulti($("#enOfficers")) : [],
    personnel_ids: $("#enHasPersonnel").checked ? readMulti($("#enPersonnel")) : [],
    conscripts,
    conscript_count: parseInt($("#enConCount").value) || 0,
    weapon: $("#enWeapon").value.trim(),
    time: $("#enTime").value.trim(),
    party: $("#enParty").value.trim(),
    note: $("#enNote").value.trim(),
  };
  const id = $("#enId").value;
  if (!id && ENTRY_AFTER_ID) body.after_id = ENTRY_AFTER_ID;
  const out = id
    ? await api(`/api/assignments/${DAY}/${encodeURIComponent(id)}`, jsonReq("PATCH", body))
    : await api(`/api/assignments/${DAY}`, jsonReq("POST", body));
  if (!out) return;
  SELECTED_ROW_ID = out.id;
  closeModal("entryModal", true); showToast(id ? "تم حفظ التعديلات" : "تمت الإضافة");
  loadDay(DAY);
};

/* ---------- تعيين ضابط بهدف/فترة كتلة ثابتة ----------
   الأهداف والكتل الثابتة قوائم مقفولة — التعديل الوحيد هو مين معيّن،
   فمودال منفصل صغير بدل مودال الخانة العام (مالوش تصنيف ولا قوام).
   المودال والفورم متشاركين بين الاتنين، والفرق بس نقطة الحفظ
   (`#tgEndpoint`) وظهور ملاحظة قائد الهدف. */
function _openAssignModal(endpoint, title, extra, showCommanderNote) {
  const roster = BOARD.roster || {officers: []};
  const current = (extra.officers || []).filter(c => !roster.officers.some(p => p.id === c.id));
  $("#tgEndpoint").value = endpoint;
  $("#targetModalTitle").textContent = title;
  $("#tgCommanderNote").classList.toggle("hidden", !showCommanderNote);
  fillMulti($("#tgOfficers"), [...roster.officers, ...current],
            (extra.officers || []).map(o => o.id));
  openModal("targetModal");
}

function openTargetAssign(name, extra) {
  _openAssignModal(`/api/board/${DAY}/target/${encodeURIComponent(name)}`,
                   `تعيين هدف «${name}»`, extra, true);
}
ACTIONS.openTargetAssign = (name, extra) => openTargetAssign(name, extra);

function openSlotAssign(section, extra) {
  _openAssignModal(
    `/api/board/${DAY}/slot/${encodeURIComponent(section)}/${encodeURIComponent(extra.shift)}`,
    `تعيين «${section}» (${extra.shift})`, extra, false);
}
ACTIONS.openSlotAssign = (section, extra) => openSlotAssign(section, extra);

$("#targetForm").onsubmit = async e => {
  e.preventDefault();
  const officer_ids = readMulti($("#tgOfficers"));
  const out = await api($("#tgEndpoint").value, jsonReq("PUT", {officer_ids}));
  if (!out) return;
  BOARD = out; closeModal("targetModal", true); showToast("تم الحفظ"); render();
};

/* ---------- حفظ ↔ تأكيد ----------
   الحفظ بيكتب في اليومية على طول وبيظهر في كل العروض (يومية الضباط، دفتر
   ٤٣، اعداد الخدمات) — بس مابيسجّلش حاجة. التأكيد هو اللي بيعتمد الوضع
   الحالي ويسجّل الفرق عن آخر تأكيد في سجل التغييرات بلحظة الضغط. */
function renderConfirmBadge() {
  const c = BOARD?.confirm;
  const badge = $("#confirmBadge");
  if (!badge) return;
  if (!c) { badge.innerHTML = ""; return }
  if (!c.confirmed) {
    badge.innerHTML = `<span class="chip taq" title="اليومية دي لسه ما اتأكدتش ولا مرة">لسه ما اتأكدتش</span>`;
  } else if (c.pending) {
    badge.innerHTML = `<span class="chip err" title="آخر تأكيد ${esc(c.at || "")}">فيه تعديلات غير مؤكدة</span>`;
  } else {
    const time = (c.at || "").split("T")[1]?.slice(0, 5) || "";
    badge.innerHTML = `<span class="chip on">مؤكدة${time ? " " + time : ""}${c.by ? " — " + esc(c.by) : ""}</span>`;
  }
}

$("#btnConfirmDay").onclick = async () => {
  const c = BOARD?.confirm;
  const extra = c?.confirmed && !c.pending
    ? " لم تُجرَ تغييرات منذ آخر تأكيد، وسيُسجَّل هذا الإجراء بوصفه إعادة تأكيد."
    : "";
  if (!(await confirmDialog({
    title: "تأكيد اليومية",
    body: `هل تريد تأكيد يومية ${fmt(DAY)}؟ سيتم تسجيل التغييرات الحالية في سجل التغييرات.${extra}`,
    confirmLabel: "تأكيد اليومية",
  }))) return;
  const by = ($("#editedBy")?.value || "").trim();
  const out = await api(`/api/board/${DAY}/confirm`, jsonReq("POST", {confirmed_by: by}));
  if (!out) return;
  showToast(out.first ? "اتأكدت اليومية لأول مرة"
            : out.changes ? `اتأكدت اليومية — ${out.changes} تغيير اتسجّل`
            : "اتأكدت اليومية — من غير تغييرات");
  loadDay(DAY);
};

/* ---------- تنقّل الأيام ---------- */
async function loadDay(day) {
  const b = await api(`/api/board/${day}`); if (!b) return;
  if (DAY && day !== DAY) SELECTED_ROW_ID = null;
  BOARD = b; DAY = day; $("#dutyDate").value = day; setPageDay(day); render();
  renderRestStrip($("#restStrip"), day);
  renderConfirmBadge();
  loadDayStatus();
}
const shiftDay = n => loadDay(addDays($("#dutyDate").value || curDate(), n));
$("#dayPrev").onclick = () => shiftDay(-1);
$("#dayNext").onclick = () => shiftDay(1);
$("#dayToday").onclick = () => loadDay(curDate());
$("#dutyDate").onchange = () => loadDay($("#dutyDate").value);
$("#btnShortcuts").onclick = () => openModal("shortcutsModal");

/* اختصارات اللوحة بتشتغل على الصف المختار، وبالحروف الفيزيائية (`code`)
   عشان مكان المفتاح يفضل ثابت حتى لو لوحة المفاتيح عربي. */
function selectableRows() {
  const seen = new Set();
  return $$("#matchBoard tr[data-service-id]").filter(row => {
    if (seen.has(row.dataset.serviceId)) return false;
    seen.add(row.dataset.serviceId);
    return true;
  });
}

function stepSelection(delta) {
  const rows = selectableRows();
  if (!rows.length) return;
  let index = rows.findIndex(row => row.dataset.serviceId === SELECTED_ROW_ID);
  if (index < 0) index = delta > 0 ? -1 : rows.length;
  index = Math.max(0, Math.min(rows.length - 1, index + delta));
  selectService(rows[index].dataset.serviceId, {scroll: true, focus: true});
}

function focusIsInteractive(target) {
  return target?.isContentEditable || !!target?.closest?.(
    'button, a[href], input, select, textarea, [contenteditable], [role="menuitem"], [role="menu"], ' +
    '[role="option"], [role="tab"], [role="combobox"]'
  );
}

function shortcutPopupOpen() {
  return !rowMenuPop.classList.contains("hidden")
    || !comboPop.classList.contains("hidden")
    || !datePopover.classList.contains("hidden");
}

document.addEventListener("keydown", e => {
  const entryOpen = !$("#entryModal").classList.contains("hidden");
  if (entryOpen && e.ctrlKey && e.key === "Enter") {
    e.preventDefault();
    $("#entryForm").requestSubmit();
    return;
  }
  if ($$(".modal:not(.hidden)").length || focusIsInteractive(e.target)
      || shortcutPopupOpen() || e.defaultPrevented) return;

  const moveCombo = (e.ctrlKey && e.altKey && !e.shiftKey)
    || (e.altKey && e.shiftKey && !e.ctrlKey);
  if (moveCombo && (e.code === "ArrowUp" || e.code === "ArrowDown")) {
    e.preventDefault();
    if (SELECTED_ROW_ID) moveService(SELECTED_ROW_ID, e.code === "ArrowUp" ? "up" : "down");
    return;
  }
  if (e.ctrlKey || e.altKey || e.metaKey) return;

  if (e.code === "ArrowUp" || e.code === "ArrowDown") {
    e.preventDefault();
    stepSelection(e.code === "ArrowUp" ? -1 : 1);
  } else if (e.code === "Enter" || e.code === "KeyE") {
    if (!SELECTED_ROW_ID) return;
    e.preventDefault(); openEntry(SELECTED_ROW_ID);
  } else if (e.code === "KeyD") {
    if (!SELECTED_ROW_ID) return;
    e.preventDefault(); openEntry(SELECTED_ROW_ID, {section: findRow(SELECTED_ROW_ID)?.section}, true);
  } else if (e.code === "Delete") {
    if (!SELECTED_ROW_ID) return;
    e.preventDefault(); deleteService(SELECTED_ROW_ID, findRow(SELECTED_ROW_ID)?.label || "الخدمة");
  } else if (e.code === "KeyN") {
    e.preventDefault();
    openEntry(null, {section: findRow(SELECTED_ROW_ID)?.section || "الخدمات الطارئة"});
  } else if (e.code === "PageUp" || e.code === "PageDown") {
    e.preventDefault(); shiftDay(e.code === "PageUp" ? -1 : 1);
  } else if (e.code === "KeyT") {
    e.preventDefault(); loadDay(curDate());
  } else if (e.shiftKey && e.code === "Slash") {
    e.preventDefault(); openModal("shortcutsModal");
  }
});

/* إغلاق اليوم: أي يوم فات بيتقفل لوحده الساعة ١٢ بالليل، والقفل بالإيد
   لليوم الحالي بس (قفل بدري). يوم مقفول بيرفض أي تعديل من الباك إند
   (409) — الزراير هنا واجهة، الحارس الحقيقي في السيرفر.
   الفتح الاستثنائي صالح النهاردة بس وبعدين اليوم بيرجع يتقفل تلقائي. */
async function loadDayStatus() {
  const s = await api(`/api/day-status/${DAY}`);
  if (!s) return;
  const badge = $("#dayLockBadge");
  if (s.closed) {
    const why = s.auto ? "اتقفل تلقائيًا الساعة 12 بالليل"
                       : `اتقفل بالإيد${s.closed_by ? " — " + s.closed_by : ""}`;
    badge.innerHTML = `<span class="chip err" title="${esc(why)}">${icon("lock")} مقفول</span>
      <button class="mini" id="btnReopenDay">فتح استثنائي</button>`;
    $("#btnReopenDay").onclick = reopenDay;
  } else if (s.reopened) {
    badge.innerHTML = `<span class="chip taq"
        title="الفتح الاستثنائي صالح النهاردة بس — اليوم هيرجع يتقفل تلقائي الساعة 12">
        ${icon("unlock")} مفتوح استثنائيًا النهاردة</span>`;
  } else if (s.stage === "not_open") {
    badge.innerHTML = `<span class="chip w" title="يوم جاي — لسه معدّاش عليه دوره، بس التجهيز المسبق مسموح">
        ⏳ لسة متفتحش</span>
      <button class="mini" id="btnCloseDay" title="قفل اليوم مقدّم قبل ما يجيله دوره">قفل اليوم بدري</button>`;
    $("#btnCloseDay").onclick = closeDay;
  } else {
    badge.innerHTML = `<span class="chip on" title="النهاردة — مفتوح للتعديل"><span class="status-dot ok" aria-hidden="true"></span> مفتوح</span>
      <button class="mini" id="btnCloseDay"
      title="اليوم بيتقفل لوحده الساعة 12 بالليل — الزرار ده للقفل بدري">قفل اليوم بدري</button>`;
    $("#btnCloseDay").onclick = closeDay;
  }
}
async function closeDay() {
  if (!(await confirmDialog({
    title: "إغلاق اليومية مبكرًا",
    body: `سيُغلق يوم ${fmt(DAY)}، وسيتطلب أي تعديل لاحق فتحًا استثنائيًا.`,
    confirmLabel: "إغلاق اليوم",
    danger: true,
  }))) return;
  const name = ($("#editedBy")?.value || "").trim();
  if (!(await api(`/api/day-status/${DAY}/close`, jsonReq("POST", {closed_by: name})))) return;
  showToast("اتقفل اليوم"); loadDayStatus();
}
async function reopenDay() {
  const reason = await reasonDialog({
    title: "فتح اليومية استثنائيًا",
    body: `سيُفتح يوم ${fmt(DAY)} للتعديل حتى نهاية اليوم الحالي فقط، وسيُسجَّل السبب في سجل التغييرات.`,
    label: "سبب الفتح الاستثنائي",
    confirmLabel: "فتح اليوم",
  });
  if (!reason) return;
  const by = ($("#editedBy")?.value || "").trim();
  if (!(await api(`/api/day-status/${DAY}/reopen`, jsonReq("POST", {reason, reopened_by: by})))) return;
  showToast("اتفتح اليوم — لغاية آخر النهاردة"); loadDayStatus();
}

/* تنبيه تسليم واستلام: مين هيبدأ راحته بكرة (تقصيرته النهاردة) وكان
   بيشتغل إيه، عشان يتكلّف بديل — من غير ما ننسخ التكليفات تلقائي. */
$("#dayTomorrow").onclick = async () => {
  const today = curDate(), tmr = addDays(today, 1);
  await loadDay(tmr);
  // الكارت القديم بيتشال الأول — الضغط مرتين كان بيكدّس نسخ متطابقة فوق بعض
  $$("#matchBoard .handover-card").forEach(el => el.remove());
  const boot = await api("/api/bootstrap/dashboard");
  const leaving = (boot?.alerts || []).filter(a => a.taqseera_date === today);
  if (!leaving.length) return;
  const todayBoard = await api(`/api/board/${today}`);
  const rows = leaving.map(a => {
    let service = "بدون خدمة مسجلة النهاردة";
    for (const sec of todayBoard?.sections || []) {
      const hit = sec.rows.find(r => (r.officers || []).some(o => o.id === a.id));
      if (hit) { service = hit.label; break }
    }
    return `<li><span class="a-name">${esc(a.role)} / ${esc(a.name)}</span>
      <span class="a-mid">في راحة (${esc(a.type)}) بداية من بكرة</span>
      <span class="a-rest">كان بيشتغل: ${esc(service)}</span></li>`;
  });
  $("#matchBoard").insertAdjacentHTML("afterbegin", `<div class="alert-card handover-card">
    <div class="alert-head"><span class="alert-ico">↷</span><strong>تسليم واستلام بكرة</strong>
      <span class="muted">${leaving.length} ضابط هيبدأ راحته بكرة — محتاجين تكليف بديل على خدمتهم</span></div>
    <ul class="alert-list">${rows.join("")}</ul></div>`);
};

async function load() {
  const d = await bootstrap();
  if (!d) return;
  const days = d.days || [];
  loadDay(days.includes(curDate()) ? curDate() : (days[days.length - 1] || curDate()));
}
load();
