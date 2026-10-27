/* إحصائيات استخدام النظام — تجميع سجل النشاط حسب الحساب والوقت. */

let ACTIVITY = null;
let ACTIVITY_CHARTS = [];

function activityDuration(minutes) {
  const value = Math.max(0, Number(minutes) || 0);
  if (value < 60) return `${value} د`;
  const hours = Math.floor(value / 60);
  const rest = value % 60;
  return rest ? `${hours} س ${rest} د` : `${hours} س`;
}

function activityTime(value) {
  if (!value) return `<span class="muted">لا يوجد نشاط</span>`;
  const [day, time = ""] = String(value).split("T");
  return `${fmt(day)}<div class="sub muted" dir="ltr">${esc(time.slice(0, 5))}</div>`;
}

function renderActivitySummary() {
  const s = ACTIVITY.summary;
  const activeRate = s.accounts ? Math.round((s.active_members / s.accounts) * 100) : 0;
  document.getElementById("activitySummary").innerHTML = `
    <div class="stat"><span>الحسابات النشطة</span><strong>${s.active_members}</strong>
      <div class="stat-sub">من ${s.accounts} حساب · ${activeRate}%</div></div>
    <div class="stat"><span>مرات تسجيل الدخول</span><strong>${s.logins}</strong></div>
    <div class="stat"><span>التعديلات المسجلة</span><strong>${s.changes}</strong></div>
    <div class="stat"><span>الوقت النشط التقديري</span><strong>${activityDuration(s.estimated_active_minutes)}</strong>
      <div class="stat-sub">بحد خمول ${ACTIVITY.estimate_idle_minutes} دقيقة</div></div>
    <div class="stat${s.failed_logins ? " stat-accent-red" : ""}"><span>محاولات دخول فاشلة</span><strong>${s.failed_logins}</strong></div>
    <div class="stat"><span>متوسط التعديل لكل نشط</span><strong>${s.active_members ? Math.round(s.changes / s.active_members * 10) / 10 : 0}</strong></div>`;
}

function destroyActivityCharts() {
  ACTIVITY_CHARTS.forEach(chart => chart.destroy());
  ACTIVITY_CHARTS = [];
}

function renderActivityCharts() {
  destroyActivityCharts();
  const daily = ACTIVITY.daily || [];
  ACTIVITY_CHARTS.push(new Chart(document.getElementById("activityDailyChart"), {
    type: "line",
    data: {
      labels: daily.map(row => fmtShort(row.day)),
      datasets: [
        {label: "التعديلات", data: daily.map(row => row.changes), borderColor: CT.navy,
          backgroundColor: CT.navy, tension: .28, pointRadius: 2, borderWidth: 2},
        {label: "مرات الدخول", data: daily.map(row => row.logins), borderColor: CT.cat[2],
          backgroundColor: CT.cat[2], tension: .28, pointRadius: 2, borderWidth: 2},
        {label: "حسابات نشطة", data: daily.map(row => row.active_members), borderColor: CT.cat[1],
          backgroundColor: CT.cat[1], tension: .28, pointRadius: 2, borderWidth: 2},
      ],
    },
    options: {...CHART_BASE, scales: vbarScales({ticks: {precision: 0}}, {ticks: {maxRotation: 0, autoSkip: true, maxTicksLimit: 10}}),
      plugins: {legend: {display: true, position: "top", align: "start",
        labels: {boxWidth: 12, padding: 14}}}},
  }));
  chartAlt("activityDailyChart", {
    lead: daily.length
      ? `أكثر الأيام تعديلًا: ${topList(daily.map(row => ({label: fmt(row.day), value: row.changes}))
        .sort((a, b) => b.value - a.value), v => countLabel(v, "تعديل"))}.`
      : "لا يوجد نشاط في هذا المدى.",
    head: ["اليوم", "التعديلات", "مرات الدخول", "حسابات نشطة"],
    rows: daily.map(row => [fmt(row.day), row.changes, row.logins, row.active_members]),
  });

  const byHour = ACTIVITY.by_hour || [];
  ACTIVITY_CHARTS.push(new Chart(document.getElementById("activityHoursChart"), {
    type: "bar",
    data: {labels: byHour.map(row => `${String(row.hour).padStart(2, "0")}:00`),
      datasets: [{data: byHour.map(row => row.events), backgroundColor: byHour.map(row =>
        row.events === Math.max(...byHour.map(item => item.events), 0) && row.events ? CT.warn : CT.navy),
        borderRadius: 3, borderSkipped: false, maxBarThickness: 18}]},
    options: {...CHART_BASE, scales: vbarScales({ticks: {precision: 0}}),
      plugins: {legend: {display: false}, tooltip: {callbacks: {label: ctx => ` ${ctx.raw} حدثًا مسجلًا`}}}},
  }));
  chartAlt("activityHoursChart", {
    lead: byHour.some(row => row.events)
      ? `أكثر الساعات نشاطًا: ${topList(byHour.map(row => ({label: `${String(row.hour).padStart(2, "0")}:00`, value: row.events}))
        .sort((a, b) => b.value - a.value), v => `${v} حدثًا`)}.`
      : "لا يوجد نشاط في هذا المدى.",
    head: ["الساعة", "الأحداث"],
    rows: byHour.map(row => [`${String(row.hour).padStart(2, "0")}:00`, row.events]),
  });
}

function activityMemberRow(member, maxVolume) {
  const volume = member.changes + member.logins;
  const width = maxVolume ? Math.max(volume ? 5 : 0, Math.round(volume / maxVolume * 100)) : 0;
  const security = member.failed_logins + member.denied_attempts;
  return `<tr>
    <td class="activity-person">
      <strong>${esc(member.display_name)}</strong>
      <div class="activity-person-meta"><span dir="ltr">@${esc(member.username)}</span>
        <span class="role-badge role-badge-sm role-${esc(member.role)}">${esc(member.role_label)}</span>
        ${member.active ? "" : '<span class="chip err">موقوف</span>'}</div>
      <div class="activity-volume" title="حجم النشاط: ${volume}"><span style="width:${width}%"></span></div>
    </td>
    <td class="n"><strong>${activityDuration(member.estimated_active_minutes)}</strong><div class="sub muted">تقديري</div></td>
    <td class="n">${member.logins}</td>
    <td class="n"><strong>${member.changes}</strong><div class="sub muted">${member.changes_per_active_day} / يوم نشط</div></td>
    <td class="n">${member.active_days}</td>
    <td class="wrap">${member.top_action ? esc(member.top_action) : '<span class="muted">—</span>'}</td>
    <td class="wrap">${activityTime(member.last_activity)}</td>
    <td class="n">${security ? `<span class="chip err">${security}</span><div class="sub muted">${member.failed_logins} دخول · ${member.denied_attempts} منع</div>` : '<span class="chip done">0</span>'}</td>
  </tr>`;
}

function renderActivityMembers() {
  const query = document.getElementById("activityMemberSearch").value.trim();
  const role = document.getElementById("activityRoleFilter").value;
  const rows = (ACTIVITY.members || []).filter(member => {
    if (role && member.role !== role) return false;
    return !query || arIncludes(`${member.display_name} ${member.username}`, query);
  });
  document.getElementById("activityMemberCount").textContent = `${rows.length} من ${ACTIVITY.members.length} حساب`;
  const wrap = document.getElementById("activityMembers");
  if (!rows.length) {
    wrap.innerHTML = emptyState({icon: "search", title: "لا توجد حسابات مطابقة",
      hint: "غيّر نص البحث أو فلتر الدور."});
    return;
  }
  const maxVolume = Math.max(...rows.map(member => member.changes + member.logins), 0);
  wrap.innerHTML = `<div class="table-scroll">${mtable([
    "الحساب", "وقت نشط", "الدخول", "التعديلات", "أيام النشاط", "أكثر قسم تعديلًا", "آخر نشاط", "تنبيهات أمنية"
  ], rows.map(member => activityMemberRow(member, maxVolume)))}</div>`;
}

async function loadActivityStats() {
  document.getElementById("activityMembers").innerHTML = skeleton("rows", 8);
  const params = new URLSearchParams({from: document.getElementById("asFrom").value,
    to: document.getElementById("asTo").value});
  const data = await api(`/api/activity-stats?${params}`);
  if (!data) return;
  ACTIVITY = data;
  document.getElementById("activityRangeStamp").textContent = `${fmt(data.date_from)} — ${fmt(data.date_to)}`;
  renderActivitySummary();
  renderActivityCharts();
  renderActivityMembers();
}

function setActivityRange(daysBack, monthStart = false) {
  const today = curDate();
  document.getElementById("asTo").value = today;
  document.getElementById("asFrom").value = monthStart ? `${today.slice(0, 8)}01` : addDays(today, -daysBack);
  loadActivityStats();
}

document.getElementById("asPreset7").onclick = () => setActivityRange(6);
document.getElementById("asPreset30").onclick = () => setActivityRange(29);
document.getElementById("asPresetMonth").onclick = () => setActivityRange(0, true);
document.getElementById("asRefresh").onclick = () => loadActivityStats();
document.getElementById("asFrom").onchange = () => loadActivityStats();
document.getElementById("asTo").onchange = () => loadActivityStats();
document.getElementById("activityRoleFilter").onchange = renderActivityMembers;
document.getElementById("activityMemberSearch").addEventListener("input", debounce(renderActivityMembers, 150));

(async () => {
  if (!(await bootstrap())) return;
  document.getElementById("asTo").value = curDate();
  document.getElementById("asFrom").value = addDays(curDate(), -29);
  loadActivityStats();
})();
