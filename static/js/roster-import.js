/* استيراد كشوف Word على مرحلتين: معاينة ثم استبدال ذري لنفس الملف. */
let ROSTER_IMPORT = null;

function rosterStat(label, value) {
  return `<div class="stat"><span>${esc(label)}</span><strong>${Number(value) || 0}</strong></div>`;
}

function rosterPreviewRows(kind, rows) {
  const shown = (rows || []).slice(0, 25);
  if (kind === "conscripts") {
    return mtable(["م", "اسم المجند", "الصفة"], shown.map(row =>
      `<tr><td>${row.row}</td><td class="name">${esc(row.name)}</td><td>سائق</td></tr>`));
  }
  return mtable(["م", "الدرجة", "الاسم", "العمل", "رقم الشرطة"], shown.map(row =>
    `<tr><td>${row.row}</td><td>${esc(row.role)}</td><td class="name">${esc(row.name)}</td><td>${esc(row.post || "—")}</td><td dir="ltr">${esc(row.code || "غير مسجل")}</td></tr>`));
}

function renderRosterPreview(result) {
  const noun = result.kind === "conscripts" ? "المجندين" : "الأفراد على القوة";
  $("#rosterImportTitle").textContent = `معاينة استبدال كشف ${noun}`;
  $("#rosterImportFile").textContent = result.filename;
  $("#rosterImportDate").value = result.effective_date;
  $("#rosterImportStats").innerHTML = rosterStat("في الملف", result.total)
    + rosterStat("مطابق حاليًا", result.matched) + rosterStat("جديد", result.added)
    + rosterStat(result.kind === "personnel" ? "سيُنقل للأرشيف" : "سيُستبدل", result.removed);
  const warnings = result.warnings || [];
  $("#rosterImportWarnings").classList.toggle("hidden", !warnings.length);
  $("#rosterImportWarnings").innerHTML = warnings.map(item => `<div>${esc(item)}</div>`).join("");
  $("#rosterImportPreview").innerHTML = rosterPreviewRows(result.kind, result.rows)
    + (result.rows.length > 25 ? `<p class="form-note">المعروض أول 25 سجلًا من ${result.rows.length}.</p>` : "");
  openModal("rosterImportModal");
}

async function previewRosterImport(config, file) {
  const form = new FormData();
  form.append("file", file);
  const result = await api(`/api/roster-import/${config.kind}/preview`, {
    method: "POST", body: form, loadingLabel: "جاري قراءة كشف Word…", timeoutMs: 60000,
  });
  if (!result) return;
  ROSTER_IMPORT = {config, file, result};
  renderRosterPreview(result);
}

function setupRosterImport(config) {
  const button = $("#" + config.buttonId), input = $("#" + config.inputId);
  if (!button || !input) return;
  button.onclick = () => { input.value = ""; input.click(); };
  input.onchange = () => input.files?.[0] && previewRosterImport(config, input.files[0]);
}

$("#rosterImportApply")?.addEventListener("click", async () => {
  if (!ROSTER_IMPORT) return;
  const {config, file, result} = ROSTER_IMPORT;
  const target = config.kind === "conscripts" ? "قائمة المجندين الحالية" : "قائمة الأفراد الموجودة على القوة";
  const confirmed = await confirmDialog({
    title: "تأكيد الاستبدال الكامل",
    body: `سيتم استبدال ${target} ببيانات الملف (${result.total} سجلًا). العملية تُحفظ كوحدة واحدة في سجل التغييرات.`,
    confirmLabel: "نعم، طبّق الاستبدال", danger: true,
  });
  if (!confirmed) return;
  const form = new FormData();
  form.append("file", file); form.append("source_hash", result.source_hash);
  form.append("revision", result.revision); form.append("effective_date", $("#rosterImportDate").value);
  const out = await api(`/api/roster-import/${config.kind}/apply`, {
    method: "POST", body: form, loadingLabel: "جاري تطبيق الكشف وحفظ البيانات…", timeoutMs: 60000,
  });
  if (!out) return;
  await closeModal("rosterImportModal", true);
  showToast(`تم استبدال الكشف بنجاح: ${out.total} سجل`);
  ROSTER_IMPORT = null;
  await config.onApplied?.();
});
