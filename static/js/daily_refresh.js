/* زرار «تحديث ملف اليومية»: يعيد توليد ملف (أو ملفات) اليومية دي بس في
   فولدر الأرشيف. كل صفحة تعلن الأنواع في data-daily-files (مفصولة بفاصلة)
   وتوفّر window.dailyFileDay(). التحديث العام لكل الملفات لسه في اليومية التفصيلية. */
(function () {
  const kinds = (document.body.dataset.dailyFiles || "").split(",").map(k => k.trim()).filter(Boolean);
  if (!kinds.length) return;
  const host = document.getElementById("dayFiles") || document.querySelector(".page-head .page-actions");
  if (!host) return;

  const button = document.createElement("button");
  button.type = "button";
  button.className = "btn refresh-daily-file-btn";
  button.id = "btnRefreshDailyFile";
  button.title = "يعيد توليد ملف هذه اليومية فقط في فولدر الأرشيف";
  button.innerHTML = `${icon("refresh")}<span>تحديث ملف اليومية</span>`;
  const status = document.createElement("small");
  status.className = "muted";
  status.id = "dailyFileRefreshStatus";
  status.setAttribute("role", "status");
  const setup = host.querySelector(".day-files-setup");
  if (setup) { setup.before(button); setup.before(status); } else { host.append(button, status); }

  const clock = at => new Date(at || Date.now()).toLocaleTimeString("ar-EG", {hour: "2-digit", minute: "2-digit"});

  button.onclick = async () => {
    const day = typeof window.dailyFileDay === "function" ? window.dailyFileDay() : null;
    if (!day) { showToast("لا توجد يومية محددة لتحديث ملفها.", true); return; }
    button.disabled = true;
    const done = [], failed = [];
    let folder = "", at = "";
    try {
      for (const kind of kinds) {
        const out = await api(`/api/day-files/${day}/${kind}`, {
          ...jsonReq("POST", {}), timeoutMs: 120000, loadingLabel: "تحديث ملف اليومية",
          onError: (body, code) => {
            if (code !== 409 && code !== 500) return false;
            failed.push(body.error || "فشل التحديث");
            return true;
          },
        });
        if (out && out.result && out.result.ok) { done.push(out.result.path); folder = out.folder; at = out.at; }
        else if (!out && !failed.length) failed.push("تعذّر التحديث");
      }
    } finally { button.disabled = false; }
    if (failed.length) {
      status.textContent = "فشل تحديث الملف";
      showToast(failed.join("، "), true);
      return;
    }
    status.textContent = `آخر تحديث لملف اليومية: ${clock(at)}`;
    status.title = folder;
    showToast(`تم تحديث ${done.length > 1 ? done.length + " ملفات" : "ملف اليومية"} — ${done.join("، ")}`);
  };
})();
