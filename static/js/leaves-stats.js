/* إحصائيات الراحات — leaves-stats.js
   يحمّل /api/leaves/stats ويرسم المخططات. الثيم والاتجاه (RTL) والألوان من
   charts.js — نفس رموز باقي النظام، مش باليتة تانية. */

const monthLabel = ym => {
  if (!ym) return ym;
  const [y, m] = ym.split("-");
  return new Date(`${y}-${m}-15T12:00:00`).toLocaleDateString("ar-EG-u-nu-latn", { month: "short", year: "2-digit" });
};

/* توزيع الأنواع: أعمدة أفقية مرتبة تنازليًا بدل دونات بسبع ألوان متقاربة */
function drawTypeChart(data) {
  const entries = Object.entries(data.by_type).sort((a, b) => b[1] - a[1]);
  const total = data.summary.total || 1;
  new Chart(document.getElementById("typeChart"), {
    type: "bar",
    data: { labels: entries.map(e => e[0]),
      datasets: [{ data: entries.map(e => e[1]), backgroundColor: CT.navy, borderRadius: 4,
        borderSkipped: false, maxBarThickness: 20 }] },
    options: {
      ...CHART_BASE,
      indexAxis: "y",
      scales: hbarScales(),
      plugins: { legend: { display: false },
        tooltip: { callbacks: { label: ctx => ` ${countLabel(ctx.raw, "راحة")} (${Math.round(ctx.raw / total * 100)}%)` } } },
    },
  });
  chartAlt("typeChart", {
    lead: `الأكثر شيوعًا: ${topList(entries.map(([label, value]) => ({ label, value })), v => countLabel(v, "راحة"))}.`,
    head: ["النوع", "عدد الراحات", "النسبة"],
    rows: entries.map(([k, n]) => [k, n, `${Math.round(n / total * 100)}%`]),
  });
}

/* الحالة الراهنة: 95% من الدونات كانت «منتهية» فمكانتش بتقول حاجة —
   بقت تلات أرقام واضحة */
function drawStatusChart(data) {
  const c = data.status_counts || {};
  const box = document.getElementById("statusNumbers");
  if (!box) return;
  box.innerHTML = [["جارية", "جارية الآن", "info"], ["قادمة", "قادمة", "navy"], ["منتهية", "منتهية", "muted"]]
    .map(([k, label, cls]) => `<div class="status-number ${cls}"><strong>${c[k] || 0}</strong><span>${label}</span></div>`).join("");
}

function drawMonthChart(data) {
  const keys = Object.keys(data.by_month);
  const values = Object.values(data.by_month);
  const current = curDate().slice(0, 7);
  chartLegend("monthChart", [["gold", "الشهر الحالي"], ["navy", "باقي الشهور"]]);
  new Chart(document.getElementById("monthChart"), {
    type: "bar",
    data: { labels: keys.map(monthLabel), datasets: [{ data: values,
      backgroundColor: keys.map(k => k === current ? CT.gold : CT.navy),
      borderRadius: 6, borderSkipped: false, maxBarThickness: 56 }] },
    options: {
      ...CHART_BASE,
      scales: vbarScales(),
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: ctx => ` ${countLabel(ctx.raw, "راحة")}` } } },
    },
  });
  const months = keys.map((k, i) => ({ label: monthLabel(k), value: values[i] }));
  chartAlt("monthChart", {
    lead: `الأعلى شهريًا: ${topList([...months].sort((a, b) => b.value - a.value), v => countLabel(v, "راحة"))}.`,
    head: ["الشهر", "عدد الراحات"],
    rows: months.map(m => [m.label, m.value]),
  });
}

function drawOfficerChart(data) {
  const rows = data.top_officers;
  new Chart(document.getElementById("officerChart"), {
    type: "bar",
    data: {
      labels: uniqueShortNames(rows.map(o => o.name)),
      datasets: [
        { label: "عدد الراحات", data: rows.map(o => o.count), backgroundColor: CT.navy, borderRadius: 4, borderSkipped: false, maxBarThickness: 12 },
        { label: "إجمالي الأيام", data: rows.map(o => o.days), backgroundColor: CT.navySoft, borderRadius: 4, borderSkipped: false, maxBarThickness: 12 },
      ],
    },
    options: {
      ...CHART_BASE,
      indexAxis: "y",
      scales: hbarScales(),
      plugins: {
        legend: { display: true, position: "top", align: "start", labels: { boxWidth: 12, padding: 16 } },
        tooltip: { callbacks: {
          title: items => rows[items[0].dataIndex].name,
          label: ctx => ctx.datasetIndex === 0 ? ` ${countLabel(ctx.raw, "راحة")}` : ` ${countLabel(ctx.raw, "يوم")}`,
        }},
      },
    },
  });
  chartAlt("officerChart", {
    lead: `الأكثر راحات: ${topList(rows.map(o => ({ label: o.name, value: o.count })), v => countLabel(v, "راحة"))}.`,
    head: ["الضابط", "عدد الراحات", "إجمالي الأيام"],
    rows: rows.map(o => [o.name, o.count, o.days]),
  });
}

function drawDurationChart(data) {
  const labels = Object.keys(data.duration_buckets);
  new Chart(document.getElementById("durationChart"), {
    type: "bar",
    data: { labels, datasets: [{ data: Object.values(data.duration_buckets), backgroundColor: CT.navy,
      borderRadius: 6, borderSkipped: false, maxBarThickness: 56 }] },
    options: {
      ...CHART_BASE,
      scales: vbarScales(),
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: ctx => ` ${countLabel(ctx.raw, "راحة")}` } } },
    },
  });
  const buckets = Object.entries(data.duration_buckets).map(([label, value]) => ({ label, value }));
  chartAlt("durationChart", {
    lead: `الأكثر شيوعًا: ${topList([...buckets].sort((a, b) => b.value - a.value), v => countLabel(v, "راحة"))}.`,
    head: ["المدة", "عدد الراحات"],
    rows: buckets.map(b => [b.label, b.value]),
  });
}

function drawWeekdayChart(data) {
  // نفس بداية الأسبوع في كل النظام: السبت أولًا (على اليمين)
  const order = ["السبت", "الأحد", "الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة"];
  const values = order.map(d => data.by_weekday[d] || 0);
  const maxVal = values.length ? Math.max(...values) : 0;
  chartLegend("weekdayChart", [["gold", "اليوم الأكثر بداية للراحات"], ["navy", "باقي الأيام"]]);
  new Chart(document.getElementById("weekdayChart"), {
    type: "bar",
    data: { labels: order, datasets: [{ data: values,
      backgroundColor: values.map(v => v === maxVal && v > 0 ? CT.gold : CT.navy),
      borderRadius: 6, borderSkipped: false, maxBarThickness: 44 }] },
    options: {
      ...CHART_BASE,
      scales: vbarScales(),
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: ctx => ` ${countLabel(ctx.raw, "راحة")}` } } },
    },
  });
  const days = order.map((label, i) => ({ label, value: values[i] }));
  chartAlt("weekdayChart", {
    lead: maxVal > 0
      ? `الأكثر بداية للراحات: ${topList([...days].sort((a, b) => b.value - a.value), v => countLabel(v, "راحة"))}.`
      : "لا توجد راحات في هذا المدى.",
    head: ["اليوم", "عدد الراحات"],
    rows: days.map(d => [d.label, d.value]),
  });
}

function drawCumulativeChart(data) {
  new Chart(document.getElementById("cumulativeChart"), {
    type: "line",
    data: {
      labels: data.cumulative.map(c => monthLabel(c.month)),
      datasets: [{ data: data.cumulative.map(c => c.total), borderColor: CT.navy, backgroundColor: CT.navySoft,
        borderWidth: 2.5, pointBackgroundColor: CT.navy, pointRadius: 4, pointHoverRadius: 6, fill: true, tension: 0.3 }],
    },
    options: {
      ...CHART_BASE,
      scales: vbarScales(),
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: ctx => ` ${countLabel(ctx.raw, "راحة")} تراكميًا` } } },
    },
  });
  const cum = data.cumulative;
  chartAlt("cumulativeChart", {
    lead: cum.length
      ? `بلغ الإجمالي التراكمي ${countLabel(cum[cum.length - 1].total, "راحة")} حتى ${monthLabel(cum[cum.length - 1].month)}.`
      : "لا توجد بيانات تراكمية.",
    head: ["الشهر", "الإجمالي التراكمي"],
    rows: cum.map(c => [monthLabel(c.month), c.total]),
  });
}

function renderSummary(s) {
  document.getElementById("summaryStats").innerHTML = `
    <div class="stat">
      <span>إجمالي الراحات</span><strong>${s.total}</strong>
      <div class="stat-sub">المجموع ${countLabel(s.total_days, "يوم")}</div>
    </div>
    <div class="stat">
      <span>متوسط المدة</span><strong>${s.avg_duration}</strong>
      <div class="stat-sub">يوم لكل راحة</div>
    </div>
    <div class="stat">
      <span>جارية الآن</span><strong>${s.current}</strong>
      <div class="stat-sub">راحة نشطة اليوم</div>
    </div>
    <div class="stat">
      <span>قادمة</span><strong>${s.upcoming}</strong>
      <div class="stat-sub">لم تبدأ بعد</div>
    </div>`;
}

// ── الفلاتر والتحميل ────────────────────────────────────────────
let optionsPopulated = false;

function populateFilterOptions(metaOptions) {
  if (optionsPopulated || !metaOptions) return;

  const mFromEl = document.getElementById("lsFilterMonthFrom");
  const mToEl   = document.getElementById("lsFilterMonthTo");
  const typeEl = document.getElementById("lsFilterType");

  if (mFromEl && metaOptions.months) {
    metaOptions.months.forEach(m => {
      const lbl = monthLabel(m);
      mFromEl.add(new Option(lbl, m));
      mToEl.add(new Option(lbl, m));
    });
  }

  if (typeEl && metaOptions.types) {
    metaOptions.types.forEach(t => {
      typeEl.add(new Option(t, t));
    });
  }

  optionsPopulated = true;
}

function getFilterParams() {
  const mFrom = document.getElementById("lsFilterMonthFrom")?.value || "";
  const mTo = document.getElementById("lsFilterMonthTo")?.value || "";
  const type = document.getElementById("lsFilterType")?.value || "";
  const status = document.getElementById("lsFilterStatus")?.value || "";

  const params = new URLSearchParams();
  if (mFrom) params.set("month_from", mFrom);
  if (mTo) params.set("month_to", mTo);
  if (type) params.set("type", type);
  if (status) params.set("status", status);

  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

async function load() {
  // تدمير المخططات الحالية قبل إعادة الرسم
  Chart.helpers.each(Chart.instances, c => c.destroy());

  // تحميل Bootstrap للـ meta والأعداد والتاريخ
  const bd = await bootstrap();

  const query = getFilterParams();
  const d = await api(`/api/leaves/stats${query}`);
  if (!d) return;

  populateFilterOptions(d.meta_options);

  renderSummary(d.summary);
  drawTypeChart(d);
  drawStatusChart(d);
  drawMonthChart(d);
  drawOfficerChart(d);
  drawDurationChart(d);
  drawWeekdayChart(d);
  drawCumulativeChart(d);
}

// ── ربط الأحداث للفلاتر ───────────────────────────────────────
["lsFilterMonthFrom", "lsFilterMonthTo", "lsFilterType", "lsFilterStatus"].forEach(id => {
  const el = document.getElementById(id);
  if (el) el.onchange = () => load();
});

function resetFilters() {
  ["lsFilterMonthFrom", "lsFilterMonthTo", "lsFilterType", "lsFilterStatus"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = "";
  });
  load();
}

document.getElementById("lsResetFilters").onclick = resetFilters;

document.getElementById("lsPresetAll").onclick = resetFilters;

document.getElementById("lsPresetThisMonth").onclick = () => {
  resetFilters();
  const today = new Date();
  const ym = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}`;
  const mFrom = document.getElementById("lsFilterMonthFrom");
  const mTo = document.getElementById("lsFilterMonthTo");
  if (mFrom) mFrom.value = ym;
  if (mTo) mTo.value = ym;
  load();
};

document.getElementById("lsPresetLast3Months").onclick = () => {
  resetFilters();
  const today = new Date();
  const mToYm = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}`;

  const d3 = new Date(today.getFullYear(), today.getMonth() - 2, 1);
  const mFromYm = `${d3.getFullYear()}-${String(d3.getMonth() + 1).padStart(2, '0')}`;

  const mFrom = document.getElementById("lsFilterMonthFrom");
  const mTo = document.getElementById("lsFilterMonthTo");
  if (mFrom) mFrom.value = mFromYm;
  if (mTo) mTo.value = mToYm;
  load();
};

document.getElementById("refreshBtn").onclick = () => {
  load();
};

load();
