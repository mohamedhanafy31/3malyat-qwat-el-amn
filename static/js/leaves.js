/* سجل الراحات والإجازات */
let LEAVES = [], PEOPLE = [], OFFICER_IDS = new Set(), LEAVE_TAB = "all";

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
  return new Date(`${y}-${m}-15T12:00:00`).toLocaleDateString("ar-EG", { month: "long", year: "numeric" });
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
    <div class="stat stat-accent-red">
      <span>جارية الآن</span>
      <strong>${current.length}</strong>
      <div class="stat-sub">${officersOnLeave} ضابط على راحة</div>
    </div>
    <div class="stat stat-accent-orange">
      <span>يعودون غداً أو بعده</span>
      <strong>${returningTomorrow.length}</strong>
      <div class="stat-sub">${returningTomorrow.length ? returningTomorrow.map(l => esc(l.name.split(" ")[0])).join("، ") : "—"}</div>
    </div>
    <div class="stat stat-accent-blue">
      <span>قادمة</span>
      <strong>${upcoming.length}</strong>
      <div class="stat-sub">لم تبدأ بعد</div>
    </div>
    <div class="stat stat-accent-purple">
      <span>هذا الشهر</span>
      <strong>${thisMonthLeaves.length}</strong>
      <div class="stat-sub">إجمالي الراحات في ${monthLabel(thisMonth)}</div>
    </div>
    <div class="stat">
      <span>إجمالي السجلات</span>
      <strong>${LEAVES.length}</strong>
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
        ? `<span class="chip-return-soon">يعود غداً</span>`
        : remaining <= 2
          ? `<span class="chip-return-soon">يعود بعد ${remaining} أيام</span>`
          : `<span class="stat-sub">يعود بعد ${remaining} أيام</span>`;
    stateHtml = `<span class="chip rest">جارية</span><div>${returnsLabel}</div>`;
  } else if (upcoming) {
    const starts = daysUntil(l.start, today);
    stateHtml = `<span class="chip soon">قادمة</span><div class="stat-sub">بعد ${starts} يوم</div>`;
  } else {
    stateHtml = `<span class="chip done">منتهية</span>`;
  }

  // تمييز صف العائدين قريباً
  const rowClass = live && daysUntil(l.return_date, today) <= 1 ? ' class="returning-soon"' : "";

  const p = personById(l.person_id);
  const who = p
    ? `<span class="badge ${OFFICER_IDS.has(l.person_id) ? "" : "person"}">${esc(p.role)}</span>`
    : '<span class="muted">(محذوف)</span>';

  return `<tr${rowClass}>
    <td class="name">${esc(l.name)}<div class="sub">${who}</div></td>
    <td><span class="chip ${l.type === "شهرية" ? "m" : l.type === "نصف شهرية" ? "h" : "w"}">${esc(l.type)}</span></td>
    <td>${fmt(l.start)}<div class="sub">تقصيرة ${dayName(addDays(l.start, -1))}</div></td>
    <td>${fmt(l.end)}</td>
    <td>${fmt(l.return_date)}</td>
    <td class="num">${days(l.start, l.end)}</td>
    <td>${stateHtml}</td>
    <td class="wrap">${esc(l.note) || "<span class='muted'>—</span>"}</td>
    <td><div class="actions">
      <button class="mini" data-action="openLeaveEdit" data-id="${esc(l.id)}">تعديل</button>
      <button class="mini bad" data-action="deleteLeave" data-id="${esc(l.id)}" data-extra="${dataAttr({name: l.name})}">حذف</button>
    </div></td></tr>`;
}

// ── Main Render ────────────────────────────────────────────────────────────
function render() {
  renderStats();
  const today = curDate();
  const thisMonth = today.slice(0, 7);

  let rows = [...LEAVES];

  // ── فلترة التبويب ──
  if (LEAVE_TAB === "current")  rows = rows.filter(l => l.start <= today && today <= l.end);
  if (LEAVE_TAB === "upcoming") rows = rows.filter(l => l.start > today);
  if (LEAVE_TAB === "month")    rows = rows.filter(l =>
    l.start.slice(0, 7) === thisMonth || l.end.slice(0, 7) === thisMonth);

  // ── فلتر الاسم ──
  const q = $("#leaveSearch").value.trim().toLowerCase();
  if (q) rows = rows.filter(l => String(l.name || "").toLowerCase().includes(q));

  // ── فلتر النوع ──
  const tf = $("#leaveTypeFilter").value;
  if (tf) rows = rows.filter(l => l.type === tf);

  // ── فلتر الشهر ──
  const mf = $("#leaveMonthFilter").value;
  if (mf) rows = rows.filter(l => l.start.slice(0, 7) === mf || l.end.slice(0, 7) === mf);

  // ── ترتيب: النوع → القيادة → الرتبة → الاسم ──
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

  // ── بناء الجدول مع فواصل النوع ──
  let lastType = null;
  const body = rows.map(l => {
    const divider = l.type !== lastType
      ? `<tr class="grouprow"><td colspan="9">${esc(l.type)}</td></tr>` : "";
    lastType = l.type;
    return divider + leaveRow(l, today);
  });

  $("#leaveWrap").innerHTML = tableBlock(
    ["الاسم", "النوع", "من", "إلى", "العودة", "الأيام", "الحالة", "ملاحظات", "الإجراء"],
    body, `عدد النتائج: ${rows.length}`, "لا توجد راحات مسجلة.");
}

// ── Actions ────────────────────────────────────────────────────────────────
ACTIONS.openLeaveEdit = id => openLeave(id);
ACTIONS.deleteLeave = async (id, extra) => {
  if (!confirm(`حذف سجل راحة «${extra.name}»؟`)) return;
  if (await api(`/api/leaves/${encodeURIComponent(id)}`, { method: "DELETE" })) {
    showToast("تم حذف الراحة"); load();
  }
};

// ── Event Listeners ────────────────────────────────────────────────────────
$$("[data-lv]").forEach(b => b.onclick = () => {
  $$("[data-lv]").forEach(x => x.classList.remove("active"));
  b.classList.add("active"); LEAVE_TAB = b.dataset.lv; render();
});
$("#leaveSearch").oninput      = render;
$("#leaveTypeFilter").onchange = render;
$("#leaveMonthFilter").onchange = render;
$("#addLeaveBtn").onclick = () => openLeave(null);

// ── Bootstrap ──────────────────────────────────────────────────────────────
async function load() {
  const d = await bootstrap();
  if (!d) return;
  LEAVES       = d.leaves || [];
  PEOPLE       = d.people || [];
  OFFICER_IDS  = new Set(d.officer_ids || []);
  setLeavePeople(PEOPLE);
  setLeaveLookup(id => LEAVES.find(l => l.id === id));

  fillSelect($("#leaveTypeFilter"),
    [["", "كل الأنواع"], ...LEAVE_TYPES().map(x => [x, x])], true);

  fillSelect($("#leaveMonthFilter"),
    [["", "كل الأشهر"], ...buildMonthOptions()], true);

  render();
}
load();
