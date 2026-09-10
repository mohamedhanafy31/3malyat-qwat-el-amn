/* صفحة الضابط — دفتره هو: كل شهر في صف، والحصر الكامل تحت. */
let OFF = null;

const MONTH_NAMES = ["يناير","فبراير","مارس","أبريل","مايو","يونيو",
                     "يوليو","أغسطس","سبتمبر","أكتوبر","نوفمبر","ديسمبر"];
const monthLabel = m => {
  const [y, mm] = m.split("-");
  return `${MONTH_NAMES[Number(mm) - 1]} ${y}`;
};

function monthStrip(block) {
  // كل خانة في مكان يومها من الشهر، فالفراغات تبان زي الدفتر الورق
  const byDay = new Map(block.cells.map(c => [Number(c.day.slice(8, 10)), c]));
  const last = Math.max(...byDay.keys());
  const cells = [];
  for (let d = 1; d <= last; d++) {
    const c = byDay.get(d);
    cells.push(c
      ? `<td><button class="${cellClass(c)}" data-action="openCell"
          data-extra="${dataAttr({day: c.day})}" title="${esc(c.label)}">${esc(c.code)}</button></td>`
      : `<td><span class="cell43 fam-none">·</span></td>`);
  }
  const heads = [];
  for (let d = 1; d <= last; d++) heads.push(`<th class="d-col">${d}</th>`);
  const t = block.tally.by_family;
  return `<div class="mcard">
    <h3>${monthLabel(block.month)}
      <span class="mcount">${block.tally.days} يوم</span>
      <span class="fam-row">
        <span class="chip on">عمل ${t["عمل"]}</span>
        <span class="chip w">راحة ${t["راحة"]}</span>
        <span class="chip w">إجازة ${t["إجازة"]}</span>
        <span class="chip taq">خارج ${t["خارج"]}</span></span></h3>
    <div class="table-scroll"><table class="table reg43">
      <thead><tr>${heads.join("")}</tr></thead>
      <tbody><tr>${cells.join("")}</tr></tbody></table></div></div>`;
}

function render() {
  if (!OFF) { $("#officerWrap").innerHTML = `<div class="empty">جارٍ التحميل...</div>`; return }
  const o = OFF.officer;
  $("#offHead").textContent =
    `${o.role} / ${o.name}${o.post ? " — " + o.post : ""}${o.section ? " · " + o.section : ""}`;
  $("#officerWrap").innerHTML =
    tallyBox(OFF.tally, OFF.legend) +
    `<div class="match-grid">${OFF.months.map(monthStrip).join("")}</div>`;
  $("#registerLegend").innerHTML = legendBox(OFF.legend);
}

ACTIONS.openCell = (id, extra) => {
  const cell = OFF.cells.find(c => c.day === extra.day);
  if (cell) openCell(cell, `${OFF.officer.role} / ${OFF.officer.name}`);
};

async function load() {
  await bootstrap();
  const d = await api(`/api/register/officer/${encodeURIComponent(OFFICER_ID)}`);
  if (!d) return;
  OFF = d; render();
}
load();
