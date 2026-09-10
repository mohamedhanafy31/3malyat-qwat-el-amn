/* إحصائيات الراحات — leaves-stats.js
   يحمّل /api/leaves/stats ويرسم 6 مخططات بـ Chart.js */

// ── ألوان النظام ──────────────────────────────────────────────
const PALETTE = {
  types: {
    "أسبوعية":      "#2563eb",
    "نصف شهرية":   "#7c3aed",
    "شهرية":        "#0891b2",
    "راحة":         "#16a34a",
    "إجازة طارئة": "#dc2626",
    "إجازة مصيف":  "#d97706",
    "راحة فرقة":   "#9333ea",
    "غير محدد":     "#6b7280",
  },
  status: {
    "جارية":  "#dc2626",
    "قادمة":  "#2563eb",
    "منتهية": "#6b7280",
  },
  bar:        "#1e3a5a",
  barHover:   "#2563eb",
  line:       "#0891b2",
  duration:   ["#2563eb", "#7c3aed", "#0891b2", "#d97706"],
  weekday:    "#16a34a",
};

// ── إعدادات Chart.js العامة ──────────────────────────────────
Chart.defaults.font.family   = "'Tajawal', 'Segoe UI', sans-serif";
Chart.defaults.font.size     = 13;
Chart.defaults.color         = "#374151";
Chart.defaults.animation.duration = 600;

const BASE_OPTS = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: { legend: { display: false } },
};

// ── مساعدات ──────────────────────────────────────────────────
const monthLabel = ym => {
  if (!ym) return ym;
  const [y, m] = ym.split("-");
  return new Date(`${y}-${m}-15T12:00:00`).toLocaleDateString("ar-EG", { month: "short", year: "2-digit" });
};

function buildLegend(containerId, labels, colors, values) {
  const el = document.getElementById(containerId);
  if (!el) return;
  el.innerHTML = labels.map((l, i) => `
    <div class="ls-legend-item">
      <span class="ls-legend-dot" style="background:${colors[i]}"></span>
      <span class="ls-legend-label">${l}</span>
      <span class="ls-legend-val">${values[i]}</span>
    </div>`).join("");
}

// ── رسم المخططات ──────────────────────────────────────────────

function drawTypeChart(data) {
  const labels = Object.keys(data.by_type);
  const values = Object.values(data.by_type);
  const colors = labels.map(l => PALETTE.types[l] || "#6b7280");

  new Chart(document.getElementById("typeChart"), {
    type: "doughnut",
    data: { labels, datasets: [{ data: values, backgroundColor: colors, borderWidth: 2, borderColor: "#fff", hoverOffset: 8 }] },
    options: {
      ...BASE_OPTS,
      cutout: "68%",
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: {
          label: ctx => ` ${ctx.label}: ${ctx.raw} راحة (${Math.round(ctx.raw / data.summary.total * 100)}%)`
        }}
      }
    }
  });
  buildLegend("typeLegend", labels, colors, values);
}

function drawStatusChart(data) {
  const labels = Object.keys(data.status_counts);
  const values = Object.values(data.status_counts);
  const colors = labels.map(l => PALETTE.status[l] || "#6b7280");

  new Chart(document.getElementById("statusChart"), {
    type: "doughnut",
    data: { labels, datasets: [{ data: values, backgroundColor: colors, borderWidth: 2, borderColor: "#fff", hoverOffset: 8 }] },
    options: {
      ...BASE_OPTS,
      cutout: "68%",
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: {
          label: ctx => ` ${ctx.label}: ${ctx.raw}`
        }}
      }
    }
  });
  buildLegend("statusLegend", labels, colors, values);
}

function drawMonthChart(data) {
  const labels = Object.keys(data.by_month).map(monthLabel);
  const values = Object.values(data.by_month);
  const maxVal = values.length ? Math.max(...values) : 0;

  new Chart(document.getElementById("monthChart"), {
    type: "bar",
    data: {
      labels,
      datasets: [{
        data: values,
        backgroundColor: values.map(v => v === maxVal ? "#2563eb" : "#93c5fd"),
        borderRadius: 6,
        borderSkipped: false,
      }]
    },
    options: {
      ...BASE_OPTS,
      scales: {
        x: { grid: { display: false }, ticks: { font: { size: 12 } } },
        y: { grid: { color: "#f1f5f9" }, beginAtZero: true, ticks: { stepSize: 10 } }
      },
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: ctx => ` ${ctx.raw} راحة` } }
      }
    }
  });
}

function drawOfficerChart(data) {
  const labels = data.top_officers.map(o => {
    // اختصار الاسم لو طويل
    const parts = o.name.split(" ");
    return parts.length > 2 ? parts.slice(0, 2).join(" ") : o.name;
  });
  const counts = data.top_officers.map(o => o.count);
  const days   = data.top_officers.map(o => o.days);

  new Chart(document.getElementById("officerChart"), {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: "عدد الراحات",
          data: counts,
          backgroundColor: "#1e3a5a",
          borderRadius: 4,
          borderSkipped: false,
        },
        {
          label: "إجمالي الأيام",
          data: days,
          backgroundColor: "#93c5fd",
          borderRadius: 4,
          borderSkipped: false,
        }
      ]
    },
    options: {
      ...BASE_OPTS,
      indexAxis: "y",
      scales: {
        x: { grid: { color: "#f1f5f9" }, beginAtZero: true },
        y: { grid: { display: false }, ticks: { font: { size: 11 } } }
      },
      plugins: {
        legend: { display: true, position: "top", labels: { boxWidth: 12, padding: 16 } },
        tooltip: { callbacks: {
          label: ctx => ctx.datasetIndex === 0
            ? ` ${ctx.raw} راحة`
            : ` ${ctx.raw} يوم`
        }}
      }
    }
  });
}

function drawDurationChart(data) {
  const labels = Object.keys(data.duration_buckets);
  const values = Object.values(data.duration_buckets);

  new Chart(document.getElementById("durationChart"), {
    type: "bar",
    data: {
      labels,
      datasets: [{
        data: values,
        backgroundColor: PALETTE.duration,
        borderRadius: 6,
        borderSkipped: false,
      }]
    },
    options: {
      ...BASE_OPTS,
      scales: {
        x: { grid: { display: false } },
        y: { grid: { color: "#f1f5f9" }, beginAtZero: true }
      },
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: ctx => ` ${ctx.raw} راحة` } }
      }
    }
  });
}

function drawWeekdayChart(data) {
  const ORDER = ["الأحد","الاثنين","الثلاثاء","الأربعاء","الخميس","الجمعة","السبت"];
  const labels = ORDER;
  const values = ORDER.map(d => data.by_weekday[d] || 0);
  const maxVal = values.length ? Math.max(...values) : 0;

  new Chart(document.getElementById("weekdayChart"), {
    type: "bar",
    data: {
      labels,
      datasets: [{
        data: values,
        backgroundColor: values.map(v => v === maxVal ? "#16a34a" : "#86efac"),
        borderRadius: 6,
        borderSkipped: false,
      }]
    },
    options: {
      ...BASE_OPTS,
      scales: {
        x: { grid: { display: false } },
        y: { grid: { color: "#f1f5f9" }, beginAtZero: true }
      },
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: ctx => ` ${ctx.raw} راحة` } }
      }
    }
  });
}

function drawCumulativeChart(data) {
  const labels = data.cumulative.map(c => monthLabel(c.month));
  const values = data.cumulative.map(c => c.total);

  new Chart(document.getElementById("cumulativeChart"), {
    type: "line",
    data: {
      labels,
      datasets: [{
        data: values,
        borderColor: "#0891b2",
        backgroundColor: "rgba(8,145,178,0.12)",
        borderWidth: 2.5,
        pointBackgroundColor: "#0891b2",
        pointRadius: 4,
        pointHoverRadius: 6,
        fill: true,
        tension: 0.35,
      }]
    },
    options: {
      ...BASE_OPTS,
      scales: {
        x: { grid: { display: false } },
        y: { grid: { color: "#f1f5f9" }, beginAtZero: true }
      },
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: ctx => ` ${ctx.raw} راحة تراكمياً` } }
      }
    }
  });
}

// ── شريط الملخص ───────────────────────────────────────────────
function renderSummary(s) {
  document.getElementById("summaryStats").innerHTML = `
    <div class="stat stat-accent-red">
      <span>إجمالي الراحات</span><strong>${s.total}</strong>
      <div class="stat-sub">${s.total_days} يوم مجموع</div>
    </div>
    <div class="stat stat-accent-blue">
      <span>متوسط المدة</span><strong>${s.avg_duration}</strong>
      <div class="stat-sub">يوم لكل راحة</div>
    </div>
    <div class="stat stat-accent-orange">
      <span>جارية الآن</span><strong>${s.current}</strong>
      <div class="stat-sub">راحة نشطة اليوم</div>
    </div>
    <div class="stat stat-accent-purple">
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
  const category = document.getElementById("lsFilterCategory")?.value || "";

  const params = new URLSearchParams();
  if (mFrom) params.set("month_from", mFrom);
  if (mTo) params.set("month_to", mTo);
  if (type) params.set("type", type);
  if (status) params.set("status", status);
  if (category) params.set("category", category);

  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

async function load() {
  // تدمير المخططات الحالية قبل إعادة الرسم
  Chart.helpers.each(Chart.instances, c => c.destroy());

  // تحميل Bootstrap للـ meta (تاريخ اليوم)
  const bd = await api("/api/bootstrap/leaves");
  if (bd) {
    const el = document.getElementById("today");
    if (el) el.textContent = new Date(bd.meta?.today + "T00:00:00")
      .toLocaleDateString("ar-EG", { weekday: "long", year: "numeric", month: "long", day: "numeric" });
  }

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
["lsFilterMonthFrom", "lsFilterMonthTo", "lsFilterType", "lsFilterStatus", "lsFilterCategory"].forEach(id => {
  const el = document.getElementById(id);
  if (el) el.onchange = () => load();
});

function resetFilters() {
  ["lsFilterMonthFrom", "lsFilterMonthTo", "lsFilterType", "lsFilterStatus", "lsFilterCategory"].forEach(id => {
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
