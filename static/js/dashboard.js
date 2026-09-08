/* الرئيسية — كل الأرقام والتنبيهات محسوبة في الباك إند، فالصفحة دي
   بتحمّل ~2 كيلوبايت بس بدل 225. */
(async () => {
  const d = await bootstrap();
  if (!d) return;
  const c = d.counts;
  $("#dashStats").innerHTML = `
    <div class="stat"><span>الضباط على القوة</span><strong>${c.officers}</strong></div>
    <div class="stat"><span>الأفراد على القوة</span><strong>${c.personnel}</strong></div>
    <div class="stat"><span>في راحة اليوم</span><strong>${c.on_rest}</strong></div>
    <div class="stat"><span>تنبيهات تقصيرة</span><strong>${c.taqseera}</strong></div>`;
  $("#qlOfficers").textContent = c.officers;
  $("#qlPersonnel").textContent = c.personnel;
  $("#qlLeaves").textContent = c.leaves;

  const day = curDate();
  $("#dashToday").innerHTML = `<p class="hint" style="margin:0">
    ${dayName(day)} ${fmt(day)} — لمتابعة تفاصيل تشغيل اليوم افتح
    «يومية التشغيل» أو «لوحة التشغيل المختصرة» من القائمة.</p>`;
  renderAlerts(d.alerts);
})();
