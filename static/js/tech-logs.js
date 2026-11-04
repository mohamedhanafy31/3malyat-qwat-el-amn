/* السجلات الفنية — آخر أسطر system.log / errors.log / ocr.log للمشرف */

let LOG_TIMER = null;

function logLevelOf(block) {
  const m = /^\S+ \| (\w+) \|/.exec(block);
  return m ? m[1] : "INFO";
}

async function loadLogs() {
  const q = new URLSearchParams();
  q.set("file", $("#logFile").value);
  q.set("lines", $("#logLines").value);
  const level = $("#logLevel").value;
  if (level) q.set("level", level);
  const text = $("#logSearch").value.trim();
  if (text) q.set("q", text);
  $("#logDownload").href = `/api/tech-logs/download?file=${encodeURIComponent($("#logFile").value)}`;

  const d = await api(`/api/tech-logs?${q.toString()}`);
  const out = $("#logOut");
  if (!d) { out.textContent = ""; return; }
  const records = d.records || [];
  $("#logMeta").textContent =
    `${d.file} — ${records.length} سجل — حجم الملف ${Math.round((d.size || 0) / 1024)} ك.ب` +
    (d.truncated ? " (عرض الجزء الأخير فقط)" : "");
  out.innerHTML = records.length
    ? records.map(r => `<span class="tl tl-${esc(logLevelOf(r))}">${esc(r)}</span>`).join("\n")
    : "لا توجد سجلات مطابقة.";
  out.scrollTop = out.scrollHeight;
}

["#logFile", "#logLevel", "#logLines"].forEach(s => { $(s).onchange = loadLogs; });
$("#logRefresh").onclick = loadLogs;
$("#logSearch").addEventListener("input", () => {
  clearTimeout(LOG_TIMER);
  LOG_TIMER = setTimeout(loadLogs, 350);
});
loadLogs();
