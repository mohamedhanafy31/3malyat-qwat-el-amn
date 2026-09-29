/* الرئيسية — كل الأرقام والتنبيهات محسوبة في الباك إند، فالصفحة دي
   بتحمّل ~2 كيلوبايت بس بدل 225. */
(async () => {
  const d = await bootstrap();
  if (!d) return;
  const c = d.counts;

  // تحذير غير مانع — ساعة الجهاز رجعت لتاريخ قبل آخر مرة شغّل عليها
  // السيستم، وممكن ده يأثر على القفل التلقائي لليوم (backend/clock.py)
  $("#clockWarning").innerHTML = d.clock_warning
    ? `<div class="alert-card"><div class="alert-head">
         <span class="alert-ico">${icon("clock","ico-lg")}</span><strong>تنبيه: ساعة الجهاز</strong></div>
         <p class="muted">${esc(d.clock_warning)}</p></div>`
    : "";

  // أمر وقف راحات ساري — لازم يبان أول ما السيستم يتفتح، مش بس في صفحة الراحات
  const susp = META.rest_suspension || {};
  $("#restSuspension").innerHTML = (susp.active || []).length
    ? `<div class="alert-card susp-banner"><div class="alert-head">
         <span class="alert-ico">${icon("block","ico-lg")}</span><strong>الراحات موقوفة: ${(susp.types || []).map(esc).join("، ")}</strong>
         <span class="muted">من ${fmt(susp.active[0].started_on)} — تسجيل راحة من الأنواع دي لأي ضابط بيترفض.</span>
         <a class="mini" href="/leaves">إدارة الوقف</a></div></div>`
    : "";

  // كل بطاقة رابط لصفحتها. التقصيرة وحدها تحتاج انتباهًا؛ الباقي محايد.
  const tile = (href, label, value, cls = "") =>
    `<a class="stat stat-link ${cls}" href="${href}"><span>${label}</span><strong>${value}</strong></a>`;
  $("#dashStats").innerHTML =
    tile("/officers", "الضباط على القوة", c.officers) +
    tile("/personnel", "الأفراد على القوة", c.personnel) +
    tile("/leaves", "في راحة اليوم", c.on_rest) +
    tile("/officers", "تنبيهات تقصيرة", c.taqseera, c.taqseera > 0 ? "stat-accent-orange" : "");
  renderAlerts(d.alerts);

  // ── مهام اليوم ──
  const u = d.upcoming || {};
  const hhmm = at => (at || "").slice(11, 16);
  const conf = d.confirm || {};
  const task = (state, text, href, label) => `<li class="task task-${state}">
      <span class="status-dot ${state}" aria-hidden="true"></span>
      <span class="task-text">${text}</span>
      ${href ? `<a class="btn" href="${href}">${esc(label)}</a>` : ""}</li>`;
  const confirmTask = !conf.confirmed && !conf.count
    ? task("muted", "لا توجد خدمات مسجّلة في اليومية التفصيلية اليوم", "/board", "فتح اليومية")
    : !conf.confirmed
      ? task("warn", "<b>اليومية التفصيلية لم تُؤكَّد بعد</b> — التغييرات لا تُسجَّل في سجل التغييرات قبل التأكيد", "/board", "تأكيد اليومية")
      : conf.pending
        ? task("warn", `<b>توجد تعديلات بعد آخر تأكيد</b> (الساعة ${esc(hhmm(conf.at))})`, "/board", "مراجعة وتأكيد")
        : task("ok", `اليومية مؤكدة الساعة ${esc(hhmm(conf.at))}${conf.by ? ` — ${esc(conf.by)}` : ""}`, "/board", "عرض اليومية");
  const vac = (u.tomorrow_vacant || []).length;
  const vacTask = vac
    ? task("warn", `<b>${countLabel(vac, "خدمة")} شاغرة غدًا</b>`, "/board", "تعيين")
    : task("ok", "لا توجد خدمات شاغرة غدًا", "", "");
  const back = (u.leaves_ending_soon || []).length;
  const backTask = back
    ? task("muted", `${back === 1 ? "ضابط واحد يعود" : `${countLabel(back, "ضابط")} يعودون`} من الراحة خلال 3 أيام`, "/leaves", "سجل الراحات")
    : task("muted", "لا يعود أحد من الراحة خلال 3 أيام", "", "");
  $("#dashTasks").innerHTML = confirmTask + vacTask + backTask;

  const recent = d.recent_changes || [];
  $("#dashChanges").innerHTML = recent.length ? `<h4>آخر التغييرات <a href="/changes">عرض الكل</a></h4>
    <ul class="change-list">${recent.map(e => `<li>
      <time>${esc(fmtShort((e.ts || "").slice(0, 10)))} ${esc(hhmm(e.ts))}</time>
      <span>${esc(humanizeDates(e.text || `${e.entity} ${e.action}`))}</span>
      ${e.edited_by ? `<em>${esc(e.edited_by)}</em>` : ""}</li>`).join("")}</ul>`
    : `<p class="recent-empty">لا توجد تغييرات حديثة.</p>`;

  const col = (title, rows, render) => `<section class="dash-col">
    <h4>${title} <em>${rows.length || ""}</em></h4>
    ${rows.length
      ? `<ul class="dash-list">${rows.map(render).join("")}</ul>`
      : emptyState({compact: true, title: "لا يوجد شيء مستحق"})}
  </section>`;

  $("#dashUpcoming").innerHTML =
    col("راحات هترجع خلال 3 أيام", u.leaves_ending_soon || [], lv =>
      `<li><b>${esc(lv.person_role)} / ${esc(lv.person_name)}</b><span>${esc(lv.type)} · يعود ${esc(dayName(lv.return_date))} ${esc(fmt(lv.return_date))}</span></li>`) +
    col("فرق هتبدأ خلال 3 أيام", u.courses_starting_soon || [], t =>
      `<li><b>${esc(t.officer_name)}</b><span>${esc(t.course_name)} — يبدأ ${fmt(t.start)}</span></li>`) +
    col("خدمات بكرة لسه شاغرة", u.tomorrow_vacant || [], w =>
      `<li><b>${esc(w.text)}</b></li>`);
})();
