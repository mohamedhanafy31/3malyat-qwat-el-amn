/* اليومية التفصيلية — أقسام الوورد العشرة على سجل تكليف واحد.
   الخدمة بتتختار من الكتالوج بالـid: الاسم الحر كان بيكسر الربط في صمت
   ويسيب الضابط في «الصافي» من غير أي تنبيه. */
let BOARD = null, DAY = null, SERVICES = [], OFFICERS = [], PERSONNEL = [], ENTRY_TAGS = [];

const svcById = id => SERVICES.find(s => s.id === id);
const nameOf = list => p => `${p.role ? p.role + "/ " : ""}${p.name}`;

/* ---------- العرض ---------- */
const chips = (list, cls) => list.map(p =>
  `<span class="chip ${cls}">${esc(nameOf()(p))}</span>`).join(" ");
const conChips = cons => (cons || []).map(c =>
  `<span class="chip w">${esc(c.class || "مجند")}${c.count ? " ×" + c.count : ""}</span>`).join(" ");
const tagChips = tags => (tags || []).map(t => `<span class="chip soon">#${esc(t)}</span>`).join(" ");

const SERVICE_HEAD = ["الخدمة", "القائم بها", "المجندين", "التسليح", "الانتظام", "الجهة", "الإجراء"];

function serviceRow(row) {
  if (row.placeholder) {
    return `<tr class="vacant"><td class="name">${esc(row.shift)}</td>
      <td colspan="5"><span class="muted">شاغرة — محتاجة تكليف</span></td>
      <td><div class="actions"><button class="mini ok" data-action="openEntry"
        data-extra="${dataAttr({shift: row.shift})}">＋</button></div></td></tr>`;
  }
  const who = [chips(row.officers, "m"), chips(row.personnel, "h")].filter(Boolean).join(" ")
    || `<span class='muted'>—</span>`;
  return `<tr class="${row.vacant ? "vacant" : ""}">
    <td class="name">${esc(row.label)}${row.tags.length ? " " + tagChips(row.tags) : ""}
      ${row.note ? `<div class="sub">${esc(row.note)}</div>` : ""}</td>
    <td class="wrap">${who}</td>
    <td>${conChips(row.conscripts) || "<span class='muted'>—</span>"}</td>
    <td>${esc(row.weapon) || "<span class='muted'>—</span>"}</td>
    <td>${esc(row.time) || "<span class='muted'>—</span>"}</td>
    <td>${esc(row.party) || "<span class='muted'>—</span>"}</td>
    <td><div class="actions">
      <button class="mini" data-action="openEntry" data-id="${esc(row.id)}">تعديل</button>
      <button class="mini bad" data-action="deleteEntry" data-id="${esc(row.id)}"
        data-extra="${dataAttr({name: row.label})}">حذف</button>
    </div></td></tr>`;
}

/* الأقسام المحسوبة — كل واحد بأعمدته بتاعته زي الوورد */
const OFFICER_VIEWS = {
  "عمل بالإدارة": [["الضابط", "العمل"], r =>
    `<tr><td class="name">${esc(nameOf()(r))}</td><td class="wrap">${esc(r.text) || "<span class='muted'>—</span>"}</td></tr>`],
  "الراحات": [["الضابط", "النوع", "من", "إلى", "العودة"], r =>
    `<tr><td class="name">${esc(nameOf()(r))}</td>
     <td><span class="chip ${r.type === "شهرية" ? "m" : r.type === "نصف شهرية" ? "h" : "w"}">${esc(r.type)}</span></td>
     <td>${r.start ? fmt(r.start) : "-"}</td><td>${r.end ? fmt(r.end) : "-"}</td>
     <td>${r.return_date ? fmt(r.return_date) : "-"}</td></tr>`],
  "التقصيرات": [["الضابط", "العمل قبل التقصيرة"], r =>
    `<tr><td class="name">${esc(nameOf()(r))}</td><td class="wrap">${esc(r.note)}</td></tr>`],
  "الخوارج": [["الضابط", "السبب", "التفاصيل"], r =>
    `<tr><td class="name">${esc(nameOf()(r))}</td>
     <td><span class="chip taq">${esc(r.reason)}</span></td>
     <td class="wrap">${esc(r.note)}</td></tr>`],
};

function sectionCard(sec) {
  const count = sec.rows.length + (sec.groups || []).reduce((n, g) => n + g.rows.length, 0);
  let body;
  if (sec.type === "officers") {
    const [head, render] = OFFICER_VIEWS[sec.name];
    body = count ? mtable(head, sec.rows.map(render)) : `<div class="mempty">لا يوجد</div>`;
  } else {
    const parts = [];
    if (sec.rows.length) parts.push(mtable(SERVICE_HEAD, sec.rows.map(serviceRow)));
    for (const g of sec.groups || []) {
      parts.push(`<div class="sub-head">#${esc(g.tag)}</div>`);
      parts.push(mtable(SERVICE_HEAD, g.rows.map(serviceRow)));
    }
    body = parts.length ? parts.join("") : `<div class="mempty">لا توجد خدمات — اضغط «إضافة» فوق</div>`;
  }
  const addBtn = sec.type === "officers" ? "" :
    `<button class="mini ok" data-action="openEntry"
      data-extra="${dataAttr({section: sec.name})}">＋ إضافة</button>`;
  return `<div class="mcard">
    <h3>${esc(sec.name)}<span class="mcount">${count}</span>${addBtn}</h3>
    ${body}</div>`;
}

function render() {
  const wrap = $("#matchBoard");
  if (!BOARD) { wrap.innerHTML = `<div class="empty">جارٍ التحميل...</div>`; return }
  wrap.innerHTML = `
    <div class="match-head">
      <span class="muted">اليومية التفصيلية — ${dayName(BOARD.date)} ${fmt(BOARD.date)}</span>
    </div>
    <div class="match-grid">${BOARD.sections.map(sectionCard).join("")}</div>`;
}

/* ---------- نموذج الخانة ---------- */
function findRow(id) {
  for (const s of BOARD.sections) {
    const hit = s.rows.find(r => r.id === id)
      || (s.groups || []).flatMap(g => g.rows).find(r => r.id === id);
    if (hit) return hit;
  }
  return null;
}

function conRow(c) {
  return `<div class="req-row">
    <input class="con-class" placeholder="الفئة (قتالية/فض/حفظ نظام/رياضي)" value="${esc(c.class || "")}">
    <input class="con-count" type="number" min="0" placeholder="العدد" value="${c.count || ""}">
    <button type="button" class="mini bad" data-action="removeConRow">حذف</button>
  </div>`;
}
function renderTagChips() {
  $("#tagChips").innerHTML = ENTRY_TAGS.map((t, i) =>
    `<span class="chip soon">#${esc(t)} <a data-action="removeTag" data-id="${i}">×</a></span>`).join(" ");
}

function fillMulti(el, people, chosen) {
  el.innerHTML = people.map(p =>
    `<option value="${esc(p.id)}" ${chosen.includes(p.id) ? "selected" : ""}>${esc(nameOf()(p))}</option>`).join("");
}
const readMulti = el => [...el.selectedOptions].map(o => o.value);

function syncShiftOptions() {
  const svc = svcById($("#enService").value);
  const allowed = svc?.shifts?.length ? svc.shifts : SHIFTS();
  const isTarget = svc?.kind === "حراسات";
  // الأهداف هدف ثابت طول اليوم فمالهاش فترة
  $("#enShiftWrap").classList.toggle("hidden", isTarget);
  fillSelect($("#enShift"), isTarget ? [["", "— بدون —"]] : allowed.map(x => [x, x]), true);
}

function openEntry(rowId, preset) {
  const row = rowId ? findRow(rowId) : null;
  $("#enId").value = rowId || "";
  $("#entryTitle").textContent = row ? "تعديل خانة" : "إضافة خانة";
  $("#tagList").innerHTML = (META.service_tags || []).map(x => `<option value="${esc(x)}">`).join("");

  fillSelect($("#enService"), SERVICES.map(s => [s.id, `${s.name}${s.sub ? " — " + s.sub : ""}`]));
  fillSelect($("#enSection"), (META.service_sections || []).map(x => [x, x]));
  $("#enService").value = row?.service_id || SERVICES[0]?.id || "";
  syncShiftOptions();

  const svc = svcById($("#enService").value);
  $("#enSection").value = preset?.section || svc?.section || (META.service_sections || [])[1] || "";
  $("#enShift").value = row?.shift ?? preset?.shift ?? "";
  fillMulti($("#enOfficers"), OFFICERS, row?.officers?.map(o => o.id) || []);
  fillMulti($("#enPersonnel"), PERSONNEL, row?.personnel?.map(p => p.id) || []);
  $("#conRows").innerHTML = (row?.conscripts || []).map(conRow).join("");
  $("#enWeapon").value = row?.weapon || "";
  $("#enTime").value = row?.time || "";
  $("#enParty").value = row?.party || "";
  $("#enLabel").value = row?.label_override || "";
  $("#enNote").value = row?.note || "";
  ENTRY_TAGS = [...(row?.tags || [])]; renderTagChips();
  openModal("entryModal");
}

ACTIONS.openEntry = (id, extra) => openEntry(id || null, extra);
ACTIONS.deleteEntry = async (id, extra) => {
  if (!confirm(`حذف «${extra.name}» من اليومية؟`)) return;
  if (await api(`/api/assignments/${DAY}/${encodeURIComponent(id)}`, {method: "DELETE"})) {
    showToast("تم الحذف"); loadDay(DAY);
  }
};
ACTIONS.removeTag = i => { ENTRY_TAGS.splice(Number(i), 1); renderTagChips() };
ACTIONS.removeConRow = (id, extra, el) => el.closest(".req-row").remove();

$("#addConRow").onclick = () => $("#conRows").insertAdjacentHTML("beforeend", conRow({}));
$("#enService").addEventListener("change", () => {
  syncShiftOptions();
  const svc = svcById($("#enService").value);
  if (svc?.section) $("#enSection").value = svc.section;
});
$("#enTags").addEventListener("keydown", e => {
  if (e.key !== "Enter") return;
  e.preventDefault();
  const v = $("#enTags").value.trim();
  if (v && !ENTRY_TAGS.includes(v)) { ENTRY_TAGS.push(v); renderTagChips() }
  $("#enTags").value = "";
});

$("#entryForm").onsubmit = async e => {
  e.preventDefault();
  const conscripts = $$("#conRows .req-row").map(r => ({
    class: r.querySelector(".con-class").value.trim(),
    count: parseInt(r.querySelector(".con-count").value) || 0,
  })).filter(c => c.class || c.count);
  const body = {
    service_id: $("#enService").value,
    section: $("#enSection").value,
    shift: $("#enShift").value,
    officer_ids: readMulti($("#enOfficers")),
    personnel_ids: readMulti($("#enPersonnel")),
    conscripts,
    weapon: $("#enWeapon").value.trim(),
    time: $("#enTime").value.trim(),
    party: $("#enParty").value.trim(),
    label_override: $("#enLabel").value.trim(),
    tags: ENTRY_TAGS,
    note: $("#enNote").value.trim(),
  };
  const id = $("#enId").value;
  const out = id
    ? await api(`/api/assignments/${DAY}/${encodeURIComponent(id)}`, jsonReq("PATCH", body))
    : await api(`/api/assignments/${DAY}`, jsonReq("POST", body));
  if (!out) return;
  closeModal("entryModal"); showToast(id ? "تم حفظ التعديلات" : "تمت الإضافة");
  loadDay(DAY);
};

/* ---------- تنقّل الأيام ---------- */
async function loadDay(day) {
  const b = await api(`/api/board/${day}`); if (!b) return;
  BOARD = b; DAY = day; $("#dutyDate").value = day; render();
}
const shiftDay = n => loadDay(addDays($("#dutyDate").value || curDate(), n));
$("#dayPrev").onclick = () => shiftDay(-1);
$("#dayNext").onclick = () => shiftDay(1);
$("#dayToday").onclick = () => loadDay(curDate());
$("#dutyDate").onchange = () => loadDay($("#dutyDate").value);

/* تنبيه تسليم واستلام: مين هيبدأ راحته بكرة (تقصيرته النهاردة) وكان
   بيشتغل إيه، عشان يتكلّف بديل — من غير ما ننسخ التكليفات تلقائي. */
$("#dayTomorrow").onclick = async () => {
  const today = curDate(), tmr = addDays(today, 1);
  await loadDay(tmr);
  const boot = await api("/api/bootstrap/dashboard");
  const leaving = (boot?.alerts || []).filter(a => a.taqseera_date === today);
  if (!leaving.length) return;
  const todayBoard = await api(`/api/board/${today}`);
  const rows = leaving.map(a => {
    let service = "بدون خدمة مسجلة النهاردة";
    for (const sec of todayBoard?.sections || []) {
      const all = [...sec.rows, ...(sec.groups || []).flatMap(g => g.rows)];
      const hit = all.find(r => (r.officers || []).some(o => o.id === a.id));
      if (hit) { service = hit.label; break }
    }
    return `<li><span class="a-name">${esc(a.role)} / ${esc(a.name)}</span>
      <span class="a-mid">في راحة (${esc(a.type)}) بداية من بكرة</span>
      <span class="a-rest">كان بيشتغل: ${esc(service)}</span></li>`;
  });
  $("#matchBoard").insertAdjacentHTML("afterbegin", `<div class="alert-card">
    <div class="alert-head"><span class="alert-ico">↷</span><strong>تسليم واستلام بكرة</strong>
      <span class="muted">${leaving.length} ضابط هيبدأ راحته بكرة — محتاجين تكليف بديل على خدمتهم</span></div>
    <ul class="alert-list">${rows.join("")}</ul></div>`);
};

async function load() {
  const d = await bootstrap();
  if (!d) return;
  SERVICES = (d.services || []).filter(s => (s.appears_in || []).includes("board"));
  OFFICERS = d.officer_index || [];
  PERSONNEL = d.personnel_index || [];
  const days = d.days || [];
  loadDay(days.includes(curDate()) ? curDate() : (days[days.length - 1] || curDate()));
}
load();
