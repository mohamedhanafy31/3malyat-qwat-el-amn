/* الرئيسية — كل الأرقام والتنبيهات محسوبة في الباك إند، فالصفحة دي
   بتحمّل ~2 كيلوبايت بس بدل 225. */
(async () => {
  const d = await bootstrap();
  if (!d) return;
  const c = d.counts;

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
