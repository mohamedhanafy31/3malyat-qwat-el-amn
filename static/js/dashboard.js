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
         <span class="alert-ico">⏱</span><strong>تنبيه: ساعة الجهاز</strong></div>
         <p class="muted">${esc(d.clock_warning)}</p></div>`
    : "";

  // أمر وقف راحات ساري — لازم يبان أول ما السيستم يتفتح، مش بس في صفحة الراحات
  const susp = META.rest_suspension || {};
  $("#restSuspension").innerHTML = (susp.active || []).length
    ? `<div class="alert-card susp-banner"><div class="alert-head">
         <span class="alert-ico">⛔</span><strong>الراحات موقوفة: ${(susp.types || []).map(esc).join("، ")}</strong>
         <span class="muted">من ${fmt(susp.active[0].started_on)} — تسجيل راحة من الأنواع دي لأي ضابط بيترفض.</span>
         <a class="mini" href="/leaves">إدارة الوقف</a></div></div>`
    : "";

  // لون الحافة العلوية بيقول معنى: التقصيرة ذهبية زي التنبيه، الراحة زرقاء
  $("#dashStats").innerHTML = `
    <div class="stat"><span>الضباط على القوة</span><strong>${c.officers}</strong></div>
    <div class="stat"><span>الأفراد على القوة</span><strong>${c.personnel}</strong></div>
    <div class="stat stat-accent-blue"><span>في راحة اليوم</span><strong>${c.on_rest}</strong></div>
    <div class="stat stat-accent-gold"><span>تنبيهات تقصيرة</span><strong>${c.taqseera}</strong></div>`;
  $("#qlOfficers").textContent = c.officers;
  $("#qlPersonnel").textContent = c.personnel;
  $("#qlLeaves").textContent = c.leaves;

  const day = curDate();
  $("#dashToday").innerHTML = `<b>${dayName(day)}</b> ${fmt(day)}`;
  renderAlerts(d.alerts);

  const u = d.upcoming || {};
  const col = (title, rows, render) => `<section class="dash-col">
    <h4>${title} <em>${rows.length || ""}</em></h4>
    ${rows.length
      ? `<ul class="dash-list">${rows.map(render).join("")}</ul>`
      : `<p class="dash-none">مفيش حاجة مستحقة</p>`}
  </section>`;

  $("#dashUpcoming").innerHTML =
    col("راحات هترجع خلال ٣ أيام", u.leaves_ending_soon || [], lv =>
      `<li><b>${esc(lv.name)}</b><span>${esc(lv.type)} — بيرجع ${fmt(lv.return_date)}</span></li>`) +
    col("فرق هتبدأ خلال ٣ أيام", u.courses_starting_soon || [], t =>
      `<li><b>${esc(t.officer_name)}</b><span>${esc(t.course_name)} — يبدأ ${fmt(t.start)}</span></li>`) +
    col("خدمات بكرة لسه شاغرة", u.tomorrow_vacant || [], w =>
      `<li><b>${esc(w.text)}</b></li>`);
})();
