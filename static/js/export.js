/* طباعة/تصدير أي صفحة — زر واحد بيتحقن جنب عنوان كل صفحة من base.html،
   بيشتغل على المحتوى الظاهر فعليًا في المتصفح من غير أي طلب سيرفر ولا
   مكتبة خارجية (السيستم شغّال من غير إنترنت أصلًا). PDF بيبقى عن طريق
   "طباعة" المتصفح (فيه زرار "حفظ كـPDF" جاهز في أي نافذة طباعة)، وExcel/Word
   بيتبنوا كملف XML/HTML بصيغة أوفيس بيتقرا في Word/Excel مباشرة. */

(function () {
  const EXCLUDE_SELECTOR = [
    ".topbar", ".sidebar", ".scrim", ".tabs", ".toolbar", ".actions", ".mini",
    ".btn", ".primary", ".danger", "#balanceTag", ".nav-dot", ".alert-toggle",
    ".ls-nav", ".ls-filter-bar", ".export-toolbar", "script", "style",
  ].join(",");

  function pageName() {
    const h2 = document.querySelector(".page-head .titles h2");
    return (h2 && h2.textContent.trim()) || document.title || "يومية";
  }

  function dayStamp() {
    const d = document.getElementById("dutyDate");
    return (d && d.value) || new Date().toISOString().slice(0, 10);
  }

  function fileBase() {
    return `${pageName()} - ${dayStamp()}`.replace(/[\\/:*?"<>|]/g, "-");
  }

  function download(blob, filename) {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  function cleanClone() {
    const container = document.querySelector("main.content .container");
    if (!container) return null;
    const clone = container.cloneNode(true);
    clone.querySelectorAll(EXCLUDE_SELECTOR).forEach((el) => el.remove());
    return clone;
  }

  function exportWord() {
    const clone = cleanClone();
    if (!clone) return;
    const html = `<html xmlns:o="urn:schemas-microsoft-com:office:office"
xmlns:w="urn:schemas-microsoft-com:office:word" xmlns="http://www.w3.org/TR/REC-html40">
<head><meta charset="utf-8"><title>${esc(pageName())}</title>
<style>
  body{font-family:Arial,Tahoma,sans-serif;direction:rtl}
  table{border-collapse:collapse;width:100%;margin-bottom:16px}
  th,td{border:1px solid #999;padding:4px 8px;text-align:right;font-size:12px}
  th{background:#e9e9e9}
</style></head>
<body dir="rtl">${clone.innerHTML}</body></html>`;
    download(new Blob(["\ufeff" + html], { type: "application/msword" }), fileBase() + ".doc");
  }

  function sheetTitle(table, index) {
    let prev = table.previousElementSibling;
    while (prev) {
      if (/^H[1-6]$/.test(prev.tagName)) {
        const h = prev.cloneNode(true);
        h.querySelectorAll(".mcount,.mini,.btn,button").forEach((el) => el.remove());
        const text = h.textContent.trim();
        if (text) return text;
      }
      prev = prev.previousElementSibling;
    }
    return `جدول ${index}`;
  }

  function cellXml(cell) {
    const text = cell.textContent.trim();
    const isHeader = cell.tagName === "TH";
    const isNumber = text !== "" && !isNaN(text.replace(/,/g, ""));
    const type = !isHeader && isNumber ? "Number" : "String";
    const value = type === "Number" ? text.replace(/,/g, "") : text;
    return `<Cell><Data ss:Type="${type}">${esc(value)}</Data></Cell>`;
  }

  function exportExcel() {
    const clone = cleanClone();
    if (!clone) return;
    const tables = [...clone.querySelectorAll("table")].filter((t) => t.querySelector("tr"));
    if (!tables.length) {
      showToast("مفيش جدول في الصفحة دي للتصدير", true);
      return;
    }
    const seenNames = new Set();
    const worksheets = tables.map((table, i) => {
      let name = sheetTitle(table, i + 1).replace(/[\\/:*?[\]]/g, "-").slice(0, 31) || `جدول ${i + 1}`;
      let unique = name, n = 2;
      while (seenNames.has(unique)) unique = `${name.slice(0, 28)} ${n++}`;
      seenNames.add(unique);
      const rows = [...table.querySelectorAll("tr")]
        .map((tr) => `<Row>${[...tr.children].map(cellXml).join("")}</Row>`)
        .join("");
      return `<Worksheet ss:Name="${esc(unique)}"><Table>${rows}</Table></Worksheet>`;
    }).join("");
    const xml = `<?xml version="1.0"?>
<?mso-application progid="Excel.Sheet"?>
<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"
 xmlns:o="urn:schemas-microsoft-com:office:office"
 xmlns:x="urn:schemas-microsoft-com:office:excel"
 xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">
${worksheets}
</Workbook>`;
    download(new Blob([xml], { type: "application/vnd.ms-excel" }), fileBase() + ".xls");
  }

  function injectToolbar() {
    const actions = document.querySelector(".page-head .page-actions");
    if (!actions) return;
    const wrap = document.createElement("div");
    wrap.className = "export-toolbar";
    wrap.innerHTML = `
      <button type="button" class="mini" id="exportPrintBtn" title="طباعة، أو احفظ كـPDF من نافذة الطباعة">طباعة / PDF</button>
      <button type="button" class="mini" id="exportWordBtn" title="تصدير الصفحة كملف Word">Word</button>
      <button type="button" class="mini" id="exportExcelBtn" title="تصدير كل جداول الصفحة كملف Excel">Excel</button>`;
    actions.prepend(wrap);
    wrap.querySelector("#exportPrintBtn").onclick = () => window.print();
    wrap.querySelector("#exportWordBtn").onclick = exportWord;
    wrap.querySelector("#exportExcelBtn").onclick = exportExcel;
  }

  injectToolbar();
})();
