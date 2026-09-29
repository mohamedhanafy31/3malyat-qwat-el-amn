/* يومية الأفراد — نفس شكل ورقة «افراد» الحقيقية: جدول واحد متواصل،
   الخدمات الأساسية قايمة مقفولة (نفس أسماء `22-6-2026 افراد.docx`
   بالظبط، من `backend/afraad.py:BASIC_SERVICE_NAMES`) وكل تفاصيلها
   بتتغيّر يوميًا، والخدمات الطارئة (+ أي قسم مخصّص) بتيجي جاهزة من
   اليومية التفصيلية مرتبة بمعاد الانتظام — نفس منطق `board.js`/
   `counts.js` بس بعرض «الدفتر الورقي» زي `/board`. */
let AF = null, DAY = null;

/* زرار «Word» العام (export.js) بيلف الـHTML الظاهر — هنا لازم يبقى
   ملف Word حقيقي بنفس شكل ورقة «افراد» الحقيقية، فبيتولّد من السيرفر
   (`backend/afraad_export.py`) بدل نسخ الشاشة، نفس فكرة board.js. */
window.exportDocxUrl = () => `/api/afraad/${DAY}/export.docx`;

function personCell(p) {
  if (!p?.name && !p?.phone) return `<span class="muted">شاغرة</span>`;
  return `${esc(p.name) || "<span class='muted'>—</span>"}${p.phone ? `<div class="sub">${esc(p.phone)}</div>` : ""}`;
}

function basicRow(r) {
  return `<tr>
    <td class="name">${esc(r.name)}</td>
    <td>${personCell(r.morning)}</td>
    <td>${personCell(r.night)}</td>
    <td>${r.count || "<span class='muted'>—</span>"}</td>
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
    || `<span class="muted">${esc(r.vacant ? "شاغرة" : "—")}</span>`;
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
  if (!AF) { wrap.innerHTML = `<div class="empty">جارٍ التحميل...</div>`; return }
  wrap.innerHTML = `
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
          : `<div class="mempty">لا توجد خدمات طارئة اليوم — تُكتب من اليومية التفصيلية</div>`}
      </div>
    </div>`;
}

async function loadDayStatus() {
  const s = await api(`/api/day-status/${DAY}`);
  if (!s) return;
  const badge = $("#dayLockBadge");
  if (s.closed) {
    badge.innerHTML = `<span class="chip err">${icon("lock")} مقفول${s.auto ? " (تلقائي)" : ""}</span>`;
  } else if (s.stage === "not_open") {
    badge.innerHTML = `<span class="chip w">⏳ لسة متفتحش</span>`;
  } else {
    badge.innerHTML = `<span class="chip on"><span class="status-dot ok" aria-hidden="true"></span> مفتوح</span>`;
  }
}

async function loadDay(day) {
  const v = await api(`/api/afraad/${day}`);
  if (!v) return;
  AF = v; DAY = day; $("#dutyDate").value = day; render();
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
  $("#afMorningName").value = row.morning.name || "";
  $("#afMorningPhone").value = row.morning.phone || "";
  $("#afNightName").value = row.night.name || "";
  $("#afNightPhone").value = row.night.phone || "";
  $("#afCount").value = row.count || "";
  $("#afWeapon").value = row.weapon || "";
  $("#afSchedule").value = row.schedule || "";
  openModal("afEntryModal");
}
ACTIONS.openAfEntry = id => openAfEntry(id);

$("#afEntryForm").onsubmit = async e => {
  e.preventDefault();
  const id = $("#afEntryId").value;
  const body = {
    morning_name: $("#afMorningName").value.trim(),
    morning_phone: $("#afMorningPhone").value.trim(),
    night_name: $("#afNightName").value.trim(),
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
