/* أزرار التصدير الرسمية من السيرفر. كل صفحة تعلن نوعًا واحدًا في data-export.
   أي تصدير بيعدّي على previewExport: الملف بيتجاب، السيرفر يرجّع صفحاته صور،
   وبعد الموافقة بيتحمّل نفس الملف اللي اتعاين. */
function _exportFileName(response, url) {
  const header = response.headers.get("Content-Disposition") || "";
  const star = header.match(/filename\*=UTF-8''([^;]+)/i);
  if (star) return decodeURIComponent(star[1]);
  const plain = header.match(/filename="?([^";]+)"?/i);
  if (plain) return plain[1];
  return decodeURIComponent(new URL(url, location.href).pathname.split("/").pop() || "ملف");
}

function _exportPreviewModal() {
  let modal = document.getElementById("exportPreviewModal");
  if (modal) return modal;
  modal = document.createElement("div");
  modal.className = "modal hidden";
  modal.id = "exportPreviewModal";
  modal.innerHTML = `<div class="modal-card export-preview-card" role="dialog" aria-modal="true" aria-labelledby="exportPreviewTitle">
    <button type="button" class="close" data-close="exportPreviewModal" aria-label="إغلاق">×</button>
    <h2 id="exportPreviewTitle" tabindex="-1" autofocus>معاينة الملف</h2>
    <p class="export-preview-meta" id="exportPreviewMeta" role="status" aria-live="polite"></p>
    <div class="export-preview-pages" id="exportPreviewPages" aria-label="صفحات المعاينة"></div>
    <p class="field-hint export-preview-note" id="exportPreviewNote"></p>
    <div class="dialog-actions">
      <button type="button" class="primary" id="exportPreviewDownload" disabled>${icon("download")}<span>تحميل الملف</span></button>
      <button type="button" class="btn" data-close="exportPreviewModal">إلغاء</button>
    </div></div>`;
  document.body.appendChild(modal);
  modal.querySelectorAll("[data-close]").forEach(button => { button.onclick = () => closeModal("exportPreviewModal"); });
  modal.onclick = event => { if (event.target === modal) closeModal("exportPreviewModal"); };
  return modal;
}

function _renderExportPages(pages, holder) {
  holder.innerHTML = "";
  pages.forEach((src, index) => {
    const figure = document.createElement("figure");
    figure.className = "export-preview-page";
    const image = document.createElement("img");
    image.src = src;
    image.alt = `صفحة ${index + 1} من ${pages.length}`;
    figure.append(image);
    if (pages.length > 1) {
      const caption = document.createElement("figcaption");
      caption.textContent = `صفحة ${index + 1} من ${pages.length}`;
      figure.append(caption);
    }
    holder.append(figure);
  });
  return pages.length;
}

async function previewExport(url, label = "") {
  if (!url) { showToast("لا توجد يومية محددة لتصديرها.", true); return; }
  const modal = _exportPreviewModal();
  const meta = modal.querySelector("#exportPreviewMeta");
  const pages = modal.querySelector("#exportPreviewPages");
  const download = modal.querySelector("#exportPreviewDownload");
  const title = modal.querySelector("#exportPreviewTitle");
  const note = modal.querySelector("#exportPreviewNote");
  note.classList.add("hidden");
  const token = Symbol("preview");
  modal._token = token;
  title.textContent = "معاينة الملف";
  meta.textContent = "جارٍ تجهيز الملف…";
  meta.classList.remove("is-error");
  pages.innerHTML = `<div class="export-preview-loading"><span class="spinner" aria-hidden="true"></span></div>`;
  download.disabled = true;
  download.onclick = null;
  openModal("exportPreviewModal");

  let blob, name, savedTo;
  try {
    const response = await fetch(url, {credentials: "same-origin"});
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.error || "تعذّر تجهيز الملف.");
    }
    name = _exportFileName(response, url);
    savedTo = decodeURIComponent(response.headers.get("X-Saved-To") || "");
    blob = await response.blob();
  } catch (error) {
    if (modal._token !== token) return;
    meta.textContent = error.message || "تعذّر تجهيز الملف.";
    meta.classList.add("is-error");
    pages.innerHTML = "";
    return;
  }
  if (modal._token !== token) return;
  title.innerHTML = `معاينة: <bdi>${esc(label || name.replace(/\.+(docx|xlsx)$/i, ""))}</bdi>`;
  download.onclick = () => {
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = name;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(link.href), 10000);
    closeModal("exportPreviewModal");
    showToast(`تم تحميل ${name}`);
  };

  meta.textContent = "جارٍ تجهيز المعاينة…";
  try {
    const kind = /\.xlsx$/i.test(name) ? "xlsx" : "docx";
    const response = await fetch(`/api/export-preview?kind=${kind}`, {
      method: "POST", credentials: "same-origin", body: blob,
      headers: {"Content-Type": "application/octet-stream", "X-Requested-With": "fetch"},
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.error || "تعذّر تجهيز المعاينة.");
    }
    const result = await response.json();
    const count = _renderExportPages(result.pages || [], pages);
    const missing = result.missing_fonts || [];
    // بـ Word نفسه المعاينة مطابقة؛ بـ LibreOffice (جهاز التطوير) تقريبية ونقول ليه.
    const approximate = result.engine !== "word";
    note.textContent = !approximate ? ""
      : missing.length ? `معاينة تقريبية (LibreOffice): الخطوط دي مش متثبتة على السيرفر فممكن تختلف عن Word: ${missing.join("، ")}.`
      : "معاينة تقريبية (LibreOffice)؛ على جهاز التشغيل بـ Word بتبقى مطابقة للملف.";
    note.classList.toggle("hidden", !approximate);
    if (modal._token !== token) return;
    meta.textContent = count === 1 ? "صفحة واحدة — راجع الشكل ثم حمّل الملف." : `${count} صفحات — راجع الشكل ثم حمّل الملف.`;
    if (savedTo) meta.textContent += ` واتحفظت نسخة في الأرشيف: ${savedTo}`;
  } catch (error) {
    if (modal._token !== token) return;
    pages.innerHTML = "";
    meta.textContent = `${error.message || "تعذّر تجهيز المعاينة."} يمكنك تحميل الملف دون معاينة.`;
    meta.classList.add("is-error");
  }
  download.disabled = false;
  download.focus();
}
window.previewExport = previewExport;

(function () {
  const mode = document.body.dataset.export;
  if (mode !== "docx" && mode !== "xlsx") return;

  const actions = document.querySelector(".page-head .page-actions");
  if (!actions) return;

  const isExcel = mode === "xlsx";
  const actionName = isExcel ? "_exportXlsx" : "_exportDocx";
  const urlName = isExcel ? "exportXlsxUrl" : "exportDocxUrl";
  function exportFile() {
    const url = typeof window[urlName] === "function" ? window[urlName]() : null;
    // زرار الصفحة ممكن يكون متسمّي باسم الملف (زي «يومية الانتظام» في الرئيسية).
    const text = document.querySelector(`[data-action="${actionName}"] span`)?.textContent.trim();
    const label = text && !text.startsWith("تصدير") ? text : "";
    if (typeof window.beforeExport === "function") {
      window.beforeExport({url, label, preview: previewExport});
      return;
    }
    previewExport(url, label);
  }

  ACTIONS[actionName] = exportFile;
  const button = document.createElement("button");
  button.type = "button";
  button.className = "btn export-btn";
  button.dataset.action = actionName;
  button.innerHTML = `${icon("download")}<span>${isExcel ? "تصدير Excel" : "تصدير Word"}</span>`;
  actions.append(button);
})();
