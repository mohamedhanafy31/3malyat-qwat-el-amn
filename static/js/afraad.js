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
  $("#afBasicList").innerHTML = (AF.basic || []).map(row => `<div class="list-row"><span>${esc(row.name)}</span><button type="button" class="mini bad" data-basic-remove="${esc(row.id)}">حذف</button></div>`).join("");
}

$("#afBasicOpen").onclick = () => { renderBasicModal(); openModal("afBasicModal"); };
$("#afBasicList").onclick = async event => {
  const button = event.target.closest("[data-basic-remove]");
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

function ocrOptions(items, selected, label) {
  return `<option value="">— ${esc(label)} —</option>` + (items || []).map(item => {
    const text = item.role ? `${item.role}/ ${item.name}` : item.name;
    return `<option value="${esc(item.id)}"${item.id === selected ? " selected" : ""}>${esc(text)}</option>`;
  }).join("");
}

function renderOcrPreview() {
  const summary = AF_OCR?.summary || {};
  $("#afOcrSummary").innerHTML = `<div class="status af-ocr-summary">
    <div><span class="label">الخلايا</span><strong>${AF_OCR?.grid?.cell_count || 0}</strong></div>
    <div><span class="label">الخدمات المطابقة</span><strong>${summary.matched_services || 0}</strong></div>
    <div><span class="label">الأفراد المطابقون</span><strong>${summary.matched_people || 0}</strong></div>
    <div><span class="label">ثقة الشبكة</span><strong>${Math.round((AF_OCR?.grid?.confidence || 0) * 100)}%</strong></div>
  </div>`;
  const overlay = $("#afOcrOverlay");
  if (AF_OCR?.overlay_png) { overlay.src = AF_OCR.overlay_png; overlay.classList.remove("hidden"); }
  else { overlay.removeAttribute("src"); overlay.classList.add("hidden"); }

  const services = AF?.basic || [], personnel = AF?.personnel || [];
  const rows = AF_OCR?.rows || [];
  $("#afOcrRows").innerHTML = rows.length ? `<div class="table-wrap"><table class="af-ocr-table">
    <thead><tr><th>اختيار</th><th>الخدمة المقروءة</th><th>الخدمة المطابقة</th><th>الصباحية</th><th>الليلية</th></tr></thead>
    <tbody>${rows.map((row, index) => `<tr data-ocr-row="${index}">
      <td><input type="checkbox" data-ocr-use${row.auto_selected ? " checked" : ""} aria-label="استيراد الصف"></td>
      <td><b>${esc(row.service || "—")}</b><small>${Math.round((row.service_score || 0) * 100)}%</small></td>
      <td><select data-ocr-service>${ocrOptions(services, row.service_id, "اختر الخدمة")}</select></td>
      <td><span class="af-ocr-read">${esc(row.morning || "—")}</span>
        <select data-ocr-morning>${ocrOptions(personnel, row.morning_match?.id || "", "اختر الفرد")}</select></td>
      <td><span class="af-ocr-read">${esc(row.evening || "—")}</span>
        <select data-ocr-night>${ocrOptions(personnel, row.night_match?.id || "", "اختر الفرد")}</select></td>
    </tr>`).join("")}</tbody></table></div>`
    : emptyState({title: "لم تُستخرج صفوف قابلة للتسكين", hint: "راجع صورة الشبكة والملاحظات، ثم أعد التصوير بوضوح."});
  const warnings = [...(AF_OCR?.warnings || []), ...(AF_OCR?.grid?.warnings || [])];
  $("#afOcrWarnings").innerHTML = warnings.length
    ? `<div class="alert warn"><b>ملاحظات المراجعة</b><ul>${[...new Set(warnings)].map(v => `<li>${esc(v)}</li>`).join("")}</ul></div>` : "";
  $("#afOcrApply").disabled = !rows.length;
}

$("#afOcrOpen").onclick = () => $("#afOcrImage").click();
$("#afOcrImage").onchange = async event => {
  const file = event.target.files?.[0];
  if (!file || !DAY) return;
  const body = new FormData(); body.append("image", file);
  const out = await api(`/api/afraad/${DAY}/ocr/preview`, {
    method: "POST", body, timeoutMs: 190000, loadingLabel: "جاري قراءة صورة اليومية…",
  });
  event.target.value = "";
  if (!out) return;
  AF_OCR = out; renderOcrPreview(); openModal("afOcrModal");
};

$("#afOcrApply").onclick = async () => {
  const rows = $$("#afOcrRows tr[data-ocr-row]").filter(row => row.querySelector("[data-ocr-use]").checked)
    .map(row => ({
      service_id: row.querySelector("[data-ocr-service]").value,
      morning_person_id: row.querySelector("[data-ocr-morning]").value,
      night_person_id: row.querySelector("[data-ocr-night]").value,
    })).filter(row => row.service_id && (row.morning_person_id || row.night_person_id));
  if (!rows.length) { showToast("اختر صفًا واحدًا على الأقل وحدد الفرد.", true); return; }
  const out = await api(`/api/afraad/${DAY}/ocr/apply`, jsonReq("POST", {
    revision: AF_OCR?.revision || AF?.revision, rows,
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
