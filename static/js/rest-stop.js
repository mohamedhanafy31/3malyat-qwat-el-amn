/* إيقاف راحة ضابط قبل نهايتها — مشترك بين صفحة الراحات وصفحة الضباط.
   التاريخ هنا «أول يوم رجوع»: الراحة بتتقص لحد اليوم اللي قبله، وراحة لسه
   ما بدأتش بتتلغي بالكامل (`backend/rest_suspension.py::stop_leave`). */
let _STOP_LEAVE = null, _STOP_DONE = null;

function _stopHint() {
  const lv = _STOP_LEAVE, on = $("#stopOn").value;
  if (!lv || !on) { $("#stopHint").textContent = ""; return }
  const hint = $("#stopHint");
  if (lv.end && on > lv.end) {
    hint.dataset.tone = "bad";
    hint.innerHTML = `${icon("alert")} التاريخ بعد نهاية الراحة — لا يوجد ما يتوقف.`;
  } else if (lv.start && on <= lv.start) {
    hint.dataset.tone = "bad";
    hint.textContent = "ستُلغى الراحة بالكامل؛ لن تظهر في اليومية.";
  } else {
    hint.dataset.tone = "warn";
    hint.textContent =
      `سيكون آخر يوم راحة ${fmt(addDays(on, -1))}، ويعود إلى العمل ${fmt(on)}`
      + (lv.end ? ` (عوضًا عن ${fmt(addDays(lv.end, 1))})` : "") + ".";
  }
}

function openStopLeave(leave, onDone) {
  _STOP_LEAVE = leave; _STOP_DONE = onDone;
  $("#stopLeaveId").value = leave.id;
  $("#stopLeaveWho").innerHTML = `<strong>${esc(leave.name || "")}</strong>
    <span>${esc(leave.type || "")}</span>
    ${leave.start && leave.end ? `<span dir="ltr">${esc(fmt(leave.start))} ← ${esc(fmt(leave.end))}</span>` : ""}`;
  $("#stopOn").value = curDate();
  const upcoming = !!leave.start && curDate() < leave.start;
  $("#stopOnRow").classList.toggle("hidden", upcoming);
  $("#stopOn").required = !upcoming;
  $("#stopLeaveModalTitle").textContent = upcoming ? "إلغاء الراحة قبل بدايتها" : "إنهاء الراحة والعودة للعمل";
  $("#stopLeaveSubmit").textContent = upcoming ? "إلغاء الراحة" : "إنهاء الراحة";
  $("#stopLeaveSubmit").classList.toggle("danger", upcoming);
  $("#stopLeaveSubmit").classList.toggle("primary", !upcoming);
  $("#stopReason").value = "";
  $("#stopReason").placeholder = upcoming ? "مثال: تم التسجيل بالخطأ" : "مثال: استدعاء بقرار المديرية";
  _stopHint();
  openModal("stopLeaveModal");
}

$("#stopOn").addEventListener("change", _stopHint);

$("#stopLeaveForm").onsubmit = async e => {
  e.preventDefault();
  const reason = $("#stopReason").value.trim();
  if (!reason) { showToast("يلزم سبب مكتوب لإيقاف الراحة"); return }
  const out = await api(`/api/leaves/${encodeURIComponent($("#stopLeaveId").value)}/stop`,
    jsonReq("POST", {on: $("#stopOn").value, reason}));
  if (!out) return;
  closeModal("stopLeaveModal", true);
  showToast(out.cancelled ? "تم إلغاء الراحة" : "تم إيقاف الراحة");
  if (_STOP_DONE) _STOP_DONE();
};
