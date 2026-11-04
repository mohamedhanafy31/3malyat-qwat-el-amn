/* صفحة طباعة اليوميات — السيرفر هو مصدر حالة كل مجموعة، والصفحة بتسأله كل
   ثانية طول ما فيه طباعة شغالة أو علامة «تم» ظاهرة، وكل 10 ثواني غير كده. */
const ACTIVE_POLL_MS = 1000, IDLE_POLL_MS = 10000;
const STATUS = {
  idle: {label: "لسة", cls: "done"},
  queued: {label: "في الطابور", cls: "soon"},
  printing: {label: "بيتم الطباعة", cls: "w"},
  done: {label: "تم", cls: "on"},
  failed: {label: "فشل", cls: "err"},
};
const DOC_STATE = {
  missing: {label: "ناقص", cls: "err"},
  edited: {label: "معدّل يدويًا", cls: "soon"},
  draft: {label: "مسودة", cls: "soon"},
  ready: {label: "جاهز", cls: "on"},
};
let PRINT = null, DAY = null, pollTimer = null, lastPaint = "", pendingIds = [];

const isLive = () => (PRINT?.collections || []).some(c => ["queued", "printing", "done"].includes(c.status.state));

function docChip(kind, status) {
  const state = status.docs[kind];
  const cls = state && STATUS[state] ? STATUS[state].cls : "done";
  const mark = state === "done" ? `${icon("check")} ` : "";
  const hint = state && STATUS[state] ? STATUS[state].label : "";
  return `<span class="chip ${cls}"${hint ? ` title="${esc(hint)}"` : ""}>${mark}${esc(PRINT.kinds[kind])}</span>`;
}

function statusBadge(status) {
  const info = STATUS[status.state];
  if (!info) return "";                 // «تم» خلصت مدتها فاختفت
  const progress = status.state === "printing" ? ` ${status.done + 1}/${status.total}` : "";
  const mark = status.state === "done" ? `${icon("check")} ` : "";
  return `<span class="chip ${info.cls} print-status" data-state="${esc(status.state)}">${mark}${info.label}${progress}</span>`;
}

function card(c) {
  const busy = ["queued", "printing"].includes(c.status.state);
  const errors = c.status.errors.map(e => `<li>${esc(e)}</li>`).join("");
  return `<article class="print-card" data-id="${esc(c.id)}">
    <header class="print-card-head"><h3>${esc(c.label)}</h3>${statusBadge(c.status)}</header>
    <div class="print-card-docs">${c.kinds.map(k => docChip(k, c.status)).join("")}</div>
    ${c.status.stuck ? `<p class="hint print-warn">الملف واخد وقت طويل. غالبًا Word مستني رد في نافذة مخفية: راجع جهاز المكتب.</p>` : ""}
    ${errors ? `<ul class="print-errors">${errors}</ul>` : ""}
    <div class="print-card-actions">
      <button type="button" class="mini ok" data-action="printOne" data-id="${esc(c.id)}"
        ${PRINT.can_print && !busy ? "" : "disabled"}>طباعة</button>
      <button type="button" class="mini" data-action="editCollection" data-id="${esc(c.id)}">تعديل</button>
      <button type="button" class="mini bad" data-action="deleteCollection" data-id="${esc(c.id)}"
        ${busy ? "disabled" : ""}>حذف</button>
    </div>
  </article>`;
}

function render() {
  const signature = JSON.stringify(PRINT);
  if (signature === lastPaint) return;
  lastPaint = signature;
  const docs = Object.keys(PRINT.kinds).map(kind => {
    const info = DOC_STATE[PRINT.documents[kind].state];
    return `<span class="chip ${info.cls}">${esc(PRINT.kinds[kind])}: ${info.label}</span>`;
  }).join("");
  $("#printDocs").innerHTML = docs + (PRINT.updating ? `<span class="chip w">الملفات بتتحدّث…</span>` : "");
  $("#printGrid").innerHTML = PRINT.collections.length
    ? PRINT.collections.map(card).join("")
    : emptyState({icon: "inbox", title: "مفيش مجموعات", hint: "ضيف مجموعة جديدة واختار يومياتها."});
  $("#printerLine").textContent = PRINT.can_print ? `الطابعة: ${PRINT.printer || "الافتراضية"}` : PRINT.block_reason;
  $("#printAllBtn").disabled = !PRINT.can_print || !PRINT.collections.length;
}

function schedule() {
  clearTimeout(pollTimer);
  pollTimer = setTimeout(poll, isLive() || PRINT?.updating ? ACTIVE_POLL_MS : IDLE_POLL_MS);
}

/* fetch مباشر: فشل سؤال دوري مايستاهلش توست كل ثانية. */
async function poll() {
  const day = DAY;
  if (!document.hidden) {
    try {
      const r = await fetch(`/api/daily-print/${day}`);
      if (r.ok && day === DAY) { PRINT = await r.json(); render(); }
    } catch (err) { /* المحاولة الجاية هتكفي */ }
  }
  schedule();
}

async function loadDay(day) {
  const out = await api(`/api/daily-print/${day}`, {noLoader: true});
  if (!out) return;
  DAY = day; PRINT = out; lastPaint = "";
  $("#dutyDate").value = day;
  setPageDay(day);
  render();
  schedule();
}

function openPrint(ids) {
  pendingIds = ids;
  const chosen = PRINT.collections.filter(c => ids.includes(c.id));
  const kinds = new Set(chosen.flatMap(c => c.kinds));
  const count = state => [...kinds].filter(k => PRINT.documents[k].state === state).map(k => PRINT.kinds[k]);
  const warnings = [];
  if (count("missing").length) warnings.push(`ملفات ناقصة (هتتولّد لو اليوم فيه بيانات): ${count("missing").join("، ")}`);
  if (count("edited").length) warnings.push(`معدّلة يدويًا وهتتطبع زي ما هي: ${count("edited").join("، ")}`);
  if (PRINT.updating) warnings.push("الملفات بتتحدّث دلوقتي، والطباعة هتستنى لما تخلص.");
  const hasDraft = kinds.has("service_order") && PRINT.documents.service_order.state === "draft";
  $("#printSummary").innerHTML = `<p><b>${esc(dayLabel(DAY))}</b> — الطابعة: ${esc(PRINT.printer || "الافتراضية")}</p>
    <p>${chosen.map(c => esc(c.label)).join("، ")}</p>
    ${warnings.map(w => `<p class="hint print-warn">${esc(w)}</p>`).join("")}
    ${hasDraft ? `<p class="hint print-warn">أمر الخدمة لسه مسودة ماتعدلتش، ومش هيتطبع إلا لو اخترت ده تحت.</p>` : ""}`;
  $("#printCopies").value = 1;
  $("#printCopies").max = PRINT.max_copies;
  $("#printDraft").checked = false;
  $("#printDraftWrap").classList.toggle("hidden", !hasDraft);
  openModal("printModal");
}

$("#printForm").onsubmit = async e => {
  e.preventDefault();
  const out = await api("/api/daily-print/jobs", jsonReq("POST", {
    day: DAY, collection_ids: pendingIds, copies: Number($("#printCopies").value),
    include_draft: $("#printDraft").checked,
  }));
  if (!out) return;
  closeModal("printModal", true);
  showToast(`اتضاف للطابور: ${out.total} ملف`);
  poll();
};

$("#printAllBtn").onclick = () => {
  const free = PRINT.collections.filter(c => !["queued", "printing"].includes(c.status.state));
  if (free.length) openPrint(free.map(c => c.id));
  else showToast("كل المجموعات في الطابور بالفعل.");
};
ACTIONS.printOne = id => openPrint([id]);

function openCollection(item) {
  $("#collectionTitle").textContent = item ? "تعديل المجموعة" : "مجموعة جديدة";
  $("#collectionId").value = item?.id || "";
  $("#collectionLabel").value = item?.label || "";
  const selected = new Set(item?.kinds || []);
  $("#collectionKinds").innerHTML = Object.entries(PRINT.kinds).map(([kind, label]) =>
    `<label><input type="checkbox" value="${esc(kind)}" ${selected.has(kind) ? "checked" : ""}> ${esc(label)}</label>`).join("");
  openModal("collectionModal");
}
$("#newCollectionBtn").onclick = () => openCollection(null);
ACTIONS.editCollection = id => openCollection(PRINT.collections.find(c => c.id === id));
ACTIONS.deleteCollection = async id => {
  const item = PRINT.collections.find(c => c.id === id);
  const ok = await confirmDialog({title: "حذف المجموعة", body: `هتتحذف مجموعة «${item.label}». مش هيتمسح أي ملف.`,
                                  confirmLabel: "حذف", danger: true});
  if (!ok) return;
  if (await api(`/api/print-collections/${encodeURIComponent(id)}`, {method: "DELETE"})) {
    showToast("اتحذفت المجموعة");
    loadDay(DAY);
  }
};

$("#collectionForm").onsubmit = async e => {
  e.preventDefault();
  const id = $("#collectionId").value;
  const body = {label: $("#collectionLabel").value.trim(),
                kinds: [...$$("#collectionKinds input:checked")].map(input => input.value)};
  const out = await api(id ? `/api/print-collections/${encodeURIComponent(id)}` : "/api/print-collections",
                        jsonReq(id ? "PATCH" : "POST", body));
  if (!out) return;
  closeModal("collectionModal", true);
  showToast("اتحفظت المجموعة");
  loadDay(DAY);
};

const shiftDay = n => loadDay(addDays($("#dutyDate").value || curDate(), n));
$("#dayPrev").onclick = () => shiftDay(-1);
$("#dayNext").onclick = () => shiftDay(1);
$("#dayToday").onclick = () => loadDay(curDate());
$("#dutyDate").onchange = () => loadDay($("#dutyDate").value);

(async () => {
  if (await bootstrap()) loadDay(workDay());
})();
