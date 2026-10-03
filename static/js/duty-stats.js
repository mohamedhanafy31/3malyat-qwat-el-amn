/* إحصائيات تشغيل الضباط — duty-stats.js
   يحمّل /api/duty/stats ويرسم توازن وانتظام التشغيل الفعلي. الثيم والاتجاه
   (RTL) والألوان من charts.js. */

/* خط المتوسط فوق الأعمدة الأفقية + عنوانه */
function averageLinePlugin(avg) {
  return {
    id: "avgLine",
    afterDraw(chart) {
      const { ctx, chartArea, scales } = chart;
      const x = scales.x.getPixelForValue(avg);
      ctx.save();
      ctx.strokeStyle = CT.inkStrong;
      ctx.setLineDash([5, 4]);
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(x, chartArea.top);
      ctx.lineTo(x, chartArea.bottom);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = CT.inkStrong;
      ctx.font = `600 12px ${CT.font}`;
      ctx.textAlign = "center";
      ctx.fillText(`المتوسط: ${Math.round(avg * 10) / 10}`, x, chartArea.top - 6);
      ctx.restore();
    },
  };
}

function drawLoadChart(data) {
  const rows = data.by_officer_load;
  const labels = uniqueShortNames(rows.map(r => r.name));
  const values = rows.map(r => r.total);
  const avg = values.length ? values.reduce((a, b) => a + b, 0) / values.length : 0;
  // اللون بيقول المسافة عن المتوسط — والمفتاح فوق الرسم بيشرح ده
  const colorOf = v => v > avg * 1.3 ? CT.gold : v < avg * 0.7 ? CT.navySoft : CT.navy;
  chartLegend("loadChart", [["gold", "أعلى من المتوسط بوضوح"], ["navy", "قريب من المتوسط"], ["soft", "أقل من المتوسط بوضوح"]]);
  new Chart(document.getElementById("loadChart"), {
    type: "bar",
    data: { labels, datasets: [{ data: values, backgroundColor: values.map(colorOf),
      borderRadius: 4, borderSkipped: false, maxBarThickness: 18 }] },
    options: {
      ...CHART_BASE,
      indexAxis: "y",
      layout: { padding: { top: 18 } },
      scales: hbarScales(),
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: {
          title: items => fullName(rows[items[0].dataIndex]),
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
  new Chart(document.getElementById("netChart"), {
    type: "bar",
    data: { labels: uniqueShortNames(rows.map(r => r.name)),
      datasets: [{ data: rows.map(r => r.rate), backgroundColor: CT.navy, borderRadius: 4,
        borderSkipped: false, maxBarThickness: 18 }] },
    options: {
      ...CHART_BASE,
      indexAxis: "y",
      scales: hbarScales({ max: 100, ticks: { font: { size: 12 }, callback: v => `${v}%` } }),
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: {
          title: items => fullName(rows[items[0].dataIndex]),
          label: ctx => { const r = rows[ctx.dataIndex]; return ` ${r.rate}% — ${r.net_days} من ${countLabel(r.total_days, "يوم")}`; },
        }},
      },
    },
  });
}

function drawShiftChart(data) {
  const rows = data.shift_balance;
  new Chart(document.getElementById("shiftChart"), {
    type: "bar",
    data: {
      labels: uniqueShortNames(rows.map(r => r.name)),
      datasets: [
        { label: "صباحية", data: rows.map(r => r.morning), backgroundColor: CT.cat[2], borderRadius: 3, borderSkipped: false, maxBarThickness: 12 },
        { label: "ليلية", data: rows.map(r => r.night), backgroundColor: CT.navy, borderRadius: 3, borderSkipped: false, maxBarThickness: 12 },
      ],
    },
    options: {
      ...CHART_BASE,
      indexAxis: "y",
      scales: hbarScales(),
      plugins: {
        legend: { display: true, position: "top", align: "start", labels: { boxWidth: 12, padding: 16 } },
        tooltip: { callbacks: { title: items => fullName(rows[items[0].dataIndex]) } },
      },
    },
  });
}

function drawTaqseeraChart(data) {
  const rows = data.taqseera_count;
  const el = document.getElementById("taqseeraChart");
  if (!rows.length) {
    el.closest(".ls-chart-wrap").innerHTML = emptyState({compact: true, title: "لا توجد تقصيرات في هذا المدى"});
    return;
  }
  new Chart(el, {
    type: "bar",
    data: { labels: uniqueShortNames(rows.map(r => r.name)),
      datasets: [{ data: rows.map(r => r.count), backgroundColor: CT.bad, borderRadius: 4,
        borderSkipped: false, maxBarThickness: 18 }] },
    options: {
      ...CHART_BASE,
      indexAxis: "y",
      scales: hbarScales({ ticks: { font: { size: 12 }, stepSize: 1 } }),
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { title: items => fullName(rows[items[0].dataIndex]), label: ctx => ` ${countLabel(ctx.raw, "تقصيرة")}` } },
      },
    },
  });
}

function drawWeekdayChart(data) {
  // الأسبوع بيبدأ بالسبت (نفس ترتيب WEEKDAYS في النظام) وأول يوم على اليمين
  const order = WEEKDAYS();
  const byName = Object.fromEntries(data.by_weekday.map(w => [w.weekday, w]));
  const values = order.map(w => byName[w]?.services || 0);
  const maxVal = values.length ? Math.max(...values) : 0;
  chartLegend("weekdayChart", [["gold", "اليوم الأعلى تشغيلًا"], ["navy", "باقي الأيام"]]);
  new Chart(document.getElementById("weekdayChart"), {
    type: "bar",
    data: { labels: order, datasets: [{ data: values,
      backgroundColor: values.map(v => v === maxVal && v > 0 ? CT.gold : CT.navy),
      borderRadius: 6, borderSkipped: false, maxBarThickness: 44 }] },
    options: {
      ...CHART_BASE,
      scales: vbarScales(),
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: {
          label: ctx => { const w = byName[order[ctx.dataIndex]]; return [` ${countLabel(ctx.raw, "خدمة")} عبر ${countLabel(w?.days || 0, "يوم")}`, ` صافي: ${w?.net || 0} مرة`]; },
        }},
      },
    },
  });
}

function renderTargetGapTable(rows) {
  const body = rows.length
    ? `<div class="table-scroll gap-table">${mtable(["الهدف", "أيام القائد الرسمي", "أيام غير القائد", "إجمالي أيام التعيين", "الفرق (الإجمالي − القائد)", "نسبة غياب القائد (%)"], rows.map(r => {
      // الفجوة الكبيرة هي اللي محتاجة نظرة: 50% فأكثر أحمر، 25–49% كهرماني
      const rate = r.gap_rate;
      const cls = rate === null ? "" : rate >= 50 ? "err" : rate >= 25 ? "taq" : "done";
      return `<tr>
        <td class="name">${esc(r.name)}</td>
        <td class="n">${r.commander_days}</td>
        <td class="n">${r.other_days}</td>
        <td class="n">${r.total_days}</td>
        <td class="n">${r.gap_days}</td>
        <td class="n">${rate === null ? "<span class='muted'>—</span>" : `<span class="chip ${cls}">${rate}%</span>`}</td>
      </tr>`;
    }))}</div>`
    : emptyState({compact: true, title: "لا توجد بيانات في هذا المدى"});
  document.getElementById("targetGapTable").innerHTML = body;
}

function renderSummary(d) {
  // أرقام محسوبة من نفس البيانات اللي وصلت — من غير طلبات زيادة
  const totals = d.by_officer_load.map(r => r.total);
  const avg = totals.length ? Math.round(totals.reduce((a, b) => a + b, 0) / totals.length * 10) / 10 : 0;
  const max = totals.length ? Math.max(...totals) : 0;
  const min = totals.length ? Math.min(...totals) : 0;
  const taq = (d.taqseera_count || []).reduce((n, r) => n + r.count, 0);
  document.getElementById("summaryStats").innerHTML = `
    <div class="stat"><span>عدد الأيام</span><strong>${d.days_count}</strong>
      <div class="stat-sub">${fmt(d.date_from)} — ${fmt(d.date_to)}</div></div>
    <div class="stat"><span>ضباط شُغّلوا</span><strong>${d.by_officer_load.length}</strong></div>
    <div class="stat"><span>متوسط التشغيل</span><strong>${avg}</strong><div class="stat-sub">مرة لكل ضابط</div></div>
    <div class="stat"><span>الأعلى / الأقل</span><strong>${max} / ${min}</strong><div class="stat-sub">مرات تشغيل</div></div>
    <div class="stat${taq ? " stat-accent-orange" : ""}"><span>تقصيرات</span><strong>${taq}</strong></div>`;
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
