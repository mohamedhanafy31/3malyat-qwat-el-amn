/* يومية التشغيل — جدول الإجمالي وتكليف الضباط */
let DUTY = null, SERVICES = [];

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

function renderBoard(rows) {
  const body = rows.map(r => {
    const svc = r.services.length
      ? r.services.map(s => `<span class="chip ${KIND_CLS[s.kind] || "w"}">${esc(s.name)}<i>${esc(s.shift)}</i></span>`).join(" ")
      : `<span class="muted">—</span>`;
    const grp = r.leave ? `<span class="chip rest">${esc(r.leave.type)}</span><div class="sub">حتى ${fmt(r.leave.end)}</div>`
      : r.group === "صافي" ? `<span class="chip on">صافي</span>`
      : `<span class="chip ${KIND_CLS[r.group] || "done"}">${esc(r.group)}${r.bucket ? " · " + esc(r.bucket) : ""}</span>`;
    const gone = r.later_left ? `<span class="chip done" title="خرج من القوة يوم ${fmt(r.later_left)}">خرج ${fmt(r.later_left)}</span>` : "";
    return `<tr class="${r.later_left ? "was" : ""}">
      <td class="name">${esc(r.name)}<div class="sub">${esc(r.role)} ${gone}</div></td>
      <td>${svc}${r.taqseera ? ' <span class="chip taq">تقصيرة</span>' : ""}</td>
      <td>${grp}</td>
      <td class="wrap">${esc(r.note) || "<span class='muted'>—</span>"}</td>
      <td><button class="mini" ${r.leave ? "disabled title='الضابط في راحة'" : ""} data-action="openAssign" data-id="${esc(r.id)}">تكليف</button></td>
    </tr>`;
  });
  const gone = rows.filter(r => r.later_left).length;
  $("#dutyBoard").innerHTML = tableBlock(
    ["الضابط", "الخدمات", "الخانة في الإجمالي", "نص التشغيل", "الإجراء"], body,
    `قوة اليوم: ${rows.length} ضابط${gone ? ` — منهم ${gone} خرجوا من القوة بعد كده` : ""}`);
}

function render() {
  if (!DUTY) { $("#dutyBoard").innerHTML = `<div class="empty">جارٍ التحميل...</div>`; return }
  renderSummary(DUTY.summary); renderBoard(DUTY.rows);
}

ACTIONS.openAssign = id => {
  const row = DUTY.rows.find(r => r.id === id); if (!row) return;
  $("#assignPerson").value = id;
  $("#assignTitle").textContent = `تكليف: ${row.name}`;
  $("#assignHint").textContent = `يوم ${dayName(DUTY.date)} ${fmt(DUTY.date)} — الضابط بدون خدمة بيتحسب في الصافي.`;
  const chosen = new Map(row.services.map(s => [s.id, s.shift]));
  $("#assignServices").innerHTML = SERVICES.map(s => `
    <label class="svc-item ${chosen.has(s.id) ? "on" : ""}">
      <input type="checkbox" value="${esc(s.id)}" ${chosen.has(s.id) ? "checked" : ""}>
      <span class="chip ${KIND_CLS[s.kind] || "w"}">${esc(s.kind)}</span>
      <span class="svc-name">${esc(s.name)}</span>
      <select class="svc-shift">${SHIFTS().map(x => `<option ${chosen.get(s.id) === x ? "selected" : ""}>${x}</option>`).join("")}</select>
    </label>`).join("");
  $$("#assignServices input").forEach(cb =>
    cb.onchange = () => cb.closest(".svc-item").classList.toggle("on", cb.checked));
  $("#assignTaq").checked = !!row.taqseera;
  $("#assignStatus").value = row.group === "خوارج" && ["انتداب", "غياب"].includes(row.bucket) ? row.bucket : "";
  $("#assignNote").value = row.note || "";
  openModal("assignModal");
};

$("#assignForm").onsubmit = async e => {
  e.preventDefault();
  const items = $$("#assignServices .svc-item").filter(l => l.querySelector("input").checked)
    .map(l => ({service_id: l.querySelector("input").value, shift: l.querySelector(".svc-shift").value}));
  const out = await api(`/api/duty/${DUTY.date}/${encodeURIComponent($("#assignPerson").value)}`,
    jsonReq("PUT", {items, taqseera: $("#assignTaq").checked,
      status: $("#assignStatus").value, note: $("#assignNote").value}));
  if (!out) return;
  DUTY = out; closeModal("assignModal"); showToast("تم حفظ التكليف"); render();
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
  SERVICES = d.services || [];
  const days = d.duty_days || [];
  $("#dutyDate").value = days.includes(curDate()) ? curDate() : (days[days.length - 1] || curDate());
  loadDay($("#dutyDate").value);
}
load();
