/* أزرار التصدير الرسمية من السيرفر. كل صفحة تعلن نوعًا واحدًا في data-export. */
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
    if (!url) {
      showToast("لا توجد يومية محددة لتصديرها.", true);
      return;
    }
    window.location.assign(url);
  }

  ACTIONS[actionName] = exportFile;
  const button = document.createElement("button");
  button.type = "button";
  button.className = "btn export-btn";
  button.dataset.action = actionName;
  button.innerHTML = `${icon("download")}<span>${isExcel ? "تصدير Excel" : "تصدير Word"}</span>`;
  actions.append(button);
})();
