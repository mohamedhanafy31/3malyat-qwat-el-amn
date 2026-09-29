/* سجل خدمات الضابط — List زمني (صف لكل يوم) لضابط واحد في مدى تاريخ
   مختار. عكس «دفتر الضابط» اللي بيعرض شبكة رموز مختصرة لكل الأيام —
   الصفحة دي List مقروء لمدى محدد بس. */
let OLOG_OFFICERS = [], OLOG_DATA = null, OLOG_SORT_DESC = false;

function serviceChips(services) {
  return services.length
    ? services.map(s => `<span class="chip ${KIND_CLS[s.kind] || "w"}">${esc(s.name)}<i>${esc(s.shift)}</i></span>`).join(" ")
    : "<span class='muted'>—</span>";
}

function statusCell(row) {
  if (row.leave) return `<span class="chip rest">${esc(row.leave.type)}</span>`;
  if (row.group === "صافي") return `<span class="chip on">صافي</span>`;
  return `<span class="chip ${KIND_CLS[row.group] || "done"}">${esc(row.group)}${row.bucket ? " · " + esc(row.bucket) : ""}</span>`;
}

function logRow(row) {
  return `<tr>
    <td>${fmt(row.date)}</td>
    <td>${esc(row.weekday)}</td>
    <td>${serviceChips(row.services)}${row.taqseera ? ' <span class="chip taq">تقصيرة</span>' : ""}</td>
    <td>${statusCell(row)}</td>
    <td class="wrap">${esc(row.note) || "<span class='muted'>—</span>"}</td>
  </tr>`;
}

function render(d) {
  OLOG_DATA = d;
  if (!d) {
    $("#ologWrap").innerHTML = emptyState({icon: "users", title: "اختر ضابطًا لعرض سجل خدماته", hint: "اختر الضابط ومدى التاريخ من الأعلى."});
    return;
  }
  const rows = OLOG_SORT_DESC ? [...d.rows].reverse() : d.rows;
  $("#ologWrap").innerHTML = tableBlock(
    ["التاريخ", "اليوم", "الخدمات", "الحالة", "ملاحظة"],
    rows.map(logRow),
    `${d.rows.length} يوم مسجّل من ${fmt(d.date_from)} إلى ${fmt(d.date_to)} — ${esc(d.officer.role)}/ ${esc(d.officer.name)}`,
    {title: "لا توجد أيام مسجّلة لهذا الضابط في المدى المحدد", hint: "ربما لم يكن على القوة في هذه الفترة."});
}

function syncSortLabel() {
  $("#ologSortToggle").textContent = OLOG_SORT_DESC ? "الأحدث أولًا ↑" : "الأقدم أولًا ↓";
}
$("#ologSortToggle").onclick = () => {
  OLOG_SORT_DESC = !OLOG_SORT_DESC;
  syncSortLabel();
  render(OLOG_DATA);
};
syncSortLabel();

async function loadLog() {
  const id = $("#ologOfficer").value;
  if (!id) { render(null); return }
  const from = $("#ologFrom").value, to = $("#ologTo").value;
  const params = new URLSearchParams();
  if (from) params.set("date_from", from);
  if (to) params.set("date_to", to);
  const qs = params.toString();
  const d = await api(`/api/officer-log/${encodeURIComponent(id)}${qs ? `?${qs}` : ""}`);
  if (!d) return;
  $("#ologFrom").value = d.date_from;
  $("#ologTo").value = d.date_to;
  render(d);
}

$("#ologOfficer").onchange = loadLog;
$("#ologFrom").onchange = loadLog;
$("#ologTo").onchange = loadLog;

$("#ologPreset7").onclick = () => {
  $("#ologFrom").value = addDays(curDate(), -6);
  $("#ologTo").value = curDate();
  loadLog();
};
$("#ologPreset30").onclick = () => {
  $("#ologFrom").value = addDays(curDate(), -29);
  $("#ologTo").value = curDate();
  loadLog();
};
$("#ologPresetMonth").onclick = () => {
  const today = curDate();
  $("#ologFrom").value = today.slice(0, 8) + "01";
  $("#ologTo").value = today;
  loadLog();
};

async function load() {
  const d = await bootstrap();
  if (!d) return;
  OLOG_OFFICERS = d.officer_index || [];
  fillSelect($("#ologOfficer"), [["", "— اختَر ضابط —"],
    ...OLOG_OFFICERS.map(o => [o.id, `${o.role}/ ${o.name}`])]);

  // جاية من رابط "سجل الخدمات" في دفتر الضابط — تفتح على طول على نفس الضابط
  const preselect = new URLSearchParams(location.search).get("officer");
  if (preselect && OLOG_OFFICERS.some(o => o.id === preselect)) {
    $("#ologOfficer").value = preselect;
    loadLog();
  } else {
    render(null);
  }
}
load();
