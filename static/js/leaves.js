/* سجل الراحات والإجازات */
let LEAVES = [], LEAVE_HISTORY = [], PEOPLE = [], OFFICER_IDS = new Set(), LEAVE_TAB = "active";
/* الصفحة كانت بتفتح على «الكل» مرتبة بالنوع ثم الأقدم، فأول شاشة كانت راحات
   يونيو المنتهية؛ الجاري والقادم — اللي بيتسأل عنه فعلًا — كانوا مدفونين.
   الافتراضي بقى الحالية والقادمة، والتبويب اللي المستخدم يختاره بيتحفظ. */
try { LEAVE_TAB = localStorage.getItem("leavesTab") || "active"; } catch (err) {}
const LEAVE_FILTERS = UI.filterChips("#leaveFilterSummary", [
  {el:"#leaveSearch", label:"بحث", format:value=>`«${value}»`},
  {el:"#leaveTypeFilter", label:"النوع"}, {el:"#leaveMonthFilter", label:"الشهر"},
  {el:"#leaveCategoryFilter", label:"الفئة"}, {el:"#leaveDurationFilter", label:"المدة"},
], render);

const HIST_FILTERS = UI.filterChips("#histFilterSummary", [
  {el:"#histSearch", label:"بحث", format:value=>`«${value}»`},
  {el:"#histActionFilter", label:"الإجراء"}, {el:"#histStatusFilter", label:"الحالة"},
], render);

function updateLeaveTabCounts(today) {
  const counts={deleted:LEAVE_HISTORY.filter(h=>!h.restored_at).length,all:LEAVES.length,active:LEAVES.filter(l=>l.end>=today).length,
    current:LEAVES.filter(l=>l.start<=today&&today<=l.end).length,
    upcoming:LEAVES.filter(l=>l.start>today).length,ended:LEAVES.filter(l=>l.end<today).length};
  $$('[data-lv]').forEach(button=>{
    if(!button.dataset.baseLabel) button.dataset.baseLabel=button.textContent.trim();
    button.textContent=`${button.dataset.baseLabel} (${counts[button.dataset.lv]||0})`;
  });
}

// ── helpers ────────────────────────────────────────────────────────────────
const personById   = id => PEOPLE.find(p => p.id === id);
const leaveTypeIndex = t => { const i = LEAVE_TYPES().indexOf(t); return i < 0 ? LEAVE_TYPES().length : i };
const commandPriority = id => {
  const roles = COMMAND_ROLES(), role = roles.find(r => (META.command || {})[r] === id);
  const i = roles.indexOf(role); return i < 0 ? roles.length : i;
};

/** أيام من اليوم لتاريخ العودة (سالب = مضت، صفر = اليوم، موجب = قادمة) */
const daysUntil = (dateStr, today) =>
  Math.round((new Date(dateStr + "T12:00:00") - new Date(today + "T12:00:00")) / 864e5);

/** هل الراحة عودتها خلال N أيام أو أقل (من العودة لليوم)؟ */
const returningWithin = (l, today, n) =>
  l.start <= today && today <= l.end && daysUntil(l.return_date, today) <= n;

/** yyyy-mm → اسم الشهر بالعربي */
const monthLabel = ym => {
  const [y, m] = ym.split("-");
  return new Date(`${y}-${m}-15T12:00:00`).toLocaleDateString("ar-EG-u-nu-latn", { month: "long", year: "numeric" });
};

/** استخراج قائمة أشهر لا تكرار من LEAVES */
function buildMonthOptions() {
  const months = new Set();
  LEAVES.forEach(l => { if (l.start) months.add(l.start.slice(0, 7)); });
  return [...months].sort().reverse().map(ym => [ym, monthLabel(ym)]);
}

// ── Stats Bar ──────────────────────────────────────────────────────────────
function renderStats() {
  const today = curDate();
  const thisMonth = today.slice(0, 7);

  const current   = LEAVES.filter(l => l.start <= today && today <= l.end);
  const upcoming  = LEAVES.filter(l => l.start > today);
  const thisMonthLeaves = LEAVES.filter(l => l.start.slice(0, 7) === thisMonth || l.end.slice(0, 7) === thisMonth);
  const returningTomorrow = LEAVES.filter(l => returningWithin(l, today, 1));

  // أعداد الضباط (مش عدد السجلات) في راحة الآن
  const officersOnLeave = new Set(current.map(l => l.person_id)).size;

  $("#leaveStats").innerHTML = `
    <div class="stat">
      <span>جارية الآن</span>
      <strong>${current.length}</strong>
      <div class="stat-sub">${countLabel(officersOnLeave, "ضابط")} على راحة</div>
    </div>
    <div class="stat${returningTomorrow.length ? " stat-accent-orange" : ""}">
      <span>يعودون غدًا أو بعده</span>
      <strong>${returningTomorrow.length}</strong>
      <div class="stat-sub">${returningTomorrow.length ? returningTomorrow.map(l => esc(l.name.split(" ")[0])).join("، ") : "—"}</div>
    </div>
    <div class="stat">
      <span>قادمة</span>
      <strong>${upcoming.length}</strong>
      <div class="stat-sub">لم تبدأ بعد</div>
    </div>
    <div class="stat">
      <span>هذا الشهر</span>
      <strong>${thisMonthLeaves.length}</strong>
      <div class="stat-sub">إجمالي الراحات في ${monthLabel(thisMonth)}</div>
    </div>
    <div class="stat">
      <span>إجمالي السجلات</span>
      <strong>${LEAVES.filter(l => !l.virtual).length}</strong>
      <div class="stat-sub">كل الفترات</div>
    </div>`;
}

// ── Row Builder ────────────────────────────────────────────────────────────
function leaveRow(l, today) {
  const live = l.start <= today && today <= l.end;
  const upcoming = l.start > today;

  // حالة الراحة مع "أيام باقية" للجارية
  let stateHtml;
  if (live) {
    const remaining = daysUntil(l.return_date, today);
    const returnsLabel = remaining === 0
      ? `<span class="chip-return-today">يعود اليوم!</span>`
      : remaining === 1
        ? `<span class="chip-return-soon">يعود غدًا</span>`
        : remaining <= 2
          ? `<span class="chip-return-soon">يعود بعد ${countLabel(remaining, "يوم")}</span>`
          : `<span class="stat-sub">يعود بعد ${countLabel(remaining, "يوم")}</span>`;
    stateHtml = `<span class="chip rest">جارية</span><div>${returnsLabel}</div>`;
  } else if (upcoming) {
    const starts = daysUntil(l.start, today);
    stateHtml = `<span class="chip soon">قادمة</span><div class="stat-sub">بعد ${countLabel(starts, "يوم")}</div>`;
  } else {
    stateHtml = `<span class="chip done">منتهية</span>`;
  }
  // اتوقفت قبل نهايتها — التاريخ الأصلي والسبب محفوظين على السجل
  if (l.stopped_on) {
    stateHtml += `<div><span class="chip err">موقوفة</span></div>
      <div class="sub">كانت حتى ${fmt(l.original_end)} — ${esc(l.stop_reason)}</div>`;
  }
  const canStop = OFFICER_IDS.has(l.person_id) && (live || upcoming);
  const shownType = l.display_type || l.type;
  const stopExtra = {name: l.name, type: shownType, start: l.start, end: l.end};

  // تمييز صف العائدين قريباً
  const rowClass = live && daysUntil(l.return_date, today) <= 1 ? ' class="returning-soon"' : "";

  const p = personById(l.person_id);
  const who = p
    ? `<span class="badge ${OFFICER_IDS.has(l.person_id) ? "" : "person"}">${esc(p.role)}</span>`
    : '<span class="muted">(محذوف)</span>';
  const origin = l.virtual
    ? `<div class="sub"><span class="chip w">راحة أسبوعية ثابتة</span></div>`
    : l.type === "أسبوعية" && l.origin === "auto_weekly"
    ? `<div class="sub"><span class="chip w">تلقائية</span></div>`
    : l.type === "أسبوعية" && l.origin === "weekly_extra"
      ? `<div class="sub"><span class="chip soon">إضافية</span></div>` : "";

  return `<tr${rowClass}>
    <td class="name">${esc(l.name)}<div class="sub">${who}</div></td>
    <td><span class="chip leave-kind-chip ${l.type === "شهرية" ? "m" : l.type === "نصف شهرية" ? "h" : "w"}">${esc(shownType)}</span>${origin}</td>
    <td>${fmt(l.start)}<div class="sub">تقصيرة ${dayName(addDays(l.start, -1))}</div></td>
    <td>${fmt(l.end)}</td>
    <td>${fmt(l.return_date)}</td>
    <td class="num">${days(l.start, l.end)}</td>
    <td>${stateHtml}</td>
    <td class="wrap">${l.virtual ? "<span class='muted'>تُسجَّل تلقائيًا عند فتح اليوم</span>" : esc(l.note) || "<span class='muted'>—</span>"}</td>
    <td class="col-actions">${l.virtual ? "<span class='muted'>—</span>" : `<div class="actions leave-row-actions">
      ${canStop && !upcoming ? `<button class="mini warn" data-action="stopLeave"
        data-id="${esc(l.id)}" data-extra="${dataAttr(stopExtra)}">إنهاء الآن</button>` : ""}
      <button class="mini" data-action="openLeaveEdit" data-id="${esc(l.id)}">تعديل</button>
      ${rowMenu([
        canStop && upcoming && {action: "stopLeave", id: l.id, extra: stopExtra, label: "إلغاء الراحة", danger: true},
        {action: "deleteLeave", id: l.id, extra: {name: l.name}, label: "حذف", danger: true},
      ])}
    </div>`}</td></tr>`;
}

// ── Sortable column definitions ────────────────────────────────────────────
const LEAVE_COLS = {
  name:        { label: "الاسم",      fn: l => l.name,                       type: "text" },
  type:        { label: "النوع",      fn: l => leaveTypeIndex(l.type),       type: "num"  },
  start:       { label: "من",         fn: l => l.start,                      type: "date" },
  end:         { label: "إلى",        fn: l => l.end,                        type: "date" },
  return_date: { label: "العودة",     fn: l => l.return_date,                type: "date" },
  duration:    { label: "الأيام",     fn: l => days(l.start, l.end),        type: "num"  },
  state:       { label: "الحالة",     fn: l => {
    const t = curDate();
    if (l.start <= t && t <= l.end) return 0;   // جارية أولاً
    if (l.start > t) return 1;                   // قادمة
    return 2;                                    // منتهية
  }, type: "num" },
};

// ── Main Render ────────────────────────────────────────────────────────────
function render() {
  renderStats();
  const today = curDate();
  updateLeaveTabCounts(today);
  const histMode = LEAVE_TAB === "deleted";
  $("#histToolbar").classList.toggle("hidden", !histMode);
  $("#histFilterSummary").classList.toggle("hidden", !histMode);
  $("#leaveToolbar").classList.toggle("hidden", histMode);
  $("#leaveFilterSummary").classList.toggle("hidden", histMode);
  if (histMode) { renderHistory(); return; }
  const st = _sortState("leaveWrap");

  let rows = [...LEAVES];

  // ── فلترة التبويب ──
  if (LEAVE_TAB === "active")   rows = rows.filter(l => l.end >= today);
  if (LEAVE_TAB === "current")  rows = rows.filter(l => l.start <= today && today <= l.end);
  if (LEAVE_TAB === "upcoming") rows = rows.filter(l => l.start > today);
  if (LEAVE_TAB === "ended")    rows = rows.filter(l => l.end < today);

  // ── فلتر الاسم (بتطبيع عربي — «احمد» تلاقي «أحمد») ──
  const q = $("#leaveSearch").value.trim();
  if (q) rows = rows.filter(l => arIncludes(l.name, q));

  // ── فلتر النوع ──
  const tf = $("#leaveTypeFilter").value;
  if (tf) rows = rows.filter(l => l.type === tf);

  // ── فلتر الشهر ──
  const mf = $("#leaveMonthFilter").value;
  if (mf) rows = rows.filter(l => l.start.slice(0, 7) === mf || l.end.slice(0, 7) === mf);

  // ── فلتر الفئة (ضباط vs أفراد) ──
  // OFFICER_IDS بقت شاملة المتأرشفين كمان، فمالهاش داعي أي بادئة احتياطية.
  // البادئة اللي كانت هنا مكتوبة "OFF_" بشرطة سفلية والمعرّفات كلها "OFF-"
  // بشرطة عادية، فكانت دايمًا false وكل راحة لضابط متأرشف بتتحسب "فرد".
  const cf = $("#leaveCategoryFilter")?.value;
  if (cf === "officers")  rows = rows.filter(l => OFFICER_IDS.has(l.person_id));
  if (cf === "personnel") rows = rows.filter(l => !OFFICER_IDS.has(l.person_id));

  // ── فلتر المدة ──
  const df = $("#leaveDurationFilter")?.value;
  if (df) {
    rows = rows.filter(l => {
      const n = days(l.start, l.end);
      if (df === "short") return n <= 3;
      if (df === "medium") return n >= 4 && n <= 7;
      if (df === "long") return n > 7;
      return true;
    });
  }

  // ── الترتيب الافتراضي بالزمن خارج «الكل»: الجارية أولًا (الأقرب رجوعًا)،
  //    ثم القادمة (الأقرب بدايةً)؛ والمنتهية الأحدث أولًا ──
  const byTime = !st.col && LEAVE_TAB !== "all";
  if (byTime) {
    const live = l => l.start <= today && today <= l.end;
    rows.sort((a, b) => {
      if (LEAVE_TAB === "ended") return b.end.localeCompare(a.end);
      if (live(a) !== live(b)) return live(a) ? -1 : 1;
      return live(a) ? a.end.localeCompare(b.end) : a.start.localeCompare(b.start);
    });
  }
  // ── «الكل»: النوع → القيادة → الرتبة (يُطبّق فقط لو مفيش column sort نشط) ──
  if (!st.col && !byTime) {
    rows.sort((a, b) => {
      const ta = leaveTypeIndex(a.type), tb = leaveTypeIndex(b.type);
      if (ta !== tb) return ta - tb;
      const ca = commandPriority(a.person_id), cb = commandPriority(b.person_id);
      if (ca !== cb) return ca - cb;
      const pa = personById(a.person_id), pb = personById(b.person_id);
      const ra = rankIndex(pa?.role), rb = rankIndex(pb?.role);
      if (ra !== rb) return ra - rb;
      return (pa?.name || a.name).localeCompare(pb?.name || b.name, "ar");
    });
  }

  // ── بناء الجدول: فواصل النوع فقط عند الترتيب الافتراضي ──
  const rowHtml = (st.col || byTime)
    ? l => leaveRow(l, today)   // بدون grouprows عند column sort أو الترتيب الزمني
    : (() => {
        let lastType = null;
        return l => {
          const divider = l.type !== lastType
            ? `<tr class="grouprow"><td colspan="9">${esc(l.type)}</td></tr>` : "";
          lastType = l.type;
          return divider + leaveRow(l, today);
        };
      })();

  $("#leaveWrap").innerHTML = sortableTableBlock(
    "leaveWrap",
    LEAVE_COLS,
    rows,
    rowHtml,
    ["ملاحظات", "الإجراء"],
    `عدد النتائج: ${rows.length}`,
    {title: "لا توجد راحات مسجّلة", hint: "سجّل راحة جديدة من زر «تسجيل راحة»."},
    render
  );
  LEAVE_FILTERS.update(rows.length);
}


// ── المحذوفة والملغية ───────────────────────────────────────────────────────
const HIST_COLS = {
  name:    { label: "الضابط",       fn: h => h.person_name || "",        type: "text" },
  type:    { label: "النوع",        fn: h => h.display_type || "",       type: "text" },
  start:   { label: "المدة",        fn: h => (h.before || {}).start || "", type: "date" },
  origin:  { label: "الأصل",        fn: h => h.origin_label || "",       type: "text" },
  action:  { label: "الإجراء",      fn: h => h.action_label || "",       type: "text" },
  by:      { label: "بواسطة",       fn: h => h.performed_by || "",       type: "text" },
  at:      { label: "التوقيت",      fn: h => h.occurred_at || "",        type: "date" },
};
const fmtStamp = iso => iso ? `${fmt(iso.slice(0, 10))} ${esc(iso.slice(11, 16))}` : "—";

function historyRow(h) {
  const b = h.before || {};
  const n = b.start && b.end ? days(b.start, b.end) : 0;
  const extra = h.action === "stop" && h.after && h.after.end
    ? `<div class="sub">كانت حتى ${fmt(b.end)}، أصبحت حتى ${fmt(h.after.end)}</div>` : "";
  const status = h.restored_at
    ? `<span class="chip done">تم الاسترجاع</span><div class="sub">بواسطة ${esc(h.restored_by)} في ${fmtStamp(h.restored_at)}</div>`
    : `<span class="chip soon">قابلة للاسترجاع</span>`;
  const who = h.person_archived ? `<div class="sub"><span class="chip err">في الأرشيف</span></div>` : "";
  const action = h.restored_at
    ? "<span class='muted'>—</span>"
    : `<button type="button" class="mini primary" data-action="restoreLeave" data-id="${esc(h.id)}"
        data-extra="${dataAttr({name: h.person_name, kind: h.action_label, stop: h.action === "stop"})}"
        aria-label="استرجاع ${esc(h.action_label)} راحة ${esc(h.person_name)}">استرجاع</button>`;
  return `<tr>
    <td class="name">${esc(h.person_name) || "<span class='muted'>(محذوف)</span>"}${who}</td>
    <td><span class="chip leave-kind-chip ${b.type === "شهرية" ? "m" : b.type === "نصف شهرية" ? "h" : "w"}">${esc(h.display_type || b.type)}</span></td>
    <td>${fmt(b.start)} ← ${fmt(b.end)}<div class="sub">${countLabel(n, "يوم")}</div>${extra}</td>
    <td>${esc(h.origin_label)}</td>
    <td>${esc(h.action_label)}${h.suspension_id ? `<div class="sub">${esc(h.suspension_id)}</div>` : ""}</td>
    <td>${esc(h.performed_by)}</td>
    <td>${fmtStamp(h.occurred_at)}</td>
    <td class="wrap">${esc(h.reason) || "<span class='muted'>—</span>"}</td>
    <td>${status}</td>
    <td class="col-actions">${action}</td></tr>`;
}

function renderHistory() {
  const q = $("#histSearch").value.trim();
  const af = $("#histActionFilter").value, sf = $("#histStatusFilter").value;
  let rows = [...LEAVE_HISTORY];
  if (q) rows = rows.filter(h => arIncludes(h.person_name || "", q) || arIncludes(h.reason || "", q));
  if (af) rows = rows.filter(h => h.action_label === af);
  if (sf) rows = rows.filter(h => sf === "restored" ? !!h.restored_at : !h.restored_at);
  const hasFilters = !!(q || af || sf);
  if (!rows.length) {
    $("#leaveWrap").innerHTML = hasFilters ? emptyState({filtered: true}) : emptyState({
      icon: "inbox", title: "لا توجد راحات محذوفة أو ملغية",
      hint: "أي راحة تُحذف أو تُنهى مبكرًا تظهر هنا ويمكن استرجاعها."});
  } else {
    $("#leaveWrap").innerHTML = sortableTableBlock(
      "leaveWrap", HIST_COLS, rows, historyRow,
      ["السبب", "الحالة", "الإجراء"], `عدد النتائج: ${rows.length}`, null, render);
  }
  HIST_FILTERS.update(rows.length);
}

ACTIONS.restoreLeave = async (id, extra) => {
  const what = extra.stop
    ? `ستعود راحة «${extra.name}» إلى نهايتها الأصلية قبل الإنهاء المبكر.`
    : `ستُعاد راحة «${extra.name}» كما كانت تمامًا (نفس التواريخ والنوع والملاحظات).`;
  if (!(await confirmDialog({
    title: "استرجاع الراحة",
    body: `${what} لن يتم الاسترجاع لو في تعارض مع راحة أخرى لنفس الشخص، وسيُسجَّل الإجراء في سجل التغييرات.`,
    confirmLabel: "استرجاع",
  }))) return;
  if (await api(`/api/leaves/history/${encodeURIComponent(id)}/restore`, jsonReq("POST", {}))) {
    showToast("تم استرجاع الراحة"); load();
  }
};

// ── Actions ────────────────────────────────────────────────────────────────
ACTIONS.openLeaveEdit = id => openLeave(id);
ACTIONS.stopLeave = (id, extra) => openStopLeave({id, ...extra}, load);
ACTIONS.deleteLeave = async (id, extra) => {
  if (!(await confirmDialog({
    title: "حذف سجل الراحة",
    body: `سيُحذف سجل راحة «${extra.name}» نهائيًا ولا يمكن التراجع عن ذلك.`,
    confirmLabel: "حذف السجل",
    danger: true,
  }))) return;
  if (await api(`/api/leaves/${encodeURIComponent(id)}`, { method: "DELETE" })) {
    showToast("تم حذف الراحة"); load();
  }
};

// ── Event Listeners ────────────────────────────────────────────────────────
$$("[data-lv]").forEach(b => b.onclick = () => {
  $$("[data-lv]").forEach(x => {
    const selected=x===b;
    x.classList.toggle("active",selected);
    x.setAttribute("aria-selected",String(selected));
    x.tabIndex=selected?0:-1;
  });
  $("#leaveWrap").setAttribute("aria-labelledby",b.id);
  LEAVE_TAB = b.dataset.lv;
  try { localStorage.setItem("leavesTab", LEAVE_TAB); } catch (err) {}
  render();
});
// التبويب المحفوظ بيتعلّم أول ما الصفحة تفتح
(() => {
  const saved = document.querySelector(`[data-lv="${LEAVE_TAB}"]`) || document.querySelector('[data-lv="active"]');
  LEAVE_TAB = saved.dataset.lv;
  $$("[data-lv]").forEach(x => {
    const selected = x === saved;
    x.classList.toggle("active", selected);
    x.setAttribute("aria-selected", String(selected));
    x.tabIndex = selected ? 0 : -1;
  });
  $("#leaveWrap").setAttribute("aria-labelledby", saved.id);
})();
$("#leaveSearch").oninput      = debounce(render);   // إعادة الرسم بعد ما الكتابة تهدى
$("#histSearch").oninput = debounce(render);
$("#histActionFilter").onchange = render;
$("#histStatusFilter").onchange = render;
$("#leaveTypeFilter").onchange = render;
$("#leaveMonthFilter").onchange = render;
if ($("#leaveCategoryFilter")) $("#leaveCategoryFilter").onchange = render;
if ($("#leaveDurationFilter")) $("#leaveDurationFilter").onchange = render;
$("#addLeaveBtn").onclick = () => openLeave(null);

// ── وقف الراحات — سطر حالة بس؛ الإدارة نفسها في صفحتها (/leaves/suspension) ──
function renderSuspensionStrip() {
  const susp = META.rest_suspension || {};
  $("#suspensionBar").innerHTML = (susp.active || []).length
    ? `<div class="alert-card susp-banner"><div class="alert-head"><span class="alert-ico">${icon("block","ico-lg")}</span>
        <strong>الراحات موقوفة: ${(susp.types || []).map(esc).join("، ")}</strong>
        <span class="muted">يُرفض تسجيل راحة من هذه الأنواع لأي ضابط.</span>
        <a class="mini" href="/leaves/suspension">إدارة الوقف</a></div></div>`
    : "";
}

// ── Bootstrap ──────────────────────────────────────────────────────────────
async function load() {
  const d = await bootstrap();
  if (!d) { UI.regionError("#leaveWrap", {message:"تعذر تحميل سجل الراحات.", retry:load}); return; }
  UI.regionReady("#leaveWrap");
  LEAVES       = d.leaves || [];
  LEAVE_HISTORY = d.leave_history || [];
  PEOPLE       = d.people || [];
  OFFICER_IDS  = new Set(d.officer_ids || []);
  setLeavePeople(PEOPLE);
  setLeaveLookup(id => LEAVES.find(l => l.id === id));

  fillSelect($("#leaveTypeFilter"),
    [["", "كل الأنواع"], ...LEAVE_TYPES().map(x => [x, x])], true);

  fillSelect($("#leaveMonthFilter"),
    [["", "كل الأشهر"], ...buildMonthOptions()], true);

  render();
  renderSuspensionStrip();
}
load();
