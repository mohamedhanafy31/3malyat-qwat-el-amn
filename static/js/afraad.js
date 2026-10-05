/* يومية الأفراد — نفس شكل ورقة «افراد» الحقيقية: جدول واحد متواصل،
   الخدمات الأساسية قايمة مقفولة (نفس أسماء `22-6-2026 افراد.docx`
   بالظبط، من `backend/afraad.py:BASIC_SERVICE_NAMES`) وكل تفاصيلها
   بتتغيّر يوميًا، والخدمات الطارئة (+ أي قسم مخصّص) بتيجي جاهزة من
   اليومية التفصيلية مرتبة بمعاد الانتظام — نفس منطق `board.js`/
   `counts.js` بس بعرض «الدفتر الورقي» زي `/board`. */
let AF = null, DAY = null;
let PERSONNEL_VALUES = new Map();

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
  const options = [];
  for (const person of AF?.personnel || []) {
    const label = personnelLabel(person);
    PERSONNEL_VALUES.set(label, person);
    PERSONNEL_VALUES.set(person.name, person);
    options.push(`<option value="${esc(label)}">${esc(person.phone || "")}</option>`);
  }
  $("#afPersonnelList").innerHTML = options.join("");
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

async function load() {
  const d = await bootstrap();
  if (!d) return;
  loadDay(curDate());
}
load();
