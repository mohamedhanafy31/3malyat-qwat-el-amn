/* مشترك بين دفتر 43 وصفحة الضابط — الرموز والمفتاح ونافذة الخانة. */

/* لون الخانة بيتبع عائلة الحالة: شغل / راحة / خارج القوة */
const FAMILY_CLS = {"عمل": "fam-work", "راحة": "fam-rest", "خارج": "fam-away",
                    "خارج القوة": "fam-none", "بدون سجل": "fam-blank"};

const cellClass = c => `cell43 ${FAMILY_CLS[c.family] || ""}`;

function legendBox(legend) {
  const items = (legend || []).map(l =>
    `<span class="lg-item"><b class="cell43 ${FAMILY_CLS[l.family] || ""}">${esc(l.code)}</b>
      ${esc(l.label)}</span>`).join("");
  return `<div class="legend-box"><span class="lg-title">مفتاح الرموز</span>${items}</div>`;
}

/* الضغط على أي خانة بيوري الخدمة اللي وراها — الدفتر بيتستخدم كإثبات،
   فلازم كل رمز تقدر ترجّعه لمصدره. */
function openCell(cell, who) {
  $("#cellTitle").textContent = `${dayName(cell.day)} ${fmt(cell.day)}`;
  $("#cellWho").textContent = who || "";
  const rows = [];
  rows.push(`<div class="cell-state"><b class="cell43 ${FAMILY_CLS[cell.family] || ""}">${esc(cell.code)}</b>
    <span>${esc(cell.label)}</span></div>`);
  if (cell.services?.length) {
    rows.push(mtable(["الخدمة", "الفترة", "التصنيف"], cell.services.map(s =>
      `<tr><td class="name">${esc(s.name)}</td>
       <td>${esc(s.shift) || "<span class='muted'>—</span>"}</td>
       <td><span class="chip ${KIND_CLS[s.kind] || "w"}">${esc(s.kind)}</span></td></tr>`)));
  } else {
    rows.push(`<div class="mempty">مفيش خدمة مسجّلة في اليوم ده</div>`);
  }
  if (cell.taqseera) rows.push(`<p class="hint"><span class="chip taq">تقصيرة</span></p>`);
  if (cell.leave) {
    rows.push(`<p class="hint">راحة ${esc(cell.leave.type)} —
      من ${fmt(cell.leave.start)} إلى ${fmt(cell.leave.end)}،
      العودة ${fmt(cell.leave.return_date)}</p>`);
  }
  if (cell.note) rows.push(`<p class="hint">نص التشغيل: ${esc(cell.note)}</p>`);
  $("#cellBody").innerHTML = rows.join("");
  openModal("cellModal");
}

/* حصر الأيام بالرمز + الخدمات بالاسم */
function tallyBox(tally, legend) {
  const order = (legend || []).filter(l => tally.by_code[l.code]);
  const codes = order.map(l =>
    `<tr><td><b class="cell43 ${FAMILY_CLS[l.family] || ""}">${esc(l.code)}</b></td>
     <td class="name">${esc(l.label)}</td><td><b>${tally.by_code[l.code]}</b></td></tr>`);
  const fams = Object.entries(tally.by_family)
    .map(([k, v]) => `<span class="chip ${k === "عمل" ? "on" : k === "راحة" ? "w" : "taq"}">${esc(k)} ${v}</span>`)
    .join(" ");
  const svcs = (tally.services || []).map(s =>
    `<tr><td class="name">${esc(s.name)}</td><td><b>${s.count}</b></td></tr>`);
  return `<div class="tally-grid">
    <div class="mcard"><h3>الأيام حسب الحالة<span class="mcount">${tally.days}</span></h3>
      <div class="fam-row">${fams}</div>
      ${codes.length ? mtable(["", "الحالة", "أيام"], codes) : '<div class="mempty">لا يوجد</div>'}</div>
    <div class="mcard"><h3>الخدمات<span class="mcount">${(tally.services || []).length}</span></h3>
      ${svcs.length ? mtable(["الخدمة", "مرات"], svcs) : '<div class="mempty">لا يوجد</div>'}</div>
  </div>`;
}
