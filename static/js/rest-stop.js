/* إيقاف راحة ضابط قبل نهايتها — مشترك بين صفحة الراحات وصفحة الضباط.
   التاريخ هنا «أول يوم رجوع»: الراحة بتتقص لحد اليوم اللي قبله، وراحة لسه
   ما بدأتش بتتلغي بالكامل (`backend/rest_suspension.py::stop_leave`). */
let _STOP_LEAVE = null, _STOP_DONE = null;

function _stopHint() {
  const lv = _STOP_LEAVE, on = $("#stopOn").value;
  if (!lv || !on) { $("#stopHint").textContent = ""; return }
  if (lv.end && on > lv.end) {
    $("#stopHint").textContent = "⚠ التاريخ بعد نهاية الراحة — مفيش حاجة تتوقف.";
  } else if (lv.start && on <= lv.start) {
    $("#stopHint").textContent = "الراحة هتتلغي بالكامل (لسه ما بدأتش).";
  } else {
    $("#stopHint").textContent =
      `آخر يوم راحة هيبقى ${fmt(addDays(on, -1))}، ويرجع للعمل ${fmt(on)}`
      + (lv.end ? ` (بدل ${fmt(addDays(lv.end, 1))})` : "") + ".";
  }
}

function openStopLeave(leave, onDone) {
  _STOP_LEAVE = leave; _STOP_DONE = onDone;
  $("#stopLeaveId").value = leave.id;
  $("#stopLeaveWho").textContent = [leave.name, leave.type,
    leave.start && leave.end ? `${fmt(leave.start)} ← ${fmt(leave.end)}` : ""]
    .filter(Boolean).join(" — ");
  $("#stopOn").value = curDate();
  $("#stopReason").value = "";
  _stopHint();
  openModal("stopLeaveModal");
}

$("#stopOn").addEventListener("change", _stopHint);

$("#stopLeaveForm").onsubmit = async e => {
  e.preventDefault();
  const reason = $("#stopReason").value.trim();
  if (!reason) { showToast("لازم سبب مكتوب لإيقاف الراحة"); return }
  const out = await api(`/api/leaves/${encodeURIComponent($("#stopLeaveId").value)}/stop`,
    jsonReq("POST", {on: $("#stopOn").value, reason}));
  if (!out) return;
  closeModal("stopLeaveModal");
  showToast(out.cancelled ? "تم إلغاء الراحة" : "تم إيقاف الراحة");
  if (_STOP_DONE) _STOP_DONE();
};
