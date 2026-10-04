/* صفحة القوة — بتخدم الضباط والأفراد. الفرق بينهم في الأعمدة وكرت القيادة،
   وحالة الراحة/التقصيرة بتيجي محسوبة من الباك إند فمش محتاجين نحمّل كل
   سجلات الراحات هنا. */
const IS_OFF = PAGE === "officers";
let LIST = {active: [], archive: []}, BUCKET = "active";
let COMMAND = {}, COMMAND_GROUPS = {};

const readMulti = el => [...el.selectedOptions].map(o => o.value);
const personById = id => [...LIST.active, ...LIST.archive].find(p => p.id === id);
const commandOf = id => COMMAND_ROLES().find(r => COMMAND[r] === id);
const groupRolesOf = id => GROUP_ROLES().filter(r => (COMMAND_GROUPS[r] || []).includes(id));

/* ضابط في راحة دلوقتي — إيقافها من هنا مباشرة (`rest-stop.js`) */
function restStopItem(p) {
  const lv = p.status_today?.state === "resting" ? p.status_today.leave : null;
  if (!lv?.id) return null;
  return {action: "stopRestFor", id: lv.id,
    extra: {name: p.name, type: lv.type, start: lv.start, end: lv.end}, label: "إيقاف الراحة"};
}
ACTIONS.stopRestFor = (id, extra) => openStopLeave({id, ...extra}, load);

function badges(p) {
  const roles = [commandOf(p.id), ...groupRolesOf(p.id)].filter(Boolean);
  if (!roles.length) return "";
  return `<div class="name-roles">${roles.map(r => `<span class="chip cmd">${esc(r)}</span>`).join("")}</div>`;
}

/* خلية الهاتف مقسّمة وبالاتجاه الصحيح للأرقام */
const phoneCell = (p, dash) => `<td class="num"><span dir="ltr">${esc(fmtPhone(p.phone)) || dash}</span></td>`;

function renderStats() {
  const onRest = LIST.active.filter(p => p.status_today?.state === "resting").length;
  $("#forceStats").innerHTML = `
    <div class="stat"><span>على القوة</span><strong>${LIST.active.length}</strong></div>
    <div class="stat"><span>في الأرشيف</span><strong>${LIST.archive.length}</strong></div>
    ${IS_OFF ? `<div class="stat"><span>في راحة اليوم</span><strong>${onRest}</strong></div>` : ""}
    <div class="stat"><span>الإجمالي (قوة + أرشيف)</span><strong>${LIST.active.length + LIST.archive.length}</strong></div>`;
}

function filterRows(rows) {
  const q = $("#search").value.trim();
  const rf = $("#restFilter")?.value;
  const rankF = $("#rankFilter")?.value;
  const statusF = $("#statusFilter")?.value;

  // تطبيع عربي — «احمد» تلاقي «أحمد»، و«فاطمه» تلاقي «فاطمة»
  if (q) rows = rows.filter(p => [p.name, p.code, p.phone, p.role, p.post, p.address]
    .some(v => arIncludes(v, q)));
  if (rf && IS_OFF) rows = rf === "__rest_now"
    ? rows.filter(p => p.status_today?.state === "resting")
    : rows.filter(p => (p.rest_system || "—") === rf);

  if (rankF) {
    if (IS_OFF) {
      if (rankF === "leaders") {
        rows = rows.filter(p => ["عميد", "عقيد", "مقدم"].some(r => (p.role || "").includes(r)));
      } else if (rankF === "officers") {
        rows = rows.filter(p => ["رائد", "نقيب", "ملازم"].some(r => (p.role || "").includes(r)));
      }
    } else {
      if (rankF === "nco") {
        rows = rows.filter(p => ["مساعد", "رقيب", "عريف"].some(r => (p.role || "").includes(r)));
      } else if (rankF === "soldiers") {
        rows = rows.filter(p => (p.role || "").includes("جندي"));
      }
    }
  }

  if (statusF) {
    if (statusF === "resting") {
      rows = rows.filter(p => p.status_today?.state === "resting");
    } else if (statusF === "working") {
      rows = rows.filter(p => p.status_today?.state !== "resting");
    }
  }

  return rows;
}

function officerSectionLabel(section) {
  const value = String(section || "القوة").trim() || "القوة";
  return value === "الحراسات المشددة" ? "الحراسات" : value;
}

function groupedOfficerRows(rows) {
  const order = META.officer_sections || ["القوة", "الحراسات المشددة", "الخوارج"];
  const out = [], used = new Set();
  for (const section of order) {
    const mine = rows.filter(p => (p.section || "القوة") === section);
    if (!mine.length) continue;
    used.add(section);
    out.push({_sectionHeader: officerSectionLabel(section), section: section});
    out.push(...mine);
  }
  for (const section of [...new Set(rows.map(p => p.section || "القوة"))]) {
    if (used.has(section)) continue;
    out.push({_sectionHeader: officerSectionLabel(section), section});
    out.push(...rows.filter(p => (p.section || "القوة") === section));
  }
  return out;
}

function renderTable() {
  const isArch = BUCKET === "archive";
  const rows   = filterRows(LIST[BUCKET]);
  const cid    = "tableWrap";
  const dash   = "<span class='muted'>—</span>";

  // ── تعريف الأعمدة القابلة للترتيب حسب السياق ──
  let cols, extraHeads, rowHtml;

  if (IS_OFF && !isArch) {
    // ── ضباط نشطون ──
    cols = {
      name:      { label: "الاسم",       fn: p => p.name,                           type: "text" },
      role:      { label: "الرتبة",      fn: p => rankIndex(p.role),                type: "num"  },
      code:      { label: "الأقدمية",    fn: p => p.code,                           type: "text" },
      post:      { label: "العمل المسند",fn: p => p.post || "",                     type: "text" },
      weapon:    { label: "عهدة السلاح", fn: p => p.weapon_custody || "",           type: "text" },
      rest:      { label: "نظام الراحة", fn: p => p.rest_system || "—",             type: "text" },
    };
    // عمود فاضي بالكامل بياخد مساحة من غير أي معلومة — بيظهر تاني أول ما أي صف يتملي
    const hasWeapon = rows.some(p => (p.weapon_custody || "").trim());
    if (!hasWeapon) delete cols.weapon;
    extraHeads = ["الهاتف", "الإجراء"];
    rowHtml = p => {
      if (p._sectionHeader) return `<tr class="section-row officer-section-row"><td colspan="${Object.keys(cols).length + extraHeads.length}">${esc(p._sectionHeader)} <span class="section-count">${rows.filter(x => (x.section || "القوة") === p.section).length}</span></td></tr>`;
      const acts = `<button class="mini" data-action="openPerson" data-id="${esc(p.id)}">تعديل</button>
        ${rowMenu([
          {action: "openLeaveFor", id: p.id, label: "تسجيل راحة"},
          restStopItem(p),
          {action: "openRemove", id: p.id, extra: {name: p.name}, label: "إخراج من القوة", danger: true},
        ])}`;
      return `<tr>
        <td class="name">${esc(p.name)}${badges(p)}</td>
        <td><span class="badge">${esc(p.role)}</span></td>
        <td>${esc(p.code)}</td>
        <td class="wrap">${esc(p.post) || "-"}</td>
        ${hasWeapon ? `<td>${esc(p.weapon_custody) || "<span class='muted'>—</span>"}</td>` : ""}
        <td>${restLabel(p)}</td>
        ${phoneCell(p, dash)}
        <td class="col-actions"><div class="actions">${acts}</div></td></tr>`;
    };

  } else if (IS_OFF && isArch) {
    // ── ضباط أرشيف ──
    cols = {
      name:       { label: "الاسم",       fn: p => p.name,             type: "text" },
      role:       { label: "الرتبة",      fn: p => rankIndex(p.role),  type: "num"  },
      code:       { label: "الأقدمية",    fn: p => p.code,             type: "text" },
      post:       { label: "العمل المسند",fn: p => p.post || "",       type: "text" },
      join_date:  { label: "من",          fn: p => p.join_date,        type: "date" },
      leave_date: { label: "إلى",         fn: p => p.leave_date || "", type: "date" },
    };
    extraHeads = ["الهاتف", "السبب", "الإجراء"];
    rowHtml = p => {
      const acts = `<button class="mini" data-action="openPerson" data-id="${esc(p.id)}">تعديل</button>
        ${rowMenu([
          {action: "restorePerson", id: p.id, label: "استرجاع إلى القوة"},
          {action: "deleteRecord", id: p.id, extra: {name: p.name}, label: "حذف نهائي", danger: true},
        ])}`;
      return `<tr>
        <td class="name">${esc(p.name)}</td>
        <td><span class="badge">${esc(p.role)}</span></td>
        <td>${esc(p.code)}</td>
        <td class="wrap">${esc(p.post) || "-"}</td>
        <td>${fmt(p.join_date)}</td>
        <td>${fmt(p.leave_date)}</td>
        ${phoneCell(p, dash)}
        <td class="wrap">${esc(p.leave_reason) || dash}</td>
        <td class="col-actions"><div class="actions">${acts}</div></td></tr>`;
    };

  } else if (!IS_OFF && !isArch) {
    // ── أفراد نشطون ──
    cols = {
      name:      { label: "الاسم",  fn: p => p.name,        type: "text" },
      role:      { label: "الدرجة", fn: p => p.role || "",  type: "text" },
      code:      { label: "الكود",  fn: p => p.code,        type: "text" },
      post:      { label: "العمل",  fn: p => p.post || "",  type: "text" },
      join_date: { label: "من",     fn: p => p.join_date,   type: "date" },
    };
    extraHeads = ["الهاتف", "العنوان", "الإجراء"];
    rowHtml = p => {
      const acts = `<button class="mini" data-action="openPerson" data-id="${esc(p.id)}">تعديل</button>
        ${rowMenu([{action: "openRemove", id: p.id, extra: {name: p.name},
          label: "إخراج من القوة", danger: true}])}`;
      return `<tr>
        <td class="name">${esc(p.name)}</td>
        <td><span class="badge person">${esc(p.role)}</span></td>
        <td>${esc(p.code)}</td>
        <td class="wrap">${esc(p.post) || "-"}</td>
        <td>${fmt(p.join_date)}</td>
        ${phoneCell(p, dash)}
        <td class="wrap">${esc(p.address) || "-"}</td>
        <td class="col-actions"><div class="actions">${acts}</div></td></tr>`;
    };

  } else {
    // ── أفراد أرشيف ──
    cols = {
      name:       { label: "الاسم",  fn: p => p.name,             type: "text" },
      role:       { label: "الدرجة", fn: p => p.role || "",       type: "text" },
      code:       { label: "الكود",  fn: p => p.code,             type: "text" },
      post:       { label: "العمل",  fn: p => p.post || "",       type: "text" },
      join_date:  { label: "من",     fn: p => p.join_date,        type: "date" },
      leave_date: { label: "إلى",    fn: p => p.leave_date || "", type: "date" },
    };
    extraHeads = ["الهاتف", "العنوان", "السبب", "الإجراء"];
    rowHtml = p => {
      const acts = `<button class="mini" data-action="openPerson" data-id="${esc(p.id)}">تعديل</button>
        ${rowMenu([
          {action: "restorePerson", id: p.id, label: "استرجاع إلى القوة"},
          {action: "deleteRecord", id: p.id, extra: {name: p.name}, label: "حذف نهائي", danger: true},
        ])}`;
      return `<tr>
        <td class="name">${esc(p.name)}</td>
        <td><span class="badge person">${esc(p.role)}</span></td>
        <td>${esc(p.code)}</td>
        <td class="wrap">${esc(p.post) || "-"}</td>
        <td>${fmt(p.join_date)}</td>
        <td>${fmt(p.leave_date)}</td>
        ${phoneCell(p, dash)}
        <td class="wrap">${esc(p.address) || "-"}</td>
        <td class="wrap">${esc(p.leave_reason) || dash}</td>
        <td class="col-actions"><div class="actions">${acts}</div></td></tr>`;
    };
  }

  // إعادة ضبط الـ sort state عند تغيير السياق (active↔archive أو officers↔personnel)
  const ctxKey = `${IS_OFF ? "off" : "prs"}_${isArch ? "arch" : "act"}`;
  if (_sortState(cid)._ctx !== ctxKey) {
    _sortStates[cid] = { col: null, dir: 0, _ctx: ctxKey };
  }

  const grouped = IS_OFF && !isArch && !_sortState(cid).col ? groupedOfficerRows(rows) : rows;
  $("#tableWrap").innerHTML = sortableTableBlock(
    cid, cols, grouped, rowHtml, extraHeads,
    `عدد النتائج: ${rows.length}`, {title: IS_OFF ? "لا يوجد ضباط" : "لا يوجد أفراد"}, renderTable
  );
}

function render() { renderStats(); renderTable(); }


/* ---------- قيادة الإدارة (صفحة الضباط بس) ---------- */
/* إعدادات بتتغيّر مرة كل حركة ضباط، فمطوية تحت الجدول. سطر الملخص بيقول
   مين شايل كل منصب من غير ما تفتح الكرت. */
function renderCommand() {
  const box = $("#commandBar"); if (!box) return;
  const wasOpen = box.querySelector("details")?.open;
  const officers = LIST.active;
  const held = [
    ...COMMAND_ROLES().map(role => {
      const p = COMMAND[role] ? personById(COMMAND[role]) : null;
      return p ? `${role}: ${esc(p.role)} / ${esc(p.name)}` : null;
    }),
    ...GROUP_ROLES().map(role => {
      const ids = COMMAND_GROUPS[role] || [];
      return ids.length ? `${role} (${ids.length})` : null;
    }),
  ].filter(Boolean);

  box.innerHTML = `
    <details class="settings-fold"${wasOpen ? " open" : ""}>
      <summary>
        <span class="fold-title">قيادة الإدارة</span>
        <span class="fold-now">${held.length ? held.join(" • ")
          : "<span class='muted'>لا توجد مناصب محددة</span>"}</span>
        <span class="fold-hint">تعديل</span>
      </summary>
      <p class="hint generated-hint">تشغيلهم ثابت يوميًا (إلا أيام الراحة)
        — غيّرهم مع حركة الضباط.</p>
      <div class="cmd-slots">${COMMAND_ROLES().map(role => {
        const cur = COMMAND[role], p = cur ? personById(cur) : null;
        return `<label class="cmd-slot"><span class="cmd-role">${esc(role)}</span>
          <select data-cmd-role="${esc(role)}" aria-label="${esc(role)}">
            <option value="">— غير محدد —</option>
            ${officers.map(o => `<option value="${esc(o.id)}" ${o.id === cur ? "selected" : ""}>${esc(o.role)} / ${esc(o.name)}</option>`).join("")}
          </select>
          ${p ? `<span class="cmd-now">${esc(p.role)} / ${esc(p.name)}</span>`
              : `<span class="cmd-now empty">لم يُحدَّد ضابط لهذا المنصب</span>`}</label>`;
      }).join("")}</div>
      <p class="hint generated-hint generated-hint-wide">يمكن أن يشغل منصبَي «طبي» و«بحث» أكثر من ضابط
        في الوقت نفسه — اختر كل الضباط الشاغلين لهذا المنصب، ثم
        اضغط «حفظ».</p>
      <div class="cmd-slots">${GROUP_ROLES().map(role => {
        const ids = COMMAND_GROUPS[role] || [];
        return `<label class="cmd-slot"><span class="cmd-role">${esc(role)}</span>
          <div class="cmd-group-pick">
            <select data-group-role="${esc(role)}" multiple size="4" aria-label="${esc(role)}">
              ${officers.map(o => `<option value="${esc(o.id)}" ${ids.includes(o.id) ? "selected" : ""}>${esc(o.role)} / ${esc(o.name)}</option>`).join("")}
            </select>
            <button type="button" class="mini ok" data-save-group="${esc(role)}">حفظ</button>
          </div>
          ${ids.length ? `<span class="cmd-now">${ids.map(oid => {
              const p = personById(oid);
              return p ? `${esc(p.role)} / ${esc(p.name)}` : "";
            }).filter(Boolean).join("، ")}</span>`
              : `<span class="cmd-now empty">لم يُحدَّد ضابط لهذا المنصب</span>`}</label>`;
      }).join("")}</div>
    </details>`;

  upgradeSelects(box);   // القوايم دي متولّدة بعد التحميل الأول
  box.querySelectorAll("[data-cmd-role]").forEach(sel => sel.onchange = async () => {
    const out = await api("/api/command", jsonReq("PATCH", {[sel.dataset.cmdRole]: sel.value || null}));
    if (!out) { renderCommand(); return }   // رجّع الاختيار القديم لو الطلب اترفض
    showToast("تم تحديث القيادة"); load();
  });
  // مناصب «طبي»/«بحث» بتتحفظ بزرار — مش عند كل تحديد/إلغاء اختيار، عشان
  // اختيار كذا ضابط من قايمة الاختيار المتعدد يفضل مفتوح من غير ما يتقفل
  // ويرجّع الصفحة تحمّل تاني بعد أول اختيار.
  box.querySelectorAll("[data-save-group]").forEach(btn => btn.onclick = async () => {
    const role = btn.dataset.saveGroup;
    const sel = box.querySelector(`[data-group-role="${CSS.escape(role)}"]`);
    const out = await api("/api/command-groups", jsonReq("PATCH", {[role]: readMulti(sel)}));
    if (!out) return;
    COMMAND_GROUPS = out;
    showToast("تم تحديث القيادة"); render(); renderCommand();
  });
}

/* ---------- نموذج الشخص ---------- */
function updateRoles() {
  const isOff = $("#type").value === "officer";
  fillSelect($("#role"), (isOff ? OFFICER_ROLES : PERSONNEL_ROLES).map(x => [x, x]), true);
  $("#weaponWrap").classList.toggle("hidden", !isOff);
  $("#restSysWrap").classList.toggle("hidden", !isOff);
  $("#restDayWrap").classList.toggle("hidden", !isOff);
  $("#addressWrap").classList.toggle("hidden", isOff);
  $("#officerSectionWrap")?.classList.toggle("hidden", !isOff);
  toggleRestDay();
}

function updateOfficerSection() {
  if (!$("#fSection")) return;
  const custom = $("#fSection").value === "__new__";
  $("#fNewSection").classList.toggle("hidden", !custom);
  $("#newSectionHint").classList.toggle("hidden", !custom);
  if (custom) $("#fNewSection").focus();
}

function fillOfficerSections(selected) {
  if (!$("#fSection")) return;
  const options = (META.officer_sections || ["القوة", "الحراسات المشددة", "الخوارج"])
    .map(x => [x, x]);
  fillSelect($("#fSection"), [["القوة", "القوة"], ...options.filter(x => x[0] !== "القوة"),
    ["__new__", "+ إضافة قسم جديد"]]);
  $("#fSection").value = selected && options.some(x => x[0] === selected) ? selected : (selected || "القوة");
  $("#fNewSection").value = selected && !options.some(x => x[0] === selected) ? selected : "";
  updateOfficerSection();
}
function toggleRestDay() {
  $("#restDayWrap").classList.toggle("hidden",
    $("#fRestSystem").value !== "أسبوعية" || $("#type").value !== "officer");
}

function openPerson(id) {
  const p = id ? personById(id) : null;
  $("#personId").value = id || "";
  $("#personModalTitle").textContent = p ? "تعديل البيانات" : "إضافة إلى القوة";
  $("#personSubmit").textContent = p ? "حفظ التعديلات" : "حفظ وإضافة للقوة";
  fillSelect($("#fRestSystem"), REST_SYSTEMS().map(x => [x, x]));
  fillSelect($("#fRestDay"), [["", "— بدون —"], ...WEEKDAYS().map(x => [x, x])]);

  $("#type").value = IS_OFF ? "officer" : "personnel";
  $("#type").disabled = !!p;
  updateRoles();

  $("#fName").value = p?.name || "";
  $("#fCode").value = p?.code || "";
  $("#fPhone").value = p?.phone || "";
  $("#fJoin").value = p?.join_date || curDate();
  $("#fPost").value = p?.post || "";
  fillOfficerSections(p?.section || "القوة");
  $("#fEffectiveFrom").value = curDate();
  $("#effectiveWrap").classList.toggle("hidden", !p);
  $("#fWeaponCustody").value = p?.weapon_custody || "";
  $("#fAddress").value = p?.address || "";
  if (p?.role) fillSelect($("#role"),
    [[p.role, p.role], ...(IS_OFF ? OFFICER_ROLES : PERSONNEL_ROLES).filter(x => x !== p.role).map(x => [x, x])]);
  $("#fRestSystem").value = p?.rest_system || "—";
  $("#fRestDay").value = p?.rest_day || "";
  toggleRestDay();

  const archived = p?.status === "archived";
  $("#archiveFields").classList.toggle("hidden", !archived);
  if (archived) { $("#fLeaveDate").value = p.leave_date || ""; $("#fLeaveReason").value = p.leave_reason || "" }
  openModal("personModal");
}

$("#personForm").onsubmit = async e => {
  e.preventDefault();
  const id = $("#personId").value, isOff = $("#type").value === "officer";
  const body = {name: $("#fName").value, role: $("#role").value, code: $("#fCode").value,
    phone: $("#fPhone").value, join_date: $("#fJoin").value, post: $("#fPost").value};
  if (id) body.effective_from = $("#fEffectiveFrom").value;
  if (isOff) {
    body.rest_system = $("#fRestSystem").value;
    body.rest_day = $("#fRestSystem").value === "أسبوعية" ? $("#fRestDay").value : "";
    body.weapon_custody = $("#fWeaponCustody").value.trim();
    const sectionSelect = $("#fSection");
    const custom = sectionSelect?.value === "__new__";
    // توافق مع نسخة HTML قديمة لم يكن فيها اختيار القسم بعد.
    body.section = custom ? ($("#fNewSection")?.value || "").trim()
      : (sectionSelect?.value || "القوة");
    if (custom) body.new_section = true;
  } else body.address = $("#fAddress").value;
  if (!$("#archiveFields").classList.contains("hidden")) {
    body.leave_date = $("#fLeaveDate").value; body.leave_reason = $("#fLeaveReason").value;
  }
  const out = id
    ? await api(`/api/person/${encodeURIComponent(id)}`, jsonReq("PATCH", body))
    : await api("/api/person", jsonReq("POST", {...body, type: $("#type").value}));
  if (!out) return;
  closeModal("personModal", true); showToast(id ? "تم حفظ التعديلات" : "تمت الإضافة إلى القوة"); load();
};

$("#removeForm").onsubmit = async e => {
  e.preventDefault();
  const id = $("#removeId").value;
  const body = {leave_date: $("#leaveDate").value, reason: $("#reason").value};

  // فيه راحات/فرق/تكليفات مسجّلة بعد تاريخ الخروج ده؟ السيرفر بيرفض
  // (409 + needs_confirm) من غير تأكيد صريح — نعرض ملخّص ونسأل قبل
  // ما نعيد النداء بـ`cleanup: true`.
  let conflicts = null;
  let out = await api(`/api/person/${encodeURIComponent(id)}/remove`,
    {...jsonReq("POST", body), onError: (b) => {
      if (b && b.needs_confirm) { conflicts = b; return true; }
      return false;
    }});

  if (!out && conflicts) {
    const conflictLabels = {
      leaves: "الراحات", terms: "الفرق", assignment_days: "أيام التكليف",
      state_days: "أيام الحالة", missions: "المأموريات",
    };
    const summary = Object.entries(conflicts.conflicts || {})
      .map(([k, v]) => `${conflictLabels[k] || k}: ${Array.isArray(v) ? v.length : v}`).join("، ");
    if (await confirmDialog({
      title: "تنظيف البيانات وإخراج السجل",
      body: `توجد بيانات مسجلة بعد تاريخ الخروج (${summary}). ستُحذف هذه البيانات ويُخرج السجل من القوة.`,
      confirmLabel: "تنظيف وإخراج",
      danger: true,
    })) {
      out = await api(`/api/person/${encodeURIComponent(id)}/remove`,
        jsonReq("POST", {...body, cleanup: true}));
    }
  }
  if (!out) return;
  closeModal("removeModal", true); showToast("تم الإخراج وحفظ السجل في الأرشيف"); load();
};

ACTIONS.openPerson = id => openPerson(id);
ACTIONS.openRemove = (id, extra) => {
  $("#removeId").value = id; $("#removeName").textContent = `سيتم إخراج: ${extra.name}`;
  $("#leaveDate").value = curDate(); $("#reason").value = ""; openModal("removeModal");
};
ACTIONS.restorePerson = async id => {
  // تاريخ الانضمام لازم يكون بعد تاريخ خروجه القديم — وإلا نفس الشخص
  // يتحسب مرتين في نفس اليوم على القوة (السجل القديم لسه بيغطي يوم
  // خروجه، والجديد بدأ منه أو قبله). السيرفر بيرفض (400) لو مخالف.
  const person = personById(id);
  const joinDate = await dateDialog({
    title: "استرجاع السجل إلى القوة",
    body: `سيُسترجع سجل «${person?.name || "السجل"}» إلى القوة من تاريخ الانضمام الجديد.`,
    label: "تاريخ الانضمام الجديد",
    value: curDate(),
    confirmLabel: "استرجاع إلى القوة",
    min: person?.leave_date ? addDays(person.leave_date, 1) : undefined,
  });
  if (joinDate === null) return;
  const body = {join_date: joinDate};
  if (await api(`/api/person/${encodeURIComponent(id)}/restore`, jsonReq("POST", body))) {
    showToast("تم الاسترجاع إلى القوة"); load();
  }
};
ACTIONS.deleteRecord = async (id, extra) => {
  if (!(await confirmDialog({
    title: "حذف سجل من الأرشيف",
    body: `سيُحذف سجل «${extra.name}» نهائيًا من الأرشيف ولا يمكن التراجع عن ذلك.`,
    confirmLabel: "حذف السجل نهائيًا",
    danger: true,
  }))) return;
  if (await api(`/api/person/${encodeURIComponent(id)}`, {method: "DELETE"})) {
    showToast("تم حذف السجل"); load();
  }
};
if (IS_OFF) ACTIONS.openLeaveFor = id => openLeave(null, id, personById(id));

/* ---------- ربط ---------- */
$$("[data-bucket]").forEach(b => b.onclick = () => {
  $$("[data-bucket]").forEach(x => {
    const selected=x===b;
    x.classList.toggle("active",selected);
    x.setAttribute("aria-selected",String(selected));
    x.tabIndex=selected?0:-1;
  });
  $("#tableWrap").setAttribute("aria-labelledby",b.id);
  BUCKET = b.dataset.bucket; $("#search").value = ""; render();
});
$("#search").oninput = debounce(render);   // إعادة الرسم بعد ما الكتابة تهدى
if ($("#restFilter")) $("#restFilter").onchange = render;
if ($("#rankFilter")) $("#rankFilter").onchange = render;
if ($("#statusFilter")) $("#statusFilter").onchange = render;
$("#addBtn").onclick = () => openPerson(null);
$("#type").onchange = updateRoles;
$("#fRestSystem").onchange = toggleRestDay;
// بعض نسخ القالب القديمة/المخزنة مؤقتًا قد لا تحتوي حقل القسم بعد؛ لا
// ينبغي أن يمنع ذلك بقية صفحة القوة من التحميل.
if ($("#fSection")) $("#fSection").onchange = updateOfficerSection;

async function load() {
  const d = await bootstrap();
  if (!d) return;
  LIST = IS_OFF ? d.officers : d.personnel;
  $("#addBtn").innerHTML = `${icon("plus")} ${IS_OFF ? "إضافة ضابط" : "إضافة فرد"}`;
  if (IS_OFF) {
    COMMAND = d.command || {};
    COMMAND_GROUPS = d.command_groups || {};
    fillSelect($("#restFilter"), [["", "كل أنظمة الراحة"], ["__rest_now", "في راحة اليوم"],
      ...REST_SYSTEMS().map(x => [x, x])], true);
    renderAlerts(d.alerts);
    renderCommand();
    if (typeof setLeavePeople === "function") setLeavePeople(LIST.active);
  }
  render();
}
load();
