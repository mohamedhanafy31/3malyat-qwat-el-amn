/* التصدير الرسمي الوحيد: Word DOCX من السيرفر.
   الصفحات المسموح لها فقط تعلن data-export="docx" وتحدد exportDocxUrl. */
(function () {
  if (document.body.dataset.export !== "docx") return;

  const actions = document.querySelector(".page-head .page-actions");
  if (!actions) return;

  function exportDocx() {
    const url = typeof window.exportDocxUrl === "function" ? window.exportDocxUrl() : null;
    if (!url) {
      showToast("لا توجد يومية محددة لتصديرها.", true);
      return;
    }
    window.location.assign(url);
  }

  ACTIONS._exportDocx = exportDocx;
  const button = document.createElement("button");
  button.type = "button";
  button.className = "btn export-btn";
  button.dataset.action = "_exportDocx";
  button.innerHTML = `${icon("download")}<span>تصدير Word</span>`;
  actions.append(button);
})();
