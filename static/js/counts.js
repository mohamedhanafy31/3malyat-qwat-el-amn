/* اعداد الخدمات — القالب الثابت (أساسية صباحية/ليلية + طوارئ متكررة) يتفرّد
   نسخة لكل يوم بمجرد أول تعديل.

   بلوك الطوارئ اليومي مالوش سجل هنا: بيتقرا مباشرة من قسم «الخدمات الطارئة»
   في اليومية التفصيلية، فأي خدمة طارئة بتتكتب هناك بتظهر هنا على طول. خانة
   العدد اللي جنب كل خدمة بتكتب على صف التكليف نفسه — نفس الحقل اللي خانة
   الخدمة على اللوحة بتكتبه، فالرقم واحد مهما اتعدّل من فين.

   نفس المبدأ لأي قسم مخصّص المشغّل كتبه بإيده على اللوحة لليوم ده بس (زي
   «خدمات مباراة المصري») — بيوصل هنا في `VIEW.custom_sections` وبياخد
   بلوك مستقل بنفس شكل بلوك الطوارئ بالظبط. */
let DAY = null, MODE = "day", VIEW = null;

/* ---------- العرض ---------- */

/* سطر الإجمالي تحت كل بلوك — زي «المجموع» في آخر كل عمود في ورقة الإكسل.
   رقمين مختلفين: عدد الخدمات (صفوف) وعدد المجندين (مجموع الأرقام). */
function blockTotal(services, conscripts) {
  return `<div class="blk-total">
    <span>الإجمالي</span>
    <span class="blk-total-bits">
      <span><b>${services}</b> خدمة</span>
      <span><b>${conscripts}</b> مجند</span>
    </span></div>`;
}

/* التسليح بيتحدد من هنا للأساسية بس — الطوارئ (متكررة أو يومية) بتاخده
   من اليومية التفصيلية أصلًا (خانة التسليح على صف الخدمة في اللوحة). */
const WEAPON_BLOCKS = new Set(["صباحية", "ليلية"]);
const cardTable = (head, rows) => `<div class="mtable-wrap">${mtable(head, rows)}</div>`;

function editableCard(label, block, rows) {
  const showWeapon = WEAPON_BLOCKS.has(block);
  const head = ["الخدمة", "الجهة", ...(showWeapon ? ["التسليح"] : []), "عدد المجندين", "الإجراء"];
  const body = rows.length
    ? cardTable(head, rows.map(e => `
      <tr>
        <td class="name">${esc(e.name) || "<span class='muted'>—</span>"}</td>
        <td>${esc(e.party) || "<span class='muted'>—</span>"}</td>
        ${showWeapon ? `<td>${esc(e.weapon) || "<span class='muted'>—</span>"}</td>` : ""}
        <td><strong>${e.count}</strong></td>
        <td class="col-actions"><div class="actions">
          <button class="mini" data-action="openCount" data-id="${esc(e.id)}"
            data-extra="${dataAttr({block})}">تعديل</button>
          ${rowMenu([{action: "deleteCount", id: e.id, extra: {name: e.name},
            label: "حذف", danger: true}])}
        </div></td>
      </tr>`))
    : emptyState({compact: true, title: "لا توجد خدمات في هذا القسم", hint: "استخدم زر «إضافة» في رأس القسم."});
  const total = rows.reduce((n, e) => n + (e.count || 0), 0);
  return `<div class="mcard">
    <h3>${esc(label)}<span class="mcount">${rows.length}</span>
      <button class="mini on-dark" data-action="openCount" data-extra="${dataAttr({block})}">${icon("plus")} إضافة</button>
    </h3>${body}${blockTotal(rows.length, total)}</div>`;
}

/* بلوك محسوب من اللوحة — لبلوك الطوارئ ولأي قسم مخصّص بنفس الشكل بالظبط.
   `emptyText` بيفرّق الرسالة بين «مفيش طوارئ النهاردة» و«مفيش صفوف لسه
   في القسم ده» لأن القسم المخصّص أصلًا اسمه معروف مسبقًا (مختلف عن
   «الخدمات الطارئة» الثابت). */
function boardCountCard(label, rows, emptyText) {
  const locked = VIEW?.locked;
  const body = rows.length
    ? cardTable(["الخدمة", "الفترة", "الجهة", "القوام على اللوحة", "عدد المجندين"], rows.map(r => `
      <tr class="${r.needs_count ? "vacant" : ""}">
        <td class="name">${esc(r.name) || "<span class='muted'>بدون اسم</span>"}</td>
        <td>${esc(r.shift) || "-"}</td>
        <td>${esc(r.party) || "<span class='muted'>—</span>"}</td>
        <td class="wrap">${esc(r.strength) || "<span class='muted'>—</span>"}</td>
        <td><input class="board-count" type="number" min="0" value="${r.count}"
             data-id="${esc(r.assignment_id)}" ${locked ? "disabled" : ""}
             aria-label="عدد مجندين ${esc(r.name)}"></td>
      </tr>`))
    : emptyState({compact: true, title: emptyText});
  const missing = rows.filter(r => r.needs_count).length;
  const note = locked
    ? "اليوم ده مقفول — افتحه فتح استثنائي من اليومية التفصيلية عشان تعدّل الأعداد"
    : missing
      ? `${missing} خدمة لسه من غير عدد مجندين — اكتب الرقم في الخانة والصف هيتظبط`
      : "الأعداد بتتخزّن على صف الخدمة في اليومية التفصيلية — نفس الرقم في المكانين";
  const total = rows.reduce((n, r) => n + (r.count || 0), 0);
  return `<div class="mcard special">
    <h3>${esc(label)}<span class="mcount">${rows.length}</span></h3>
    <div class="sub-head">${esc(note)}</div>
    ${body}${blockTotal(rows.length, total)}</div>`;
}

function render() {
  const isTemplate = MODE === "template";
  $("#btnModeToggle").innerHTML = isTemplate
    ? `${icon("arrow-back")} رجوع لعرض اليوم`
    : `${icon("edit")} تعديل القالب الدائم`;
  ["dayPrev", "dayNext", "dayToday", "dutyDate", "btnReset"].forEach(id => {
    $("#" + id).classList.toggle("hidden", isTemplate);
  });
  if (!VIEW) { $("#cntBlocks").innerHTML = skeleton("cards", 4); return }

  if (isTemplate) {
    $("#cntSeedBanner").classList.toggle("hidden", VIEW.seeded);
    $("#cntTotals").innerHTML = "";
    const am = VIEW.entries.filter(e => e.block === "صباحية");
    const pm = VIEW.entries.filter(e => e.block === "ليلية");
    const rec = VIEW.entries.filter(e => e.block === "طوارئ");
    $("#cntBlocks").innerHTML = [
      editableCard("القالب الدائم — أساسية صباحية", "صباحية", am),
      editableCard("القالب الدائم — أساسية ليلية", "ليلية", pm),
      editableCard("القالب الدائم — طوارئ متكررة", "طوارئ", rec),
    ].join("");
    grandTotal(VIEW.entries.length, VIEW.entries.reduce((n, e) => n + (e.count || 0), 0),
               "إجمالي القالب الدائم");
    return;
  }

  const totalEntries = VIEW.basic_am.length + VIEW.basic_pm.length + VIEW.recurring.length;
  $("#cntSeedBanner").classList.toggle("hidden", !(VIEW.from_template && !totalEntries));
  $("#btnReset").classList.toggle("hidden", VIEW.from_template);
  const t = VIEW.totals;
  const customSections = VIEW.custom_sections || [];
  const extraStat = t.custom
    ? `<div class="stat"><span>أقسام إضافية</span><strong>${t.custom}</strong></div>`
    : "";
  $("#cntTotals").innerHTML = `<div class="stats">
    <div class="stat"><span>أساسية صباحية</span><strong>${t.basic_am}</strong></div>
    <div class="stat"><span>أساسية ليلية</span><strong>${t.basic_pm}</strong></div>
    <div class="stat stat-accent-orange"><span>الطوارئ</span><strong>${t.emergency}</strong></div>
    ${extraStat}
    <div class="stat"><span>الإجمالي الكلي</span><strong>${t.grand_total}</strong></div>
  </div>`;
  $("#cntBlocks").innerHTML = [
    editableCard("الخدمات الأساسية — صباحية", "صباحية", VIEW.basic_am),
    editableCard("الخدمات الأساسية — ليلية", "ليلية", VIEW.basic_pm),
    editableCard("طوارئ متكررة", "طوارئ", VIEW.recurring),
    boardCountCard("طوارئ اليوم — من اليومية التفصيلية", VIEW.emergency,
      "لا توجد خدمات طارئة في اليومية التفصيلية لهذا اليوم — أي خدمة تُضاف في قسم «الخدمات الطارئة» تظهر هنا تلقائيًا"),
    ...customSections.map(sec => boardCountCard(sec.name, sec.rows,
      `لا توجد صفوف بعد — أضف خدمة في قسم «${sec.name}» باليومية التفصيلية وستظهر هنا تلقائيًا`)),
  ].join("");
  grandTotal(VIEW.services.total, t.grand_total, `إجمالي خدمات يوم ${dayName(DAY)} ${fmt(DAY)}`);
}

/* الإجمالي الكلي تحت خالص — آخر حاجة في الصفحة زي «إجمالي اعداد الخدمات»
   في آخر سطر في ورقة الإكسل. موجود فوق كمان في شريط الإحصائيات، وده
   مقصود: اللي بيملا الورقة شايفه وهو بيكتب، واللي بيطبعها شايفه في آخرها. */
function grandTotal(services, conscripts, label) {
  $("#cntGrand").innerHTML = `
    <div class="grand-label">${esc(label)}</div>
    <div class="grand-bits">
      <span><b>${services}</b> خدمة</span>
      <span class="grand-main"><b>${conscripts}</b> مجند</span>
    </div>`;
}

/* خانة العدد جوّه بلوك الطوارئ أو أي قسم مخصّص. المستمع على الحاوية نفسها
   (مش على كل خانة) عشان render() بيستبدل كل المحتوى — الربط مرة واحدة
   وخلاص. */
$("#cntBlocks").addEventListener("change", async e => {
  const box = e.target.closest(".board-count");
  if (!box) return;
  const count = Math.max(0, parseInt(box.value) || 0);
  const v = await api(`/api/counts/${DAY}/board/${encodeURIComponent(box.dataset.id)}`,
                      jsonReq("PATCH", {count}));
  if (!v) return;
  VIEW = v; showToast("تم حفظ العدد"); render();
});

/* ---------- تحميل ---------- */
async function loadDay(day) {
  const v = await api(`/api/counts/${day}`);
  if (!v) return;
  VIEW = v; DAY = day; MODE = "day"; $("#dutyDate").value = day; setPageDay(day); render();
}
async function loadTemplateView() {
  const v = await api(`/api/counts/template`);
  if (!v) return;
  VIEW = v; MODE = "template"; render();
}

const shiftDay = n => loadDay(addDays($("#dutyDate").value || curDate(), n));
$("#dayPrev").onclick = () => shiftDay(-1);
$("#dayNext").onclick = () => shiftDay(1);
$("#dayToday").onclick = () => loadDay(curDate());
$("#dutyDate").onchange = () => loadDay($("#dutyDate").value);
$("#btnModeToggle").onclick = () => (MODE === "day" ? loadTemplateView() : loadDay(DAY || curDate()));

$("#btnReset").onclick = async () => {
  if (!(await confirmDialog({
    title: "استرجاع القالب الافتراضي",
    body: `ستُحذف جميع التعديلات الخاصة بيوم ${fmt(DAY)} ويُسترجع القالب الافتراضي.`,
    confirmLabel: "استرجاع القالب",
    danger: true,
  }))) return;
  const v = await api(`/api/counts/${DAY}/reset`, {method: "POST"});
  if (!v) return;
  VIEW = v; showToast("تم الاسترجاع"); render();
};
$("#btnSeed").onclick = async () => {
  if (!(await api("/api/counts/template/seed", {method: "POST"}))) return;
  showToast("تم تحميل القالب المبدئي");
  MODE === "template" ? loadTemplateView() : loadDay(DAY);
};

/* ---------- نموذج الصف ---------- */
function currentPool() {
  if (MODE === "template") return VIEW.entries;
  return [...VIEW.basic_am, ...VIEW.basic_pm, ...VIEW.recurring];
}

function syncWeaponVisibility() {
  $("#cnWeaponWrap").classList.toggle("hidden", !WEAPON_BLOCKS.has($("#cnBlock").value));
}
$("#cnBlock").onchange = syncWeaponVisibility;

function openCount(id, extra) {
  const row = id ? currentPool().find(e => e.id === id) : null;
  $("#cnId").value = id || "";
  $("#cnSource").value = MODE;
  $("#countTitle").textContent = row ? "تعديل خدمة" : "إضافة خدمة";
  $("#cnBlock").value = row?.block || extra?.block || "صباحية";
  $("#cnName").value = row?.name || "";
  $("#cnParty").value = row?.party || "";
  $("#cnCount").value = row?.count ?? 0;
  $("#cnWeapon").value = row?.weapon || "";
  syncWeaponVisibility();
  openModal("countModal");
}
ACTIONS.openCount = (id, extra) => openCount(id || null, extra);
ACTIONS.deleteCount = async (id, extra) => {
  if (!(await confirmDialog({
    title: "حذف الخدمة",
    body: `ستُحذف خدمة «${extra.name}» نهائيًا ولا يمكن التراجع عن ذلك.`,
    confirmLabel: "حذف الخدمة",
    danger: true,
  }))) return;
  const base = MODE === "template" ? "/api/counts/template/entries" : `/api/counts/${DAY}/entries`;
  if (await api(`${base}/${encodeURIComponent(id)}`, {method: "DELETE"})) {
    showToast("تم الحذف");
    MODE === "template" ? loadTemplateView() : loadDay(DAY);
  }
};

$("#countForm").onsubmit = async e => {
  e.preventDefault();
  const body = {
    block: $("#cnBlock").value,
    name: $("#cnName").value.trim(),
    party: $("#cnParty").value.trim(),
    count: parseInt($("#cnCount").value) || 0,
    weapon: WEAPON_BLOCKS.has($("#cnBlock").value) ? $("#cnWeapon").value.trim() : "",
  };
  const id = $("#cnId").value;
  const source = $("#cnSource").value;
  const base = source === "template" ? "/api/counts/template/entries" : `/api/counts/${DAY}/entries`;
  const out = id
    ? await api(`${base}/${encodeURIComponent(id)}`, jsonReq("PATCH", body))
    : await api(base, jsonReq("POST", body));
  if (!out) return;
  closeModal("countModal", true); showToast(id ? "تم حفظ التعديلات" : "تمت الإضافة");
  source === "template" ? loadTemplateView() : loadDay(DAY);
};

async function load() {
  const d = await bootstrap();
  if (!d) return;
  loadDay(curDate());
}
load();
