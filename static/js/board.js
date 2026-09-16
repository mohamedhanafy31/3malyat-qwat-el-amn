/* اليومية التفصيلية — أقسام الوورد العشرة على سجل تكليف واحد.
   اسم الخدمة حر بيكتبه المشغّل على الخانة نفسها، والتصنيف (خارجية/داخلية/
   حراسات/طبية) بيتحدد معاه — مفيش كتالوج منفصل يتربط بيه. */
let BOARD = null, DAY = null, OFFICERS = [], PERSONNEL = [], ENTRY_TAGS = [];

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
    <td>${conChips(row.conscripts)}${row.conscript_count ? ` <span class="chip w">×${row.conscript_count}</span>` : ""}
      ${!row.conscripts.length && !row.conscript_count ? "<span class='muted'>—</span>" : ""}</td>
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

/* تنبيهات مش موانع: الأرشيف فيه ضباط على خدمتين في نفس الفترة فعلًا،
   فالفحص بيلفت النظر ومابيمنعش الحفظ. */
const WARN_ICON = {"راحة": "☾", "حالة": "⚑", "ازدحام": "⇄", "شاغرة": "○"};
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
        <li><span class="w-ico">${WARN_ICON[w.kind] || "⚠"}</span>
          <span class="chip taq">${esc(w.kind)}</span> ${esc(w.text)}</li>`).join("")}</ul>
    </div>`).join("");
  return `<div class="alert-card">
    <div class="alert-head"><span class="alert-ico">⚠</span><strong>مراجعة اليوم</strong>
      <span class="muted">${list.length} ملاحظة — للفت النظر مش للمنع</span></div>
    ${body}</div>`;
}

function render() {
  const wrap = $("#matchBoard");
  if (!BOARD) { wrap.innerHTML = `<div class="empty">جارٍ التحميل...</div>`; return }
  wrap.innerHTML = `
    <div class="match-head">
      <span class="muted">اليومية التفصيلية — ${dayName(BOARD.date)} ${fmt(BOARD.date)}</span>
    </div>
    ${warningsCard(BOARD.warnings)}
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
  const isTarget = $("#enKind").value === "حراسات";
  // الأهداف هدف ثابت طول اليوم فمالهاش فترة
  $("#enShiftWrap").classList.toggle("hidden", isTarget);
  fillSelect($("#enShift"), isTarget ? [["", "— بدون —"]] : SHIFTS().map(x => [x, x]), true);
}

function openEntry(rowId, preset) {
  const row = rowId ? findRow(rowId) : null;
  $("#enId").value = rowId || "";
  $("#entryTitle").textContent = row ? "تعديل خانة" : "إضافة خانة";
  $("#tagList").innerHTML = (META.service_tags || []).map(x => `<option value="${esc(x)}">`).join("");

  $("#enName").value = row?.name || "";
  fillSelect($("#enKind"), KINDS().map(x => [x, x]));
  $("#enKind").value = row?.kind || KINDS()[0] || "";
  fillSelect($("#enSection"), (META.service_sections || []).map(x => [x, x]));
  $("#enSection").value = row?.section || preset?.section || (META.service_sections || [])[1] || "";
  syncShiftOptions();
  $("#enShift").value = row?.shift ?? preset?.shift ?? "";
  fillMulti($("#enOfficers"), OFFICERS, row?.officers?.map(o => o.id) || []);
  fillMulti($("#enPersonnel"), PERSONNEL, row?.personnel?.map(p => p.id) || []);
  $("#conRows").innerHTML = (row?.conscripts || []).map(conRow).join("");
  $("#enConCount").value = row?.conscript_count || "";
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
$("#enKind").addEventListener("change", syncShiftOptions);
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
    name: $("#enName").value.trim(),
    kind: $("#enKind").value,
    section: $("#enSection").value,
    shift: $("#enShift").value,
    officer_ids: readMulti($("#enOfficers")),
    personnel_ids: readMulti($("#enPersonnel")),
    conscripts,
    conscript_count: parseInt($("#enConCount").value) || 0,
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
    ? "\n\nملاحظة: مفيش أي تعديل من آخر تأكيد — ده هيتسجّل كإعادة تأكيد."
    : "";
  if (!confirm(`انت متأكد إنك عايز تأكد الخدمات الحالية ليوم ${DAY}؟`
               + `\nاللي اتغيّر من آخر تأكيد هيتسجّل في سجل التغييرات بوقت دلوقتي.${extra}`)) return;
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
  BOARD = b; DAY = day; $("#dutyDate").value = day; render();
  renderConfirmBadge();
  loadDayStatus();
}
const shiftDay = n => loadDay(addDays($("#dutyDate").value || curDate(), n));
$("#dayPrev").onclick = () => shiftDay(-1);
$("#dayNext").onclick = () => shiftDay(1);
$("#dayToday").onclick = () => loadDay(curDate());
$("#dutyDate").onchange = () => loadDay($("#dutyDate").value);

/* إغلاق اليوم: أي يوم فات بيتقفل لوحده الساعة ١٢ بالليل، والقفل بالإيد
   لليوم الحالي بس (قفل بدري). يوم مقفول بيرفض أي تعديل من الباك إند
   (409) — الزراير هنا واجهة، الحارس الحقيقي في السيرفر.
   الفتح الاستثنائي صالح النهاردة بس وبعدين اليوم بيرجع يتقفل تلقائي. */
async function loadDayStatus() {
  const s = await api(`/api/day-status/${DAY}`);
  if (!s) return;
  const badge = $("#dayLockBadge");
  if (s.closed) {
    const why = s.auto ? "اتقفل تلقائيًا الساعة ١٢ بالليل"
                       : `اتقفل بالإيد${s.closed_by ? " — " + s.closed_by : ""}`;
    badge.innerHTML = `<span class="chip err" title="${esc(why)}">🔒 مقفول</span>
      <button class="mini" id="btnReopenDay">فتح استثنائي</button>`;
    $("#btnReopenDay").onclick = reopenDay;
  } else if (s.reopened) {
    badge.innerHTML = `<span class="chip taq"
        title="الفتح الاستثنائي صالح النهاردة بس — اليوم هيرجع يتقفل تلقائي الساعة ١٢">
        🔓 مفتوح استثنائيًا النهاردة</span>`;
  } else {
    badge.innerHTML = `<button class="mini" id="btnCloseDay"
      title="اليوم بيتقفل لوحده الساعة ١٢ بالليل — الزرار ده للقفل بدري">قفل اليوم بدري</button>`;
    $("#btnCloseDay").onclick = closeDay;
  }
}
async function closeDay() {
  if (!confirm(`قفل يوم ${DAY}؟ أي تعديل بعد كده هيحتاج فتح استثنائي.`)) return;
  const name = ($("#editedBy")?.value || "").trim();
  if (!(await api(`/api/day-status/${DAY}/close`, jsonReq("POST", {closed_by: name})))) return;
  showToast("اتقفل اليوم"); loadDayStatus();
}
async function reopenDay() {
  const reason = prompt("سبب فتح اليوم المقفول؟ (الفتح صالح النهاردة بس)");
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
      const all = [...sec.rows, ...(sec.groups || []).flatMap(g => g.rows)];
      const hit = all.find(r => (r.officers || []).some(o => o.id === a.id));
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
  OFFICERS = d.officer_index || [];
  PERSONNEL = d.personnel_index || [];
  const days = d.days || [];
  loadDay(days.includes(curDate()) ? curDate() : (days[days.length - 1] || curDate()));
}
load();
