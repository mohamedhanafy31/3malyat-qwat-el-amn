/* لوحة التشغيل المختصرة — قابلة للتعديل الحر */
let MATCH = null, MATCH_DAY = null, OFFICERS = [], ENTRY_TAGS = [];
const CATEGORY_OCCASIONAL = "الخدمات الطارئة";
const CATEGORY_TARGETS = "الأهداف";   // هدف ثابت طول اليوم — مالوش صباحية/ليلية

/* ---------- العرض ---------- */
const reqBadges = reqs => (reqs || []).map(r =>
  `<span class="chip w">${esc(r.label)}${r.count ? " ×" + r.count : ""}${r.note ? " (" + esc(r.note) + ")" : ""}</span>`).join(" ");
const tagBadges = tags => (tags || []).map(t => `<span class="chip soon">#${esc(t)}</span>`).join(" ");

function entryRow(cat, e, extraTags) {
  const reqCell = reqBadges(e.requirements) + (extraTags?.length ? " " + tagBadges(extraTags) : "");
  return `<tr>
    <td class="name">${esc(e.service)}${e.shift ? `<div class="sub">${esc(e.shift)}</div>` : ""}</td>
    <td>${e.officer_name ? esc(e.officer_name) : "<span class='muted'>—</span>"}</td>
    <td class="wrap">${reqCell}</td>
    <td class="wrap">${esc(e.note) || "<span class='muted'>—</span>"}</td>
    <td><div class="actions">
      <button class="mini" data-action="openEntry" data-id="${esc(e.id)}" data-extra="${dataAttr({category: cat})}">تعديل</button>
      <button class="mini bad" data-action="deleteEntry" data-id="${esc(e.id)}" data-extra="${dataAttr({name: e.service})}">حذف</button>
    </div></td></tr>`;
}
const HEAD = ["الخدمة", "الضابط / المسؤول", "الاحتياجات", "ملاحظات", "الإجراء"];

function entryCard(cat) {
  const table = cat.entries.length
    ? mtable(HEAD, cat.entries.map(e => entryRow(cat.name, e)))
    : `<div class="mempty">لا توجد خدمات — اضغط «إضافة» فوق</div>`;
  return `<div class="mcard">
    <h3>${esc(cat.name)}<span class="mcount">${cat.entries.length}</span>
      <button class="mini ok" data-action="openEntry" data-extra="${dataAttr({category: cat.name})}">＋ إضافة</button></h3>
    ${table}</div>`;
}
function specialCard(g) {
  const table = mtable(HEAD, g.entries.map(e => entryRow(e.category, e, e.tags.filter(t => t !== g.tag))));
  return `<div class="mcard special">
    <h3>#${esc(g.tag)}<span class="mcount">${g.entries.length}</span>
      <span class="of-cat">ضمن «${esc(g.of_category)}»</span>
      <button class="mini ok" data-action="openSpecialEntry" data-extra="${dataAttr({tag: g.tag, category: g.of_category})}">＋ إضافة</button></h3>
    ${table}</div>`;
}

function render() {
  const wrap = $("#matchBoard");
  if (!MATCH) { wrap.innerHTML = `<div class="empty">جارٍ التحميل...</div>`; return }
  const b = MATCH;

  const restHtml = mtable(["الضابط","النوع","من يوم","إلى يوم","العودة"], b.rests.map(x =>
    `<tr><td class="name">${esc(x.name)}</td>
     <td><span class="chip ${x.type === 'شهرية' ? 'm' : x.type === 'نصف شهرية' ? 'h' : 'w'}">${esc(x.type)}</span></td>
     <td>${x.start ? fmt(x.start) : "-"}</td><td>${x.end ? fmt(x.end) : "-"}</td>
     <td>${x.return_date ? fmt(x.return_date) : "-"}</td></tr>`));
  const taqHtml = mtable(["الضابط","العمل قبل التقصيرة"], b.taqseeras.map(x =>
    `<tr><td class="name">${esc(x.name)}</td><td class="wrap">${esc(x.note)}</td></tr>`));
  const outHtml = mtable(["الضابط","السبب","التفاصيل"], b.outsiders.map(x =>
    `<tr><td class="name">${esc(x.name)}</td><td><span class="chip taq">${esc(x.reason)}</span></td>
     <td class="wrap">${esc(x.note)}</td></tr>`));
  const netHtml = mtable(["الضابط","العمل بالإدارة"], b.net.map(x =>
    `<tr><td class="name">${esc(x.name)}</td><td class="wrap">${esc(x.post) || "<span class='muted'>—</span>"}</td></tr>`));

  const statusCards = [
    ["الراحات", b.rests.length, restHtml], ["التقصيرات", b.taqseeras.length, taqHtml],
    ["الخوارج", b.outsiders.length, outHtml], ["عمل بالإدارة (الصافي)", b.net.length, netHtml],
  ].map(([t, n, h]) => `<div class="mcard"><h3>${t}<span class="mcount">${n}</span></h3>${n ? h : '<div class="mempty">لا يوجد</div>'}</div>`);

  wrap.innerHTML = `
    <div class="match-head">
      <span class="muted">لوحة التشغيل المختصرة — ${dayName(b.date)} ${fmt(b.date)}</span>
    </div>
    <div class="match-grid">${b.categories.map(entryCard).join("")}${statusCards.join("")}</div>
    <div class="special-head">
      <div><h3>الخدمات الخاصة</h3>
      <p class="hint" style="margin:0">خدمات مرتبطة بحدث معيّن (مباراة، خطة انتشار...) — منفصلة هنا للمتابعة،
        لكنها تفضل منطقيًا ضمن تصنيفها الأصلي (غالبًا الخدمات الطارئة).</p></div>
      <button class="mini ok" data-action="openSpecialEntry" data-extra="${dataAttr({tag: "", category: CATEGORY_OCCASIONAL})}">＋ حدث خاص جديد</button>
    </div>
    ${b.special.length ? `<div class="match-grid special-grid">${b.special.map(specialCard).join("")}</div>`
      : `<div class="mempty" style="margin:0 18px 20px">لا توجد خدمات خاصة اليوم.</div>`}`;
}

/* ---------- نموذج الخانة ---------- */
function toggleEnShift() {
  const noShift = $("#enCategory").value.trim() === CATEGORY_TARGETS;
  $("#enShiftWrap").classList.toggle("hidden", noShift);
  if (noShift) $("#enShift").value = "";
}
function reqRow(r) {
  return `<div class="req-row">
    <input class="req-label" placeholder="النوع (ضابط/فرد/مج/وحدة...)" value="${esc(r.label || "")}">
    <input class="req-count" type="number" min="0" placeholder="العدد" value="${r.count || ""}">
    <input class="req-note" placeholder="ملاحظة (قتالية/فض/رياضي...)" value="${esc(r.note || "")}">
    <button type="button" class="mini bad" data-action="removeReqRow">حذف</button>
  </div>`;
}
function renderTagChips() {
  $("#tagChips").innerHTML = ENTRY_TAGS.map((t, i) =>
    `<span class="chip soon">#${esc(t)} <a data-action="removeTag" data-id="${i}">×</a></span>`).join(" ");
}
function findEntry(id) {
  for (const c of MATCH.categories) { const e = c.entries.find(x => x.id === id); if (e) return e }
  for (const g of MATCH.special) { const e = g.entries.find(x => x.id === id); if (e) return e }
  return null;
}
function openEntry(category, entryId, presetTags) {
  const e = entryId ? findEntry(entryId) : null;
  $("#enId").value = entryId || "";
  $("#entryTitle").textContent = e ? "تعديل خانة" : `إضافة إلى «${category}»`;
  $("#categoryList").innerHTML = (META.board_categories || []).map(x => `<option value="${esc(x)}">`).join("");
  $("#officerList").innerHTML = OFFICERS.map(o => `<option value="${esc(o.name)}">`).join("");
  $("#tagList").innerHTML = (META.service_tags || []).map(x => `<option value="${esc(x)}">`).join("");
  fillSelect($("#enShift"), [["", "— بدون —"], ...SHIFTS().map(x => [x, x])]);

  $("#enCategory").value = e ? e.category : category;
  $("#enService").value = e ? e.service : "";
  $("#enShift").value = e ? e.shift : "";
  $("#enOfficer").value = e?.officer_name || "";
  $("#enOfficer").dataset.officerId = e?.officer_id || "";
  $("#enNote").value = e ? e.note : "";
  toggleEnShift();
  $("#reqRows").innerHTML = (e?.requirements || []).map(reqRow).join("");
  ENTRY_TAGS = [...(e ? e.tags : presetTags) || []]; renderTagChips();
  openModal("entryModal");
}

ACTIONS.openEntry = (id, extra) => openEntry(extra.category, id || null);
ACTIONS.openSpecialEntry = (id, extra) => openEntry(extra.category, null, extra.tag ? [extra.tag] : []);
ACTIONS.deleteEntry = async (id, extra) => {
  if (!confirm(`حذف «${extra.name}» من اليومية؟`)) return;
  if (await api(`/api/board/${MATCH_DAY}/entries/${encodeURIComponent(id)}`, {method: "DELETE"})) {
    showToast("تم الحذف"); loadDay(MATCH_DAY);
  }
};
ACTIONS.removeTag = i => { ENTRY_TAGS.splice(Number(i), 1); renderTagChips() };
ACTIONS.removeReqRow = (id, extra, el) => el.closest(".req-row").remove();

$("#addReqRow").onclick = () => $("#reqRows").insertAdjacentHTML("beforeend", reqRow({}));
$("#enCategory").addEventListener("input", toggleEnShift);
$("#enOfficer").addEventListener("input", () => {
  const o = OFFICERS.find(o => o.name === $("#enOfficer").value);
  $("#enOfficer").dataset.officerId = o ? o.id : "";
});
$("#enTags").addEventListener("keydown", e => {
  if (e.key !== "Enter") return;
  e.preventDefault();
  const v = $("#enTags").value.trim();
  if (v && !ENTRY_TAGS.includes(v)) { ENTRY_TAGS.push(v); renderTagChips() }
  $("#enTags").value = "";
});
$("#entryForm").onsubmit = async e => {
  e.preventDefault();
  const requirements = $$("#reqRows .req-row").map(r => ({
    label: r.querySelector(".req-label").value.trim(),
    count: parseInt(r.querySelector(".req-count").value) || 0,
    note: r.querySelector(".req-note").value.trim(),
  })).filter(r => r.label);
  const body = {
    category: $("#enCategory").value.trim(), service: $("#enService").value.trim(),
    shift: $("#enShift").value, officer_id: $("#enOfficer").dataset.officerId || "",
    officer_name: $("#enOfficer").value.trim(), requirements, tags: ENTRY_TAGS,
    note: $("#enNote").value.trim(),
  };
  const id = $("#enId").value;
  const out = id
    ? await api(`/api/board/${MATCH_DAY}/entries/${encodeURIComponent(id)}`, jsonReq("PATCH", body))
    : await api(`/api/board/${MATCH_DAY}/entries`, jsonReq("POST", body));
  if (!out) return;
  closeModal("entryModal"); showToast(id ? "تم حفظ التعديلات" : "تمت الإضافة");
  loadDay(MATCH_DAY);
};

/* ---------- تنقّل الأيام ---------- */
async function loadDay(day) {
  const b = await api(`/api/board/${day}`); if (!b) return;
  MATCH = b; MATCH_DAY = day; $("#dutyDate").value = day; render();
}
const shiftDay = n => loadDay(addDays($("#dutyDate").value || curDate(), n));
$("#dayPrev").onclick = () => shiftDay(-1);
$("#dayNext").onclick = () => shiftDay(1);
$("#dayToday").onclick = () => loadDay(curDate());
$("#dutyDate").onchange = () => loadDay($("#dutyDate").value);

/* تنبيه تسليم واستلام: مين هيبدأ راحته بكرة (تقصيرته النهاردة) وكان بيشتغل إيه،
   عشان يتكلّف بديل — من غير ما ننسخ التكليفات تلقائي. */
$("#dayTomorrow").onclick = async () => {
  const today = curDate(), tmr = addDays(today, 1);
  await loadDay(tmr);
  const boot = await api("/api/bootstrap/dashboard");
  const leaving = (boot?.alerts || []).filter(a => a.taqseera_date === today);
  if (!leaving.length) return;
  const todayBoard = await api(`/api/board/${today}`);
  const rows = leaving.map(a => {
    let service = "بدون خدمة مسجلة النهاردة";
    if (todayBoard) for (const cat of todayBoard.categories) {
      const e = cat.entries.find(x => x.officer_id === a.id);
      if (e) { service = `${e.service}${e.shift ? " (" + e.shift + ")" : ""}`; break }
    }
    return `<li><span class="a-name">${esc(a.role)} / ${esc(a.name)}</span>
      <span class="a-mid">في راحة (${esc(a.type)}) بداية من بكرة</span>
      <span class="a-rest">كان بيشتغل: ${esc(service)}</span></li>`;
  });
  $("#matchBoard").insertAdjacentHTML("afterbegin", `<div class="alert-card">
    <div class="alert-head"><span class="alert-ico">↷</span><strong>تسليم واستلام بكرة</strong>
      <span class="muted">${leaving.length} ضابط هيبدأ راحته بكرة — محتاجين تكليف بديل على خدمتهم</span></div>
    <ul class="alert-list">${rows.join("")}</ul></div>`);
};

async function load() {
  const d = await bootstrap();
  if (!d) return;
  OFFICERS = d.officer_index || [];
  const days = d.board_days || [];
  loadDay(days.includes(curDate()) ? curDate() : (days[days.length - 1] || curDate()));
}
load();
