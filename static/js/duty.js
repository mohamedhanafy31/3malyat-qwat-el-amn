/* يومية تشغيل الضباط — جدول الإجمالي وحالة الضابط.
   التكليف بخدمة بقى في اليومية التفصيلية (نفس السجل)، والصفحة دي بتعدّل
   حالة الضابط بس: تقصيرة / انتداب / غياب / مرضي / فرقة / طارئة / ملاحظة. */
let DUTY = null;

function renderSummary(s) {
  const cell = v => `<td>${v}</td>`;
  const x = s["خارجية"], dl = s["داخلية"], tb = s["طبية"], kh = s["خوارج"];
  $("#balanceTag").innerHTML = s.balanced
    ? `<span class="chip on">متوازن ${s.counted}/${s["أصل القوة"]}</span>`
    : `<span class="chip rest">غير متوازن ${s.counted}/${s["أصل القوة"]}</span>`;
  $("#dutySummary").innerHTML = `<div class="table-scroll"><table class="table sum">
   <thead>
    <tr><th rowspan="2">أصل القوة</th><th colspan="3">الخدمات الخارجية</th><th colspan="2">الخدمات الداخلية</th>
        <th colspan="2">الخدمات الطبية</th><th colspan="7">الخوارج</th>
        <th rowspan="2">الحراسات المشددة</th><th rowspan="2">الصافي (${s["صافي"]})</th></tr>
    <tr><th>صباحية</th><th>ليلية</th><th>بحث</th><th>صباحية</th><th>ليلية</th>
        <th>موجود</th><th>راحة</th>
        <th>تقصيرة</th><th>راحة</th><th>طارئة</th><th>غياب</th><th>مرضي</th><th>فرقة</th><th>انتداب</th></tr>
   </thead>
   <tbody><tr class="sumrow">
     <td><b>${s["أصل القوة"]}</b></td>
     ${cell(x["صباحية"])}${cell(x["ليلية"])}${cell(x["بحث"])}
     ${cell(dl["صباحية"])}${cell(dl["ليلية"])}
     ${cell(tb["موجود"])}${cell(tb["راحة"])}
     ${cell(kh["تقصيرة"])}${cell(kh["راحة"])}${cell(kh["طارئة"])}${cell(kh["غياب"])}${cell(kh["مرضي"])}${cell(kh["فرقة"])}${cell(kh["انتداب"])}
     ${cell(s["حراسات"])}
     <td class="wrap">${s.net_names.map(esc).join("<br>") || "—"}</td>
   </tr></tbody></table></div>`;
}

/* أقسام جدول الوورد الثلاثة — القسم تابع لوضع الضابط التنظيمي مش لتشغيله */
function sectionRows(rows) {
  const order = META.officer_sections || ["القوة", "الحراسات المشددة", "الخوارج"];
  const out = [];
  for (const section of order) {
    const mine = rows.filter(r => (r.section || order[0]) === section);
    if (!mine.length) continue;
    if (section !== order[0]) {
      out.push(`<tr class="section-row"><td colspan="6">${esc(section)}</td></tr>`);
    }
    out.push(...mine.map(officerRow));
  }
  // أي قسم مش في القايمة يتعرض في الآخر بدل ما يختفي
  out.push(...rows.filter(r => !order.includes(r.section || order[0])).map(officerRow));
  return out;
}

function officerRow(r) {
  const svc = r.services.length
    ? r.services.map(s => `<span class="chip ${KIND_CLS[s.kind] || "w"}">${esc(s.name)}<i>${esc(s.shift)}</i></span>`).join(" ")
    : `<span class="muted">—</span>`;
  const grp = r.leave ? `<span class="chip rest">${esc(r.leave.type)}</span><div class="sub">حتى ${fmt(r.leave.end)}</div>`
    : r.group === "صافي" ? `<span class="chip on">صافي</span>`
    : `<span class="chip ${KIND_CLS[r.group] || "done"}">${esc(r.group)}${r.bucket ? " · " + esc(r.bucket) : ""}</span>`;
  const gone = r.later_left ? `<span class="chip done" title="خرج من القوة يوم ${fmt(r.later_left)}">خرج ${fmt(r.later_left)}</span>` : "";
  const search = r.search_attached ? ` <span class="chip soon" title="تشغيل من إدارة البحث">بحث</span>` : "";
  return `<tr class="${r.later_left ? "was" : ""}">
    <td class="name">${esc(r.name)}<div class="sub">${esc(r.role)}${search} ${gone}</div></td>
    <td class="wrap">${esc(r.post) || "<span class='muted'>—</span>"}</td>
    <td>${svc}${r.taqseera ? ' <span class="chip taq">تقصيرة</span>' : ""}</td>
    <td>${grp}</td>
    <td class="wrap">${esc(r.note) || "<span class='muted'>—</span>"}</td>
    <td><button class="mini" data-action="openAssign" data-id="${esc(r.id)}">الحالة</button></td>
  </tr>`;
}

function render() {
  if (!DUTY) { $("#dutyBoard").innerHTML = `<div class="empty">جارٍ التحميل...</div>`; return }
  renderSummary(DUTY.summary);
  const gone = DUTY.rows.filter(r => r.later_left).length;
  $("#dutyBoard").innerHTML = tableBlock(
    ["الضابط", "العمل المسند إليه", "الخدمات", "الخانة في الإجمالي", "نص التشغيل", "الإجراء"],
    sectionRows(DUTY.rows),
    `قوة اليوم: ${DUTY.rows.length} ضابط${gone ? ` — منهم ${gone} خرجوا من القوة بعد كده` : ""}`);
}

ACTIONS.openAssign = id => {
  const row = DUTY.rows.find(r => r.id === id); if (!row) return;
  $("#assignPerson").value = id;
  $("#assignTitle").textContent = `حالة: ${row.name}`;
  $("#assignHint").textContent =
    `يوم ${dayName(DUTY.date)} ${fmt(DUTY.date)} — التكليف بالخدمات من اليومية التفصيلية.`
    + (row.leave ? ` تنبيه: الضابط في ${row.leave.type} لحد ${fmt(row.leave.end)}.` : "");
  fillSelect($("#assignStatus"),
    [["", "— بدون —"], ...(META.officer_statuses || []).map(x => [x, x])]);
  $("#assignStatus").value = row.group === "خوارج" && !row.leave ? (row.bucket || "") : "";
  $("#assignTaq").checked = !!row.taqseera;
  $("#assignNote").value = row.note || "";
  openModal("assignModal");
};

$("#assignForm").onsubmit = async e => {
  e.preventDefault();
  const out = await api(`/api/duty/${DUTY.date}/${encodeURIComponent($("#assignPerson").value)}`,
    jsonReq("PUT", {taqseera: $("#assignTaq").checked,
      status: $("#assignStatus").value, note: $("#assignNote").value}));
  if (!out) return;
  DUTY = out; closeModal("assignModal"); showToast("تم حفظ الحالة"); render();
};

async function loadDay(day) {
  const d = await api(`/api/duty/${day}`); if (!d) return;
  DUTY = d; render();
}
const shiftDay = n => { const d = addDays($("#dutyDate").value || curDate(), n); $("#dutyDate").value = d; loadDay(d) };
$("#dayPrev").onclick = () => shiftDay(-1);
$("#dayNext").onclick = () => shiftDay(1);
$("#dayToday").onclick = () => { $("#dutyDate").value = curDate(); loadDay(curDate()) };
$("#dutyDate").onchange = () => loadDay($("#dutyDate").value);

async function load() {
  const d = await bootstrap();
  if (!d) return;
  const days = d.days || [];
  $("#dutyDate").value = days.includes(curDate()) ? curDate() : (days[days.length - 1] || curDate());
  loadDay($("#dutyDate").value);
}
load();
