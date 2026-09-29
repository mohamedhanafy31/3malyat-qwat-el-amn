/* إحصائيات تشغيل الضباط — duty-stats.js
   يحمّل /api/duty/stats ويرسم توازن وانتظام التشغيل الفعلي بـ Chart.js */

Chart.defaults.font.family = getComputedStyle(document.documentElement).getPropertyValue('--font-body').trim();
Chart.defaults.font.size = 13;
Chart.defaults.color = "#374151";
Chart.defaults.animation.duration = 600;

const BASE_OPTS = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: { legend: { display: false } },
};

const shortName = name => {
  const parts = name.split(" ");
  return parts.length > 2 ? parts.slice(0, 2).join(" ") : name;
};

/* خط المتوسط فوق عمود أفقي — Chart.js مالوش annotation plugin هنا، فبنرسم
   خط بسيط كـdataset من نوع line فوق نفس المحاور. */
function averageLinePlugin(avg) {
  return {
    id: "avgLine",
    afterDraw(chart) {
      const { ctx, chartArea, scales } = chart;
      const x = scales.x.getPixelForValue(avg);
      ctx.save();
      ctx.strokeStyle = "#dc2626";
      ctx.setLineDash([5, 4]);
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(x, chartArea.top);
      ctx.lineTo(x, chartArea.bottom);
      ctx.stroke();
      ctx.restore();
    },
  };
}

function drawLoadChart(data) {
  const rows = data.by_officer_load;
  const labels = rows.map(r => shortName(r.name));
  const values = rows.map(r => r.total);
  const avg = values.length ? values.reduce((a, b) => a + b, 0) / values.length : 0;

  new Chart(document.getElementById("loadChart"), {
    type: "bar",
    data: {
      labels,
      datasets: [{
        data: values,
        backgroundColor: values.map(v => v > avg * 1.3 ? "#dc2626" : v < avg * 0.7 ? "#d97706" : "#1e3a5a"),
        borderRadius: 4, borderSkipped: false,
      }],
    },
    options: {
      ...BASE_OPTS,
      indexAxis: "y",
      scales: {
        x: { grid: { color: "#f1f5f9" }, beginAtZero: true },
        y: { grid: { display: false }, ticks: { font: { size: 11 } } },
      },
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: {
          label: ctx => {
            const r = rows[ctx.dataIndex];
            const byKind = Object.entries(r.by_kind).map(([k, n]) => `${k}: ${n}`).join("، ");
            return [` الإجمالي: ${r.total}`, ` ${byKind || "—"}`];
          },
        }},
      },
    },
    plugins: [averageLinePlugin(avg)],
  });
}

function drawNetChart(data) {
  const rows = [...data.net_rate].sort((a, b) => b.rate - a.rate);
  const labels = rows.map(r => shortName(r.name));
  const values = rows.map(r => r.rate);

  new Chart(document.getElementById("netChart"), {
    type: "bar",
    data: {
      labels,
      datasets: [{ data: values, backgroundColor: "#6b7280", borderRadius: 4, borderSkipped: false }],
    },
    options: {
      ...BASE_OPTS,
      indexAxis: "y",
      scales: {
        x: { grid: { color: "#f1f5f9" }, beginAtZero: true, max: 100 },
        y: { grid: { display: false }, ticks: { font: { size: 11 } } },
      },
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: {
          label: ctx => {
            const r = rows[ctx.dataIndex];
            return ` ${r.rate}% — ${r.net_days} من ${r.total_days} يوم`;
          },
        }},
      },
    },
  });
}

function drawShiftChart(data) {
  const rows = data.shift_balance;
  const labels = rows.map(r => shortName(r.name));

  new Chart(document.getElementById("shiftChart"), {
    type: "bar",
    data: {
      labels,
      datasets: [
        { label: "صباحية", data: rows.map(r => r.morning), backgroundColor: "#d97706", borderRadius: 3, borderSkipped: false },
        { label: "ليلية", data: rows.map(r => r.night), backgroundColor: "#1e3a5a", borderRadius: 3, borderSkipped: false },
      ],
    },
    options: {
      ...BASE_OPTS,
      indexAxis: "y",
      scales: {
        x: { grid: { color: "#f1f5f9" }, beginAtZero: true },
        y: { grid: { display: false }, ticks: { font: { size: 11 } } },
      },
      plugins: { legend: { display: true, position: "top", labels: { boxWidth: 12, padding: 16 } } },
    },
  });
}

function drawTaqseeraChart(data) {
  const rows = data.taqseera_count;
  const el = document.getElementById("taqseeraChart");
  if (!rows.length) {
    el.closest(".ls-chart-wrap").innerHTML = `<div class="mempty">مفيش تقصيرات في المدى ده</div>`;
    return;
  }
  new Chart(el, {
    type: "bar",
    data: {
      labels: rows.map(r => shortName(r.name)),
      datasets: [{ data: rows.map(r => r.count), backgroundColor: "#dc2626", borderRadius: 4, borderSkipped: false }],
    },
    options: {
      ...BASE_OPTS,
      indexAxis: "y",
      scales: {
        x: { grid: { color: "#f1f5f9" }, beginAtZero: true, ticks: { stepSize: 1 } },
        y: { grid: { display: false }, ticks: { font: { size: 11 } } },
      },
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: ctx => ` ${ctx.raw} تقصيرة` } },
      },
    },
  });
}

function drawWeekdayChart(data) {
  const order = WEEKDAYS();
  const byName = Object.fromEntries(data.by_weekday.map(w => [w.weekday, w]));
  const labels = order;
  const values = order.map(w => byName[w]?.services || 0);
  const maxVal = values.length ? Math.max(...values) : 0;

  new Chart(document.getElementById("weekdayChart"), {
    type: "bar",
    data: {
      labels,
      datasets: [{
        data: values,
        backgroundColor: values.map(v => v === maxVal && v > 0 ? "#16a34a" : "#86efac"),
        borderRadius: 6, borderSkipped: false,
      }],
    },
    options: {
      ...BASE_OPTS,
      scales: {
        x: { grid: { display: false } },
        y: { grid: { color: "#f1f5f9" }, beginAtZero: true },
      },
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: {
          label: ctx => {
            const w = byName[order[ctx.dataIndex]];
            return [` ${ctx.raw} خدمة عبر ${w?.days || 0} يوم`, ` صافي: ${w?.net || 0} مرة`];
          },
        }},
      },
    },
  });
}

function renderTargetGapTable(rows) {
  const body = rows.length
    ? `<div class="table-scroll">${mtable(["الهدف", "أيام التعيين", "أيام معروف فيها القائد", "أيام الفجوة", "نسبة الفجوة"], rows.map(r => `
      <tr>
        <td class="name">${esc(r.name)}</td>
        <td>${r.assigned_days}</td>
        <td>${r.commander_known_days}</td>
        <td>${r.mismatch_days}</td>
        <td>${r.mismatch_rate === null ? "<span class='muted'>—</span>" : `<b>${r.mismatch_rate}%</b>`}</td>
      </tr>`))}</div>`
    : `<div class="mempty">مفيش بيانات في المدى ده</div>`;
  document.getElementById("targetGapTable").innerHTML = body;
}

function renderSummary(d) {
  document.getElementById("summaryStats").innerHTML = `
    <div class="stat">
      <span>عدد الأيام</span><strong>${d.days_count}</strong>
      <div class="stat-sub">${fmt(d.date_from)} — ${fmt(d.date_to)}</div>
    </div>
    <div class="stat">
      <span>ضباط شُغّلوا</span><strong>${d.by_officer_load.length}</strong>
    </div>`;
}

function getFilterParams() {
  const from = document.getElementById("dsFrom")?.value || "";
  const to = document.getElementById("dsTo")?.value || "";
  const params = new URLSearchParams();
  if (from) params.set("date_from", from);
  if (to) params.set("date_to", to);
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

async function load() {
  Chart.helpers.each(Chart.instances, c => c.destroy());
  if (!(await bootstrap())) return;

  const query = getFilterParams();
  const d = await api(`/api/duty/stats${query}`);
  if (!d) return;

  document.getElementById("dsFrom").value = d.date_from;
  document.getElementById("dsTo").value = d.date_to;

  renderSummary(d);
  drawLoadChart(d);
  drawNetChart(d);
  drawShiftChart(d);
  renderTargetGapTable(d.target_gap);
  drawTaqseeraChart(d);
  drawWeekdayChart(d);
}

["dsFrom", "dsTo"].forEach(id => { document.getElementById(id).onchange = () => load(); });

document.getElementById("dsPreset7").onclick = () => {
  document.getElementById("dsFrom").value = addDays(curDate(), -6);
  document.getElementById("dsTo").value = curDate();
  load();
};
document.getElementById("dsPreset30").onclick = () => {
  document.getElementById("dsFrom").value = addDays(curDate(), -29);
  document.getElementById("dsTo").value = curDate();
  load();
};
document.getElementById("dsPresetMonth").onclick = () => {
  const today = curDate();
  document.getElementById("dsFrom").value = today.slice(0, 8) + "01";
  document.getElementById("dsTo").value = today;
  load();
};

document.getElementById("refreshBtn").onclick = () => load();

load();
