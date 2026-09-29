/* صفحة وقف الراحات — الأوامر السارية (ومعاها بالظبط الراحات اللي
   أوقفتها/لغتها)، والأوامر اللي اتفتحت، وإنشاء أمر جديد على خطوتين.

   الأمر بيفضل ساري لحد «فتح الراحات»، والفتح مابيرجّعش أي راحة اتوقفت.
   وقت الإنشاء الراحات الجارية/القادمة من الأنواع المختارة بتتعرض من غير
   تحديد — المشغّل بيختار بنفسه اللي تتوقف (`backend/rest_suspension.py`). */
let SUSP = {active: [], history: []}, SUSP_CANDS = [];

const typeChips = types => types.map(t => `<span class="chip rest">${esc(t)}</span>`).join(" ");

function affectedList(o) {
  const stopped = (o.stopped_leaves || []).map(l => `<li>
      <b>${esc(l.name)}</b> <span class="chip w">${esc(l.type)}</span>
      <span class="sub">اتوقفت — كانت لحد ${fmt(l.original_end)}، رجع ${fmt(l.stopped_on)}</span></li>`);
  const cancelled = (o.cancelled_leaves || []).map(l => `<li>
      <b>${l.role ? esc(l.role) + "/ " : ""}${esc(l.name)}</b> <span class="chip w">${esc(l.type)}</span>
      <span class="sub">اتلغت قبل بدايتها (${fmt(l.start)} – ${fmt(l.end)})</span></li>`);
  const all = [...stopped, ...cancelled];
  return all.length ? `<ul class="susp-affected">${all.join("")}</ul>`
    : `<p class="muted susp-none">ما اتوقفتش أي راحة مسجّلة بالأمر ده.</p>`;
}

function activeCard(o) {
  return `<div class="susp-order">
    <div class="susp-order-head">
      <div class="susp-types">${typeChips(o.types)}</div>
      <button type="button" class="mini ok" data-action="liftSuspension" data-id="${esc(o.id)}"
        data-extra="${dataAttr({types: o.types, can_restore: !!o.can_restore,
          affected: (o.stopped_leaves || []).length + (o.cancelled_leaves || []).length})}">فتح الراحات</button>
    </div>
    <div class="sub">ساري من ${fmt(o.started_on)} — ${esc(o.reason)}</div>
    ${affectedList(o)}
  </div>`;
}

function historyRow(o) {
  return `<tr>
    <td>${typeChips(o.types)}</td>
    <td>${fmt(o.started_on)}</td><td>${fmt(o.lifted_on)}</td>
    <td class="wrap">${esc(o.reason)}${o.lift_reason ? `<div class="sub">الفتح: ${esc(o.lift_reason)}</div>` : ""}
      ${o.restored_count ? `<div class="sub"><span class="chip on">رجعت ${o.restored_count} راحة زي ما كانت</span></div>` : ""}</td>
    <td class="num">${(o.stopped_leaves || []).length}</td>
    <td class="num">${(o.cancelled_leaves || []).length}</td>
  </tr>`;
}

function render() {
  $("#suspActive").innerHTML = SUSP.active.length
    ? `<div class="susp-list">${SUSP.active.map(activeCard).join("")}</div>`
    : `<div class="empty">الراحات مفتوحة — مفيش أمر وقف ساري.</div>`;
  $("#suspHistory").innerHTML = tableBlock(
    ["الأنواع", "من", "اتفتح", "السبب", "اتوقفت", "اتلغت"],
    SUSP.history.map(historyRow), `عدد الأوامر: ${SUSP.history.length}`,
    "مفيش أوامر اتفتحت لسه.");
}

async function load() {
  const d = await bootstrap();
  if (!d) return;
  const s = await api("/api/rest-suspensions");
  if (!s) return;
  SUSP = s; render();
}

/* ---------- إنشاء أمر: خطوة ١ (الأنواع والسبب) ← خطوة ٢ (الراحات) ---------- */
const chosenTypes = () => $$("#suspendTypes [data-susp-type]").filter(cb => cb.checked).map(cb => cb.value);
const pickedBoxes = () => $$("#suspendCandidates [data-susp-leave]").filter(cb => cb.checked);

function showStep(n) {
  $("#suspStep1").classList.toggle("hidden", n !== 1);
  $("#suspStep2").classList.toggle("hidden", n !== 2);
  $("#suspStepTab1").classList.toggle("is-current", n === 1);
  $("#suspStepTab2").classList.toggle("is-current", n === 2);
}

function openSuspension() {
  const held = new Set(META.rest_suspension?.types || []);
  $("#suspendTypes").innerHTML = LEAVE_TYPES().map(t => `<label class="command-check${held.has(t) ? " is-disabled" : ""}">
    <input type="checkbox" data-susp-type value="${esc(t)}" ${held.has(t) ? "disabled" : ""}>
    <span class="command-check-icon" aria-hidden="true">${icon("check")}</span>
    ${esc(t)}${held.has(t) ? ` <small>موقوفة بالفعل</small>` : ""}
  </label>`).join("");
  $("#suspendReason").value = "";
  showStep(1);
  openModal("suspendModal");
}

$("#suspendTypes").addEventListener("change", () =>
  $$("#suspendTypes .command-check").forEach(card =>
    card.classList.toggle("is-on", card.querySelector("input").checked)));

/* العدّاد فوق القايمة بيتحدّث مع كل اختيار — ده اللي كان تأكيد المتصفح
   بيقوله بعد الضغط، بقى قدامك وانت بتختار. */
function updateCount() {
  const picked = pickedBoxes();
  const cancels = picked.filter(cb => cb.dataset.effect === "cancel").length;
  const stops = picked.length - cancels;
  const untouched = SUSP_CANDS.length - picked.length;
  $("#suspCount").innerHTML = SUSP_CANDS.length
    ? `<span class="chip rest">هيتوقف ${stops} راحة جارية</span>
       <span class="chip soon">هيتلغي ${cancels} قادمة</span>
       <span class="chip done">${untouched} هتفضل زي ما هي</span>`
    : "";
  $("#suspSubmit").textContent = picked.length
    ? `تنفيذ الأمر وإيقاف ${picked.length} راحة` : "تنفيذ أمر الوقف";
}

async function goToStep2() {
  const types = chosenTypes(), reason = $("#suspendReason").value.trim();
  if (!types.length) { showToast("اختار نوع راحة واحد على الأقل"); return }
  if (!reason) { showToast("لازم سبب مكتوب لأمر الوقف"); $("#suspendReason").focus(); return }

  const q = types.map(t => `type=${encodeURIComponent(t)}`).join("&");
  const r = await api(`/api/rest-suspensions/candidates?${q}`);
  if (!r) return;
  SUSP_CANDS = r.rows;
  $("#suspRecap").innerHTML = `الأنواع: <b>${types.map(esc).join("، ")}</b> — السبب: ${esc(reason)}`;

  const weeklyNote = types.includes("أسبوعية")
    ? `<p class="hint">الراحة الأسبوعية المحسوبة من يوم راحة الضابط (من غير سجل) بتقف لوحدها — مش محتاجة تتختار هنا.</p>`
    : "";
  $("#suspendAll").checked = false;
  $("#suspendAllWrap").classList.toggle("hidden", !r.rows.length);
  $("#suspendCandidates").innerHTML = weeklyNote + (r.rows.length
    ? `<p class="hint">اختار الراحات اللي عايز توقفها — اللي مش مختار بيفضل زي ما هو.</p>`
      + r.rows.map(c => `<label class="checkline susp-cand">
      <input type="checkbox" data-susp-leave value="${esc(c.leave_id)}" data-effect="${esc(c.effect)}">
      <span class="susp-cand-main"><b>${esc(c.role)}/ ${esc(c.name)}</b>
        <span class="chip w">${esc(c.type)}</span>
        <span class="chip ${c.state === "active" ? "rest" : "soon"}">${c.state === "active" ? "جارية" : "قادمة"}</span>
        <span class="sub">${fmt(c.start)} – ${fmt(c.end)} — ${c.effect === "cancel"
          ? "هتتلغي بالكامل" : `آخر يوم هيبقى ${fmt(c.new_end)}، يرجع ${fmt(c.return_date)}`}</span>
      </span>
    </label>`).join("")
    : `<p class="muted">مفيش راحات جارية أو قادمة مسجّلة من الأنواع دي — الأمر هيمنع التسجيل الجديد بس.</p>`);
  updateCount();
  showStep(2);
}

$("#suspNext").onclick = goToStep2;
$("#suspBack").onclick = () => showStep(1);
$("#suspendCandidates").addEventListener("change", updateCount);
$("#suspendAll").addEventListener("change", e => {
  $$("#suspendCandidates [data-susp-leave]").forEach(cb => { cb.checked = e.target.checked });
  updateCount();
});
// Enter في حقل السبب بيروح للخطوة التانية بدل ما يبعت الفورم كله
$("#suspendReason").addEventListener("keydown", e => {
  if (e.key === "Enter") { e.preventDefault(); goToStep2() }
});

$("#suspendForm").onsubmit = async e => {
  e.preventDefault();
  if ($("#suspStep2").classList.contains("hidden")) { goToStep2(); return }
  const out = await api("/api/rest-suspensions", jsonReq("POST", {
    types: chosenTypes(), reason: $("#suspendReason").value.trim(),
    stop_leave_ids: pickedBoxes().map(cb => cb.value)}));
  if (!out) return;
  closeModal("suspendModal");
  showToast("تم تنفيذ أمر الوقف");
  load();
};

/* ---------- فتح الراحات ---------- */
/* الرجوع للراحات زي ما كانت متاح بس لو الفتح في نفس يوم الوقف (وفيه راحات
   اتأثرت أصلًا) — بعد كده الضباط اتسكّنوا خلاص على أساس إن راحتهم اتوقفت. */
function syncLiftWarn() {
  const restore = $("#liftRestore").checked;
  $("#liftRestoreWrap").classList.toggle("is-on", restore);
  $("#liftWarn").innerHTML = restore
    ? `الراحات اللي اتوقفت بالأمر ده <b>هترجع لنهايتها الأصلية</b>، واللي اتلغت هتتسجّل تاني —
       كأن الأمر ماحصلش.`
    : `الراحات اللي اتوقفت بالأمر ده <b>مش هترجع</b> — الضباط بعد الفتح يتسكّنوا في راحة من جديد عادي.`;
}

ACTIONS.liftSuspension = (id, extra) => {
  $("#liftId").value = id;
  $("#liftWhat").innerHTML = `الأنواع: ${typeChips(extra.types)}`;
  $("#liftReason").value = "";
  const offer = extra.can_restore && extra.affected > 0;
  $("#liftRestoreWrap").classList.toggle("hidden", !offer);
  $("#liftRestore").checked = false;
  $("#liftRestoreHint").textContent = offer
    ? `${extra.affected} راحة — متاح لأن الفتح في نفس يوم الوقف` : "";
  syncLiftWarn();
  openModal("liftModal");
};
$("#liftRestore").addEventListener("change", syncLiftWarn);

$("#liftForm").onsubmit = async e => {
  e.preventDefault();
  const out = await api(`/api/rest-suspensions/${encodeURIComponent($("#liftId").value)}/lift`,
    jsonReq("POST", {reason: $("#liftReason").value.trim(), restore: $("#liftRestore").checked}));
  if (!out) return;
  closeModal("liftModal");
  showToast(out.restored_count ? `تم فتح الراحات ورجعت ${out.restored_count} راحة زي ما كانت`
                               : "تم فتح الراحات");
  load();
};

$("#newSuspensionBtn").onclick = openSuspension;
load();
