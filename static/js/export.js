/* تصدير/طباعة الصفحة — زرار واحد «تصدير» في رأس الصفحة، بيظهر بس في الصفحات
   اللي فيها جداول (القالب بيعلن ده بـ data-export على <body>).
   - Excel: ملف .xlsx حقيقي (Office Open XML) مبني هنا من غير أي مكتبة — ZIP
     بطريقة التخزين من غير ضغط + CRC32. الـ.xls القديم كان XML متلبّس امتداد
     إكسل، فإكسل كان بيحذّر «صيغة الملف لا تطابق الامتداد».
   - طباعة/PDF: طباعة المتصفح (فيها «حفظ كـPDF»).
   - Word: بس في اليومية التفصيلية ويومية الأفراد، ملف .docx رسمي من السيرفر
     (الصفحة بتحدد رابطه في window.exportDocxUrl).
   الجداول الطويلة بتتعرض 50 50 (pageSlice في core.js)، فالتصدير والطباعة
   بيفتحوا كل الصفوف مؤقتًا الأول — وإلا الملف كان هيطلع بأول 50 بس. */

(function () {
  const modes = (document.body.dataset.export || "").split(/\s+/).filter(Boolean);
  if (!modes.length) return;

  const SKIP_CELLS = ".row-menu-btn, .actions, .mini, .btn, .sr-only, .ico, script, style";

  function pageName() {
    const h2 = document.querySelector(".page-head .titles h2");
    return (h2 && h2.textContent.trim()) || document.title || "تصدير";
  }
  function dayStamp() {
    const d = document.getElementById("dutyDate");
    return (d && d.value) || curDate();
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

  /* ---------- كل الصفوف مؤقتًا ---------- */
  let _expanded = null;
  function expandAllPages() {
    if (_expanded) return;
    _expanded = {};
    for (const [cid, st] of Object.entries(_pageStates)) {
      if (st.limit === Infinity) continue;
      _expanded[cid] = st.limit;
      st.limit = Infinity;
      (_sortRenders[cid] || _pageRenders[cid])?.();
    }
  }
  function restorePages() {
    if (!_expanded) return;
    for (const [cid, limit] of Object.entries(_expanded)) {
      if (!_pageStates[cid]) continue;
      _pageStates[cid].limit = limit;
      (_sortRenders[cid] || _pageRenders[cid])?.();
    }
    _expanded = null;
  }
  window.addEventListener("beforeprint", expandAllPages);
  window.addEventListener("afterprint", restorePages);

  /* ---------- قراءة الجداول الظاهرة ---------- */
  function sheetTitle(table, index) {
    const card = table.closest(".mcard, .dash-card, .ls-card");
    const h = card?.querySelector("h3, .ls-card-title");
    if (h) {
      const c = h.cloneNode(true);
      c.querySelectorAll(".mcount, button, .sr-only").forEach(el => el.remove());
      const t = c.textContent.trim();
      if (t) return t;
    }
    return index === 1 ? pageName() : `${pageName()} ${index}`;
  }
  // حدود العناصر بتتحول لفواصل عشان «الاسم» و«الرتبة» تحته ما يلزقوش في
  // كلمة واحدة: سطر جديد بين الكتل (div/p/li/br)، ومسافة بعد العناصر السطرية
  function cellText(cell) {
    const c = cell.cloneNode(true);
    c.querySelectorAll(SKIP_CELLS).forEach(el => el.remove());
    c.querySelectorAll("br").forEach(el => el.replaceWith("\n"));
    c.querySelectorAll("div, p, li").forEach(el => { el.before("\n"); el.after("\n"); });
    c.querySelectorAll("span, b, i, em, strong, small, a").forEach(el => el.after(" "));
    return c.textContent.replace(/[ \t\u00a0]+/g, " ").replace(/ *\n\s*/g, "\n").trim();
  }
  /* الخانات بتتحط في شبكة بتحترم rowspan/colspan — رأس جدول الإجمالي في
     يومية الضباط صفين متداخلين، ومن غير الشبكة الصف التاني كان بيبدأ من
     أول عمود بدل ما يقع تحت مجموعته. عمود «الإجراء» بيتشال بالكامل. */
  function tableRows(table) {
    const grid = [];
    [...table.querySelectorAll("tr")].forEach((tr, r) => {
      grid[r] = grid[r] || [];
      const group = tr.classList.contains("grouprow");
      let c = 0;
      [...tr.children].forEach(cell => {
        while (grid[r][c] !== undefined) c++;
        const rs = cell.rowSpan || 1, cs = cell.colSpan || 1;
        const header = cell.tagName === "TH" || group;
        const text = cellText(cell);
        const action = cell.classList.contains("col-actions") || (cell.tagName === "TH" && text === "الإجراء");
        for (let dr = 0; dr < rs; dr++) {
          grid[r + dr] = grid[r + dr] || [];
          for (let dc = 0; dc < cs; dc++) {
            grid[r + dr][c + dc] = dr === 0 && dc === 0 ? { text, header, action } : { text: "", header };
          }
        }
        c += cs;
      });
    });
    const drop = new Set();
    grid.forEach(row => row.forEach((cell, i) => { if (cell?.action) drop.add(i); }));
    return grid.map(row => {
      const out = [];
      for (let i = 0; i < row.length; i++) if (!drop.has(i)) out.push(row[i] || { text: "", header: false });
      return out;
    }).filter(r => r.some(c => c.text));
  }
  function collectTables() {
    const main = document.querySelector("main");
    return [...main.querySelectorAll("table")].filter(t => t.querySelector("tbody tr, tr"));
  }

  /* ---------- XLSX ---------- */
  const CRC_TABLE = (() => {
    const t = new Uint32Array(256);
    for (let n = 0; n < 256; n++) {
      let c = n;
      for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1;
      t[n] = c >>> 0;
    }
    return t;
  })();
  function crc32(bytes) {
    let c = 0xFFFFFFFF;
    for (let i = 0; i < bytes.length; i++) c = CRC_TABLE[(c ^ bytes[i]) & 0xFF] ^ (c >>> 8);
    return (c ^ 0xFFFFFFFF) >>> 0;
  }
  function zipStore(files) {
    const enc = new TextEncoder();
    const parts = [], central = [];
    let offset = 0;
    for (const f of files) {
      const name = enc.encode(f.name), data = enc.encode(f.text);
      const crc = crc32(data), size = data.length;
      const local = new DataView(new ArrayBuffer(30));
      local.setUint32(0, 0x04034b50, true); local.setUint16(4, 20, true);
      local.setUint16(6, 0x0800, true);            // أسماء الملفات UTF-8
      local.setUint16(12, 0x21, true);             // 1980-01-01
      local.setUint32(14, crc, true); local.setUint32(18, size, true); local.setUint32(22, size, true);
      local.setUint16(26, name.length, true);
      parts.push(new Uint8Array(local.buffer), name, data);
      const cen = new DataView(new ArrayBuffer(46));
      cen.setUint32(0, 0x02014b50, true); cen.setUint16(4, 20, true); cen.setUint16(6, 20, true);
      cen.setUint16(8, 0x0800, true); cen.setUint16(14, 0x21, true);
      cen.setUint32(16, crc, true); cen.setUint32(20, size, true); cen.setUint32(24, size, true);
      cen.setUint16(28, name.length, true); cen.setUint32(42, offset, true);
      central.push(new Uint8Array(cen.buffer), name);
      offset += 30 + name.length + size;
    }
    const cenSize = central.reduce((n, c) => n + c.length, 0);
    const end = new DataView(new ArrayBuffer(22));
    end.setUint32(0, 0x06054b50, true);
    end.setUint16(8, files.length, true); end.setUint16(10, files.length, true);
    end.setUint32(12, cenSize, true); end.setUint32(16, offset, true);
    return new Blob([...parts, ...central, new Uint8Array(end.buffer)],
      { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
  }
  const xmlEsc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]))
    .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, "");
  function colName(i) {
    let s = "";
    for (i++; i > 0; i = Math.floor((i - 1) / 26)) s = String.fromCharCode(65 + ((i - 1) % 26)) + s;
    return s;
  }
  // رقم بس لو شكله رقم فعلًا — «01097…» (هاتف) و«765/2002» (أقدمية) بيفضلوا نص
  const isNumeric = t => /^-?(0|[1-9]\d{0,14})(\.\d+)?$/.test(t);
  function sheetXml(rows) {
    const body = rows.map((r, ri) => `<row r="${ri + 1}">${r.map((c, ci) => {
      const ref = `${colName(ci)}${ri + 1}`;
      if (!c.text) return `<c r="${ref}"${c.header ? ' s="1"' : ""}/>`;
      if (!c.header && isNumeric(c.text)) return `<c r="${ref}"><v>${c.text}</v></c>`;
      const style = c.header ? ' s="1"' : c.text.includes("\n") ? ' s="2"' : "";
      return `<c r="${ref}" t="inlineStr"${style}><is><t xml:space="preserve">${xmlEsc(c.text)}</t></is></c>`;
    }).join("")}</row>`).join("");
    return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetViews><sheetView rightToLeft="1" workbookViewId="0"/></sheetViews><sheetData>${body}</sheetData></worksheet>`;
  }
  function buildXlsx(sheets) {
    const ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"';
    const rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships";
    const files = [
      { name: "[Content_Types].xml", text: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>${sheets.map((_, i) => `<Override PartName="/xl/worksheets/sheet${i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>`).join("")}</Types>` },
      { name: "_rels/.rels", text: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="${rel}/officeDocument" Target="xl/workbook.xml"/></Relationships>` },
      { name: "xl/workbook.xml", text: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook ${ns} xmlns:r="${rel}"><sheets>${sheets.map((s, i) => `<sheet name="${xmlEsc(s.name)}" sheetId="${i + 1}" r:id="rId${i + 1}"/>`).join("")}</sheets></workbook>` },
      { name: "xl/_rels/workbook.xml.rels", text: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">${sheets.map((_, i) => `<Relationship Id="rId${i + 1}" Type="${rel}/worksheet" Target="worksheets/sheet${i + 1}.xml"/>`).join("")}<Relationship Id="rId${sheets.length + 1}" Type="${rel}/styles" Target="styles.xml"/></Relationships>` },
      { name: "xl/styles.xml", text: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet ${ns}><fonts count="2"><font><sz val="11"/><name val="Arial"/></font><font><b/><sz val="11"/><name val="Arial"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment wrapText="1" vertical="top"/></xf></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>` },
      ...sheets.map((s, i) => ({ name: `xl/worksheets/sheet${i + 1}.xml`, text: sheetXml(s.rows) })),
    ];
    return zipStore(files);
  }

  function exportXlsx() {
    expandAllPages();
    try {
      const tables = collectTables();
      if (!tables.length) { showToast("لا توجد جداول في هذه الصفحة للتصدير", true); return; }
      const seen = new Set();
      const sheets = tables.map((t, i) => {
        const base = sheetTitle(t, i + 1).replace(/[\\/:*?[\]]/g, "-").slice(0, 31) || `جدول ${i + 1}`;
        let name = base, n = 2;
        while (seen.has(name)) name = `${base.slice(0, 27)} (${n++})`;
        seen.add(name);
        return { name, rows: tableRows(t) };
      }).filter(s => s.rows.length);
      download(buildXlsx(sheets), fileBase() + ".xlsx");
    } finally {
      restorePages();
    }
  }
  // مكشوفة للاختبار اليدوي والصفحات
  window.buildXlsx = buildXlsx;

  ACTIONS._exportXlsx = () => exportXlsx();
  ACTIONS._exportPrint = () => window.print();
  ACTIONS._exportDocx = () => {
    const url = typeof window.exportDocxUrl === "function" ? window.exportDocxUrl() : null;
    if (url) window.location.href = url;
  };

  /* ---------- الزرار في رأس الصفحة ---------- */
  const actions = document.querySelector(".page-head .page-actions");
  if (!actions) return;
  const items = [];
  if (modes.includes("xlsx")) items.push({ action: "_exportXlsx", label: "Excel (.xlsx)" });
  if (modes.includes("docx")) items.push({ action: "_exportDocx", label: "Word (.docx) — الشكل الرسمي" });
  if (modes.includes("print")) items.push({ action: "_exportPrint", label: "طباعة / حفظ PDF" });
  const wrap = document.createElement("div");
  wrap.className = "export-toolbar";
  wrap.innerHTML = `<button type="button" class="btn row-menu-btn export-btn" aria-haspopup="menu"
      aria-expanded="false" aria-controls="rowMenuPopup" data-menu="${dataAttr(items)}">
      ${icon("download")}<span>تصدير</span>${icon("chevron-down")}</button>`;
  // الإجراء الأساسي للصفحة بييجي الأول، والتصدير بعده
  actions.append(wrap);
  const btn = wrap.querySelector("button");

  // الزرار بيتعطّل لو الصفحة مافيهاش صفوف تتصدّر (سجل ضابط قبل اختياره، مأموريات فاضية)
  function syncEnabled() {
    // صفحات الكروت (دليل الخدمات، الفرق) مالهاش جداول للإكسل بس ليها طباعة
    const has = !!document.querySelector("main table tbody tr")
      || (modes.includes("print") && !!document.querySelector("main .service-card, main .course-card"));
    btn.setAttribute("aria-disabled", String(!has));
    btn.title = has ? "تصدير أو طباعة جداول الصفحة" : "لا توجد بيانات للتصدير";
  }
  let queued = false;
  new MutationObserver(() => {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => { queued = false; syncEnabled(); });
  }).observe(document.querySelector("main"), { childList: true, subtree: true });
  syncEnabled();
})();
