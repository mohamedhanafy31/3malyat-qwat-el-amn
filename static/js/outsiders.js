let OUTSIDERS = [];

function renderOutsiders() {
  const type = $("#outsiderType").value;
  const query = $("#outsiderSearch").value.trim().toLocaleLowerCase();
  const rows = OUTSIDERS.filter(row => (!type || row.status === type)
    && (!query || [row.name, row.status, row.title, row.details, row.note, row.role]
      .some(value => String(value || "").toLocaleLowerCase().includes(query))));
  const leaveCount = OUTSIDERS.filter(row => row.record_kind === "leave").length;
  const absenceCount = OUTSIDERS.filter(row => row.status === "غياب").length;
  const sickCount = OUTSIDERS.filter(row => row.status === "مرضي").length;
  $("#outsiderSummary").innerHTML = `
    <div class="stat"><span>كل السجلات</span><strong>${OUTSIDERS.length}</strong></div>
    <div class="stat"><span>غياب</span><strong>${absenceCount}</strong></div>
    <div class="stat"><span>مرضي</span><strong>${sickCount}</strong></div>
    <div class="stat"><span>راحات وإجازات</span><strong>${leaveCount}</strong></div>`;
  if (!rows.length) {
    $("#outsiderRegister").innerHTML = `<div class="empty">لا توجد سجلات مطابقة.</div>`;
    return;
  }
  $("#outsiderRegister").innerHTML = `<table class="table" data-mobile-cards>
    <thead><tr><th>الاسم</th><th>الرتبة</th><th>الحالة</th><th>المدة</th><th>من</th><th>حتى</th><th>التفاصيل</th></tr></thead>
    <tbody>${rows.map(row => `<tr>
      <td data-label="الاسم">${esc(row.name || "—")}</td>
      <td data-label="الرتبة">${esc(row.role || row.category || "—")}</td>
      <td data-label="الحالة">${esc(row.status || "—")}</td>
      <td data-label="المدة">${esc(row.duration?.text || "—")}</td>
      <td data-label="من">${esc(row.start || "—")}${row.start_time ? ` ${esc(row.start_time)}` : ""}</td>
      <td data-label="حتى">${esc((row.end_time && row.stopped_on) || row.end || (row.open_ended ? "مستمرة" : "—"))}${row.end_time ? ` ${esc(row.end_time)}` : ""}</td>
      <td data-label="التفاصيل">${esc([row.title, row.details, row.note].filter(Boolean).join(" — ") || "—")}</td>
    </tr>`).join("")}</tbody></table>`;
}

async function loadOutsiders() {
  const result = await api("/api/bootstrap/outsiders");
  if (!result) return;
  OUTSIDERS = result.outsiders || [];
  const select = $("#outsiderType");
  const selected = select.value;
  const types = [...new Set(OUTSIDERS.map(row => row.status).filter(Boolean))].sort();
  select.innerHTML = `<option value="">الكل</option>${types.map(value => `<option value="${esc(value)}">${esc(value)}</option>`).join("")}`;
  select.value = types.includes(selected) ? selected : "";
  renderOutsiders();
}

$("#outsiderSearch").addEventListener("input", renderOutsiders);
$("#outsiderType").addEventListener("change", renderOutsiders);
$("#outsiderRefresh").addEventListener("click", loadOutsiders);
loadOutsiders();
