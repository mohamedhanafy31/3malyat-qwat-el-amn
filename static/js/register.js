/* دفتر 43 — صف لكل ضابط، عمود لكل يوم في الشهر، والخانة رمز حالته.
   الضغط على أي خانة بيوري الخدمة اللي وراها. */
let REG = null;

const dayNum = iso => Number(iso.slice(8, 10));
const monthValue = () => $("#regMonth").value || curDate().slice(0, 7);

function headRow() {
  const recorded = new Set(REG.recorded_days || []);
  const cols = REG.days.map(d =>
    `<th class="d-col ${recorded.has(d) ? "" : "no-rec"}"
      title="${dayName(d)} ${fmt(d)}${recorded.has(d) ? "" : " — مفيش يومية"}">${dayNum(d)}</th>`).join("");
  return `<tr><th class="who-col">الضابط</th>${cols}<th class="t-col">عمل</th>
    <th class="t-col">راحة</th><th class="t-col">خارج</th></tr>`;
}

function officerRow(r) {
  const cells = r.cells.map(c =>
    `<td><button class="${cellClass(c)}" data-action="openCell"
      data-id="${esc(r.id)}" data-extra="${dataAttr({day: c.day})}"
      title="${esc(c.label)}">${esc(c.code)}</button></td>`).join("");
  const t = r.tally.by_family;
  return `<tr>
    <td class="who-col"><a href="/register/${encodeURIComponent(r.id)}" class="who-link">
      ${esc(r.name)}</a><div class="sub">${esc(r.role)}</div></td>
    ${cells}
    <td class="t-col"><b>${t["عمل"]}</b></td>
    <td class="t-col">${t["راحة"]}</td>
    <td class="t-col">${t["خارج"]}</td></tr>`;
}

function totalsRows() {
  const line = (label, key, cls) =>
    `<tr class="tot-row ${cls || ""}"><td class="who-col">${label}</td>` +
    REG.totals.map(t => `<td class="d-col">${t.recorded ? t[key] : "·"}</td>`).join("") +
    `<td colspan="3"></td></tr>`;
  return line("القوة", "force", "tot-force") + line("الموجود", "working") +
         line("راحة", "resting") + line("خارج", "away");
}

function render() {
  const wrap = $("#registerWrap");
  if (!REG) { wrap.innerHTML = `<div class="empty">جارٍ التحميل...</div>`; return }
  const q = $("#regSearch").value.trim();
  const rows = q ? REG.rows.filter(r => r.name.includes(q)) : REG.rows;
  $("#regCount").textContent = `${rows.length} ضابط · ${REG.days.length} يوم`;
  wrap.innerHTML = `<div class="table-scroll reg-scroll">
    <table class="table reg43">
      <thead>${headRow()}</thead>
      <tbody>${rows.map(officerRow).join("")}</tbody>
      <tfoot>${totalsRows()}</tfoot>
    </table></div>`;
  $("#registerLegend").innerHTML = legendBox(REG.legend);
}

ACTIONS.openCell = (id, extra) => {
  const row = REG.rows.find(r => r.id === id);
  const cell = row?.cells.find(c => c.day === extra.day);
  if (cell) openCell(cell, `${row.role} / ${row.name}`);
};

async function loadMonth(value) {
  const [y, m] = value.split("-");
  const d = await api(`/api/register/${Number(y)}/${Number(m)}`);
  if (!d) return;
  REG = d; $("#regMonth").value = value; render();
}
const shiftMonth = n => {
  const [y, m] = monthValue().split("-").map(Number);
  const d = new Date(y, m - 1 + n, 1);
  loadMonth(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`);
};
$("#monthPrev").onclick = () => shiftMonth(-1);
$("#monthNext").onclick = () => shiftMonth(1);
$("#regMonth").onchange = () => loadMonth($("#regMonth").value);
$("#regSearch").oninput = render;

async function load() {
  const d = await bootstrap();
  if (!d) return;
  const days = d.days || [];
  loadMonth((days[days.length - 1] || curDate()).slice(0, 7));
}
load();
