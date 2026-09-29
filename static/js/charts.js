/* ثيم الرسوم البيانية المشترك (إحصائيات التشغيل والراحات).
   الألوان جاية من رموز style.css نفسها — مش باليتة منفصلة — والاتجاه RTL:
   محور الفئات (أسماء الضباط/الأيام) على اليمين، والأعمدة الأفقية بتطلع من
   اليمين لليسار، والزمن بيمشي من اليمين لليسار زي القراءة. */
const CT = (() => {
  const css = getComputedStyle(document.documentElement);
  const v = n => css.getPropertyValue(n).trim();
  return {
    navy: v("--navy-800"), navyMid: v("--navy-500"), navySoft: v("--navy-200"),
    gold: v("--gold-700"), bad: v("--bad-700"), warn: v("--warn-500"),
    grid: v("--line"), ink: v("--ink-500"), inkStrong: v("--ink-700"), surface: v("--surface"),
    // فئات بدون دلالة حالة (أنواع الراحة، الفترات)
    cat: [v("--navy-800"), v("--cat-2"), v("--cat-4"), v("--cat-1"), v("--navy-500"), v("--cat-3"), v("--ink-400")],
    font: v("--font-body"),
  };
})();

Chart.defaults.font.family = CT.font;
Chart.defaults.font.size = 13;
Chart.defaults.color = CT.ink;
Chart.defaults.animation.duration = 500;
Chart.defaults.plugins.legend.rtl = true;
Chart.defaults.plugins.legend.textDirection = "rtl";
Chart.defaults.plugins.legend.labels.font = { size: 13 };
Chart.defaults.plugins.tooltip.rtl = true;
Chart.defaults.plugins.tooltip.textDirection = "rtl";

const CHART_BASE = { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } };

/* أعمدة أفقية: الأسماء يمين، القيم بتكبر ناحية الشمال */
function hbarScales(x = {}) {
  return {
    x: { reverse: true, beginAtZero: true, grid: { color: CT.grid }, ticks: { font: { size: 12 } }, ...x },
    y: { position: "right", grid: { display: false }, ticks: { font: { size: 12 }, color: CT.inkStrong } },
  };
}
/* أعمدة رأسية وخطوط زمنية: أول فئة على اليمين */
function vbarScales(y = {}) {
  return {
    x: { reverse: true, grid: { display: false }, ticks: { font: { size: 12 }, color: CT.inkStrong } },
    y: { position: "right", beginAtZero: true, grid: { color: CT.grid }, ticks: { font: { size: 12 } }, ...y },
  };
}

/* اسم مختصر للمحور مايتكررش لضابطين: الأول + الأخير، ولو اتكرر يتضاف
   الاسم التاني، ولو فضل مكرر يتعرض كامل. الاسم الكامل بالرتبة في التلميح. */
function uniqueShortNames(names) {
  const words = names.map(n => String(n || "").trim().split(/\s+/));
  const short = w => (w.length <= 2 ? w.join(" ") : `${w[0]} ${w[w.length - 1]}`);
  const longer = w => (w.length <= 3 ? w.join(" ") : `${w[0]} ${w[1]} ${w[w.length - 1]}`);
  let out = words.map(short);
  const dup = arr => s => arr.filter(x => x === s).length > 1;
  let isDup = dup(out);
  out = out.map((s, i) => (isDup(s) ? longer(words[i]) : s));
  isDup = dup(out);
  return out.map((s, i) => (isDup(s) ? words[i].join(" ") : s));
}
const fullName = r => `${r.role ? `${r.role} / ` : ""}${r.name || ""}`;

/* مفتاح ألوان بسيط فوق الرسم لما اللون بيحمل معنى — كل بند [اسم لون من
   الرموز (navy/gold/soft/bad/cat2/cat4…)، النص] */
function chartLegend(canvasId, items) {
  const wrap = document.getElementById(canvasId)?.closest(".ls-chart-wrap");
  if (!wrap) return;
  wrap.parentElement.querySelector(".chart-key")?.remove();
  wrap.insertAdjacentHTML("beforebegin", `<div class="chart-key">${items.map(([k, l]) =>
    `<span><i class="k-${k}" aria-hidden="true"></i>${esc(l)}</span>`).join("")}</div>`);
}
