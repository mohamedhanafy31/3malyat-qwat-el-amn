/* الرئيسية — لوحة تشغيل الخدمات اليومية، والمتابعة الإدارية القديمة تحتها. */
(async () => {
  const d = await bootstrap();
  if (!d) return;

  let ops = null;
  const today = curDate();
  const requestedDay = new URLSearchParams(location.search).get("day");
  let day = /^\d{4}-\d{2}-\d{2}$/.test(requestedDay || "") ? requestedDay : today;
  window.exportDocxUrl = () => `/api/ops/${day}/regularity.docx`;
  const userKey = document.getElementById("userChipWrap")?.dataset.userId || "anonymous";
  const prefKey = `opsBoardPrefs:v2:${userKey}`;
  const defaults = {view: "list", groupBy: "time", shift: "all", states: [], types: [], lines: [],
    timeWindow: "all", attention: false, collapsed: {}};
  let prefs = loadPrefs();
  let activeShift = prefs.shift || "all";
  let filters = {query: "", states: new Set(prefs.states || []), types: new Set(prefs.types || []),
    lines: new Set(prefs.lines || []), timeWindow: prefs.timeWindow || "all", attention: Boolean(prefs.attention)};
  const pendingTargets = new Set();
  const pendingLabels = new Map();
  const pendingTimers = new Map();
  const rowErrors = new Map();
  let regularity = null;
  let regularityDirty = false;
  let lastRefreshOkAt = 0;
  let keyboardZone = 0;

  const $id = id => document.getElementById(id);
  const shiftText = {am: "صباحية", pm: "ليلية"};
  const statusText = {upcoming: "قادمة", out: "بالخارج", back: "عادت", prep: "تجهّز", late: "متأخرة", carried: "مترحّلة"};

  const runLabel = run =>
    `${run.name || "الخدمة"} — ${shiftText[run.shift] || run.shift || ""}`;
  const actionTarget = run => run.ref || run.key;
  const runIdentity = run => actionTarget(run);
  const minutes = time => {
    if (!time) return null;
    const [hour, minute] = time.split(":").map(Number);
    return hour * 60 + minute;
  };

  function loadPrefs() {
    try { return {...defaults, ...(JSON.parse(localStorage.getItem(prefKey) || "{}"))}; }
    catch (_error) { return {...defaults, collapsed: {}}; }
  }

  function savePrefs() {
    try { localStorage.setItem(prefKey, JSON.stringify({...prefs, shift: activeShift, states: [...filters.states],
      types: [...filters.types], lines: [...filters.lines], timeWindow: filters.timeWindow, attention: filters.attention})); }
    catch (_error) { /* التخزين المحلي ممكن يكون مقفول في وضع التصفح الخاص. */ }
  }

  function markRegularityDirty() {
    regularityDirty = true;
    const status = $id("regularityStatus");
    if (status) { status.textContent = "تغييرات غير محفوظة"; status.classList.add("is-dirty"); }
  }

  const supervisorFields = {am: ["regularityAmRank", "regularityAmName", "regularityAmPhone"],
    pm: ["regularityPmRank", "regularityPmName", "regularityPmPhone"]};

  function setSupervisor(shift, value) {
    const fields = supervisorFields[shift];
    const row = value && typeof value === "object" ? value : {};
    fields.forEach((id, index) => { $id(id).value = row[["rank", "name", "phone"][index]] || ""; });
  }

  function regularityNotes(values) {
    const list = $id("regularityNotes");
    list.innerHTML = (values || []).map((value, index) => `<li class="regularity-note">
      <input type="text" maxlength="500" value="${esc(value)}" aria-label="الملاحظة ${index + 1}">
      <span class="regularity-note-tools">
        <button type="button" class="btn" data-regularity-note="up" ${index ? "" : "disabled"}>أعلى</button>
        <button type="button" class="btn" data-regularity-note="down" ${index === values.length - 1 ? "" : ""}>أسفل</button>
        <button type="button" class="btn" data-regularity-note="remove">حذف</button>
      </span></li>`).join("");
    list.querySelectorAll("[data-regularity-note=down]").forEach((button, index) => {
      button.disabled = index === list.children.length - 1;
    });
  }

  function regularityNoteValues() {
    return [...document.querySelectorAll("#regularityNotes input")].map(input => input.value);
  }

  function renderRegularity(result) {
    regularity = result;
    const inputs = result.inputs || {};
    const command = result.command || {};
    setSupervisor("am", inputs.big_column_supervisors?.am);
    setSupervisor("pm", inputs.big_column_supervisors?.pm);
    $id("regularityDirectorExtra").value = inputs.officer_extra?.[command["مدير الإدارة"]] || "";
    $id("regularityDeputyExtra").value = inputs.officer_extra?.[command["وكيل الإدارة"]] || "";
    const officer = id => (result.officers || []).find(item => item.id === id);
    const director = officer(command["مدير الإدارة"]);
    const deputy = officer(command["وكيل الإدارة"]);
    [["regularityDirectorLabel", "regularityDirectorExtra", director],
      ["regularityDeputyLabel", "regularityDeputyExtra", deputy]].forEach(([labelId, inputId, person]) => {
        const label = $id(labelId), input = $id(inputId), visible = Boolean(person);
        label.classList.toggle("hidden", !visible); input.disabled = !visible;
        label.firstChild.textContent = visible ? `نص ${person.rank || ""}/ ${person.name}` : "";
        if (!visible) input.value = "";
      });
    regularityNotes(inputs.notes || []);
    const inherited = $id("regularityInheritance");
    // inherited_from بيساوي اليوم نفسه لو مدخلاته محفوظة له — ده مش توريث
    const fromOther = result.inherited_from && result.inherited_from !== day;
    inherited.textContent = fromOther ? `مورّث من يوم ${fmt(result.inherited_from)}` : "";
    inherited.classList.toggle("hidden", !fromOther);
    regularityDirty = false;
    $id("regularityStatus").textContent = `عدد صفوف الخدمات: ${result.preview?.service_rows ?? 0}`;
    $id("regularityStatus").classList.remove("is-dirty");
  }

  function regularityPayload() {
    const command = regularity?.command || {};
    const extra = {};
    if (command["مدير الإدارة"] && $id("regularityDirectorExtra").value.trim()) extra[command["مدير الإدارة"]] = $id("regularityDirectorExtra").value.trim();
    if (command["وكيل الإدارة"] && $id("regularityDeputyExtra").value.trim()) extra[command["وكيل الإدارة"]] = $id("regularityDeputyExtra").value.trim();
    const value = id => $id(id).value.trim();
    const supervisor = shift => {
      const [rank, name, phone] = supervisorFields[shift].map(value);
      return {rank, name, phone};
    };
    return {officer_extra: extra,
      big_column_supervisors: {am: supervisor("am"), pm: supervisor("pm")},
      notes: regularityNoteValues()};
  }

  async function saveRegularity(reset = false) {
    const button = $id(reset ? "regularityReset" : "regularitySave");
    if (button.dataset.pending === "1") return;
    button.dataset.pending = "1"; button.disabled = true;
    const original = button.innerHTML;
    button.innerHTML = `<span class="spinner" aria-hidden="true"></span> جارٍ الحفظ…`;
    const body = reset ? {reset: true, revision: regularity.revision}
      : {inputs: regularityPayload(), revision: regularity.revision};
    const out = await api(`/api/ops/${day}/regularity`, {
      ...jsonReq("PUT", body), loadingLabel: "جارٍ حفظ بيانات يومية الانتظام…",
      onError: (payload, status) => status === 409 && payload.code === "stale_revision",
    });
    button.innerHTML = original; button.disabled = false; delete button.dataset.pending;
    if (!out) return;
    renderRegularity(out);
    showToast(reset ? "تم مسح تخصيص اليوم واسترجاع التوريث" : "تم حفظ بيانات يومية الانتظام");
  }

  async function loadRegularity() {
    const out = await api(`/api/ops/${day}/regularity`, {noLoader: true});
    if (!out) return;
    renderRegularity(out);
  }

  function stateKey(run) {
    if (run.day && run.ref) return "carried";
    if (run.state === "back") return "back";
    if (run.hint === "late") return "late";
    if (run.hint === "prep") return "prep";
    return run.state || "upcoming";
  }

  function mergeRun(old, run) {
    const merged = {...old};
    for (const key of ["line_id", "line", "lorry", "driver", "vehicle", "warning", "section_id", "section_name", "section_kind"]) {
      if (!merged[key] && run[key]) merged[key] = run[key];
    }
    merged.types = [...new Set([...(old.types || []), ...(run.types || [])])];
    merged.line_meta = merged.line_meta || run.line_meta || null;
    merged.sources = [...new Set([...(old.sources || []), ...(run.sources || [])])];
    return merged;
  }

  function flattenRunsWithContext(payload) {
    const map = new Map();
    const add = (run, context = {}) => {
      const item = {...run, ...context};
      const id = runIdentity(item);
      map.set(id, map.has(id) ? mergeRun(map.get(id), item) : item);
    };
    for (const run of payload?.groups?.officers || []) add(run, {category: "ضباط"});
    for (const block of [payload.groups.basic?.am, payload.groups.basic?.pm,
      payload.groups.emergency]) {
      for (const run of block?.single || []) add(run, {category: block === payload.groups.emergency ? "طارئة" : "أساسية"});
      for (const line of block?.lines || []) {
        for (const run of line.runs || []) add(run, {
          category: block === payload.groups.emergency ? "طارئة" : "أساسية",
          line_id: run.line_id || line.line_id, line: run.line || line.line,
          lorry: run.lorry || line.lorry, driver: run.driver || line.driver,
          vehicle: run.vehicle || line.vehicle, warning: run.warning || line.warning,
        });
      }
    }
    return [...map.values()];
  }

  function allRuns() {
    if (Array.isArray(ops?.runs)) return ops.runs.map(run => ({...run}));
    const map = new Map();
    for (const run of ops?.carried || []) map.set(runIdentity(run), {...run});
    for (const run of flattenRunsWithContext(ops)) {
      const id = runIdentity(run);
      map.set(id, map.has(id) ? mergeRun(map.get(id), run) : run);
    }
    return [...map.values()];
  }

  function announce(text) {
    $id("opsLive").textContent = text;
  }

  function formatCountdown(total) {
    if (total == null) return "";
    if (total <= 0) return "حان المعاد";
    const hours = Math.floor(total / 60);
    const minutesLeft = total % 60;
    return hours ? `بعد ${hours}س ${minutesLeft}د` : `بعد ${minutesLeft} دقيقة`;
  }

  function paintDayContext() {
    const input = $id("dashboardDate");
    if (input) input.value = day;
    const warning = $id("dashboardDayWarning");
    const historical = day !== today;
    if (warning) {
      warning.textContent = historical ? `عرض يوم ${fmt(day)}` : "";
      warning.classList.toggle("hidden", !historical);
    }
    $id("opsNext")?.classList.toggle("ops-next-hidden", historical);
  }

  async function setDay(nextDay, {replace = false} = {}) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(nextDay) || nextDay === day) return;
    if (regularityDirty && !window.confirm("توجد تغييرات غير محفوظة في بيانات الانتظام. هل تريد تغيير اليوم؟")) return;
    pendingTimers.forEach(timer => clearTimeout(timer));
    pendingTargets.clear(); pendingLabels.clear(); pendingTimers.clear(); rowErrors.clear();
    closeModal("opsLineModal", false); closeModal("opsTimeModal", false);
    day = nextDay; ops = null; regularity = null; regularityDirty = false;
    filters = {query: "", states: new Set(), types: new Set(), lines: new Set(), timeWindow: "all", attention: false};
    activeShift = "all"; prefs.collapsed = {};
    const url = new URL(location.href);
    if (day === today) url.searchParams.delete("day"); else url.searchParams.set("day", day);
    history[replace ? "replaceState" : "pushState"]({}, "", url);
    paintDayContext(); updateToolbar(); paintCounters();
    $id("opsBoard").setAttribute("aria-busy", "true");
    $id("opsBoard").innerHTML = `<div class="ops-loading">جارٍ تحميل لوحة التشغيل…</div>`;
    $id("opsNext").textContent = day === today ? "جارٍ تحميل لوحة التشغيل…" : "—";
    await loadOps();
    await loadRegularity();
  }

  function paintClock() {
    const now = new Date();
    $id("opsClock").textContent = now.toLocaleTimeString("en-GB", {
      hour: "2-digit", minute: "2-digit", second: "2-digit",
    });
    if (day !== today) { $id("opsNext").textContent = "—"; return; }
    if (!ops) return;

    const next = ops.next;
    if (!next) {
      $id("opsNext").innerHTML =
        `<span class="ops-next-empty">لا توجد خدمة قادمة اليوم</span>`;
      return;
    }
    const current = now.getHours() * 60 + now.getMinutes() + now.getSeconds() / 60;
    const delta = minutes(next.report_time) - current;
    const label = next.line || runLabel(next);
    $id("opsNext").innerHTML = `
      <strong>${esc(label)}</strong>
      <span>${esc(next.report_text || next.report_time || "")}
        <b>${esc(formatCountdown(Math.max(0, Math.ceil(delta))))}</b>
      </span>`;
  }

  function paintCounters() {
    const counters = ops.counters || {};
    const items = [
      ["upcoming", "قادمة"], ["prep", "تجهّز"], ["late", "متأخرة"],
      ["out", "بالخارج"], ["back", "عادت"], ["carried", "مترحّلة"],
    ];
    $id("opsCounters").innerHTML = items.map(([key, label]) => `
      <button type="button" class="ops-counter ops-counter-${key}${counters[key] ? "" : " ops-counter-zero"} ${filters.states.has(key) ? "is-selected" : ""}"
        data-filter-state="${key}" aria-pressed="${filters.states.has(key)}">
        <b>${counters[key] ?? 0}</b><span>${label}</span>
      </button>`).join("");
  }

  function carriedMeta(run) {
    if (!run.day) return "";
    const time = run.out_at ? run.out_at.slice(11, 16) : "—";
    return `خرجت يوم ${dayName(run.day)} ${fmtShort(run.day)} الساعة ${time}`;
  }

  function displayState(run) { return stateKey(run); }

  function actionFor(run) {
    const state = displayState(run);
    return ["upcoming", "prep", "late"].includes(state) ? "depart" : state === "out" || state === "carried" ? "return" : "";
  }

  function actionLabel(action) { return action === "depart" ? "قيام" : action === "return" ? "عودة" : ""; }

  function pendingLabel(target) { return pendingLabels.get(target) || "جارٍ التسجيل…"; }
  function isModalOpen() { return Boolean(document.querySelector(".modal:not(.hidden)")); }
  function currentRunElement(target) { return document.querySelector(`[data-run-key="${CSS.escape(String(target))}"]`); }
  function rememberFocus() {
    const active = document.activeElement;
    return {target: active?.closest?.("[data-run-key]")?.dataset.runKey || null, scroll: window.scrollY};
  }
  function restoreFocus(snapshot, preferredTarget) {
    window.scrollTo({top: snapshot.scroll, behavior: "auto"});
    const target = snapshot.target || preferredTarget;
    const el = target ? currentRunElement(target) : document.querySelector("[data-run-key]");
    if (el) { el.focus({preventScroll: true}); return; }
    document.querySelector("[data-run-key]")?.focus({preventScroll: true});
  }
  function syncPendingDom(targets) {
    for (const target of targets) {
      const el = currentRunElement(target);
      if (!el) continue;
      const busy = pendingTargets.has(target);
      el.setAttribute("aria-busy", String(busy));
      el.querySelectorAll("button").forEach(button => {
        button.disabled = busy;
        button.setAttribute("aria-disabled", String(busy));
      });
      const action = el.querySelector(`[data-target="${CSS.escape(String(target))}"][data-op="depart"], [data-target="${CSS.escape(String(target))}"][data-op="return"]`);
      if (action && busy) action.innerHTML = `<span class="spinner" aria-hidden="true"></span> ${esc(pendingLabel(target))}`;
      if (action && !busy) action.innerHTML = esc(actionLabel(action.dataset.op));
    }
  }
  function slowNotice(target) {
    const el = currentRunElement(target);
    if (!el || !pendingTargets.has(target)) return;
    const host = el.querySelector(".ops-row-status, .ops-card-meta") || el;
    if (!host.querySelector(".ops-slow")) host.insertAdjacentHTML("beforeend", `<small class="ops-slow">الاتصال بطيء — ما زال التسجيل جاريًا</small>`);
    const dialog = document.querySelector(".modal:not(.hidden) .dialog-actions");
    if (dialog && !dialog.querySelector(".ops-dialog-slow")) dialog.insertAdjacentHTML("beforebegin", `<p class="ops-dialog-slow ops-slow">الاتصال بطيء — ما زال التسجيل جاريًا</p>`);
  }
  function clearPending(targets) {
    targets.forEach(target => {
      pendingTargets.delete(target); pendingLabels.delete(target);
      clearTimeout(pendingTimers.get(target)); pendingTimers.delete(target);
    });
    document.querySelectorAll(".ops-dialog-slow").forEach(item => item.remove());
    syncPendingDom(targets);
  }

  function runContext(run) {
    // من غير خط: الـfallback كان `run` نفسه فاسم الخدمة كان بيطلع كأنه اسم الخط
    const meta = run.line_meta || {};
    return [meta.name || run.line, meta.lorry ? `لوري ${meta.lorry}` : "", meta.driver,
      meta.vehicle, run.section_name || run.category].filter(Boolean).join(" · ") || "بلا خط";
  }

  function card(run) {
    const state = displayState(run);
    const action = actionFor(run);
    const target = actionTarget(run);
    const lastChange = run.back_at || run.out_at;
    const undoable = lastChange &&
      Date.now() - new Date(lastChange).getTime() <= 300000;
    const head = run.head
      ? `القائم بها: ${run.head}`
      : "القائم بها غير مسجّل";
    const count = run.count == null || run.count === ""
      ? "القوام غير مسجّل"
      : countLabel(run.count, "مجند");
    const details = `${head} · ${count}${run.weapon ? ` · ${run.weapon}` : ""}`;
    const actionHtml = action
      ? `<button type="button" class="primary ops-action"
           data-op="${action}"
           data-target="${esc(target)}"
           aria-label="${actionLabel(action)}: ${esc(runLabel(run))}">${actionLabel(action)}</button>`
      : `<span class="ops-times">${state === "back" ? `عاد ${esc(run.back_at?.slice(11, 16) || "—")}` : ""}</span>`;
    const menu = rowMenu([
      undoable ? {label: "تراجع", action: "opsUndo", id: target, danger: true} : null,
      {label: "تعديل المعاد", action: "opsEditTime", id: target},
    ], {label: `إجراءات ${runLabel(run)}`});

    return `<article class="ops-card ops-state-${state}" data-run-key="${esc(target)}" data-state="${state}" tabindex="-1"
        aria-busy="${pendingTargets.has(target)}">
      <div class="ops-card-head">
        <div class="ops-card-name" title="${esc(run.name || "")}">
          ${esc(run.name || "خدمة")}
        </div>
        <div class="ops-card-tools">
          <span class="badge">${esc(shiftText[run.shift] || run.shift || "—")}</span>
          ${menu}
        </div>
      </div>
      <div class="ops-card-meta">
        <span class="ops-report">${esc(run.report_text || run.report_time || "بدون معاد")}</span>
        <span class="ops-status-label">${statusText[state]}</span>${pendingTargets.has(target) ? `<small class="ops-pending-label">${esc(pendingLabel(target))}</small>` : ""}
      </div>${rowErrors.has(target) ? `<p class="ops-row-error" role="alert">${esc(rowErrors.get(target))}</p>` : ""}
      <div class="ops-card-detail">
        <span title="${esc(details)}">${esc(details)}</span>
        ${run.day ? `<span class="ops-carried-meta">${esc(carriedMeta(run))}</span>` : ""}
      </div>
      <div class="ops-card-foot">
        <span class="ops-card-context">${esc(runContext(run))}</span>
        ${actionHtml}
      </div>
    </article>`;
  }

  function lineMetaText(line) {
    return [
      line.lorry ? `لوري ${line.lorry}` : "",
      line.driver || "", line.vehicle || "",
    ].filter(Boolean).join(" · ");
  }

  function lineMeta(line) {
    // غياب السواق أو العربية معناه إن اللوري مش متسجل في يومية الحملة النهاردة.
    const bits = [];
    if (!line.driver && !line.vehicle) bits.push(`<span class="ops-line-missing">لم تُسجَّل بيانات اللوري في يومية الحملة</span>`);
    else bits.push(esc(lineMetaText(line)));
    if (line.warning) bits.push(`<span class="ops-line-warning">${esc(line.warning)}</span>`);
    return bits.join(" · ");
  }

  function normaliseArabic(value) { return String(value || "").toLowerCase().normalize("NFKD").replace(/[\u064B-\u065F\u0670]/g, "").replace(/[إأآٱ]/g, "ا").replace(/ى/g, "ي").replace(/ة/g, "ه").replace(/ؤ/g, "و").replace(/ئ/g, "ي").replace(/ـ/g, ""); }
  function searchText(run) { return normaliseArabic([run.name, run.head, run.line, run.lorry, run.weapon, run.report_text, run.report_time, run.category, run.section_name, run.line_meta?.name, run.line_meta?.driver, run.line_meta?.vehicle].join(" ")); }
  function lineKey(run) { return run.line_meta?.line_id || run.line_id || "none"; }
  function timeMatches(run) {
    if (filters.timeWindow === "all") return true;
    if (filters.timeWindow === "none") return !run.report_time;
    if (!run.report_time) return false;
    const delta = minutes(run.report_time) - (new Date().getHours() * 60 + new Date().getMinutes());
    return delta >= 0 && delta <= Number(filters.timeWindow);
  }
  function matchesFilters(run) {
    const state = displayState(run);
    if (activeShift !== "all" && run.shift !== activeShift) return false;
    if (filters.states.size && !filters.states.has(state)) return false;
    if (!filters.states.size && state === "back") return false;
    if (filters.attention && !["late", "prep", "carried"].includes(state)) return false;
    if (filters.types.size && ![...(run.types || [])].some(type => filters.types.has(type))) return false;
    if (filters.lines.size && !filters.lines.has(lineKey(run))) return false;
    if (!timeMatches(run)) return false;
    const terms = normaliseArabic(filters.query).split(/\s+/).filter(Boolean);
    return terms.every(term => searchText(run).includes(term));
  }

  function groupRuns(runs) {
    if (prefs.groupBy === "none") return [{id: "all", title: "كل الخدمات", runs}];
    const groups = new Map();
    for (const run of runs) {
      const id = prefs.groupBy === "line" ? lineKey(run)
        : prefs.groupBy === "section" ? (run.section_id || "emergency")
        : prefs.groupBy === "state" ? displayState(run)
        : (run.report_time || "none");
      const title = prefs.groupBy === "line" ? (run.line_meta?.name || run.line || "بلا خط")
        : prefs.groupBy === "section" ? (run.section_name || "الخدمات")
        : prefs.groupBy === "state" ? statusText[displayState(run)]
        : (run.report_text || run.report_time || "بدون معاد");
      if (!groups.has(id)) groups.set(id, {id, title, runs: []});
      groups.get(id).runs.push(run);
    }
    return [...groups.values()].sort((a, b) => prefs.groupBy === "time"
      ? (minutes(a.runs[0].report_time) ?? 9999) - (minutes(b.runs[0].report_time) ?? 9999)
      : prefs.groupBy === "state" ? ["carried", "late", "prep", "out", "upcoming", "back"].indexOf(displayState(a.runs[0])) - ["carried", "late", "prep", "out", "upcoming", "back"].indexOf(displayState(b.runs[0]))
      : a.title.localeCompare(b.title, "ar"));
  }

  function stateSummary(runs) {
    const counts = {};
    for (const run of runs) counts[displayState(run)] = (counts[displayState(run)] || 0) + 1;
    return ["late", "prep", "out", "carried", "upcoming", "back"].filter(key => counts[key])
      .map(key => `${counts[key]} ${statusText[key]}`).join(" · ");
  }

  function row(run) {
    const action = actionFor(run), target = actionTarget(run), state = displayState(run);
    const lastChange = run.back_at || run.out_at;
    const undoable = lastChange && Date.now() - new Date(lastChange).getTime() <= 300000;
    const menu = rowMenu([undoable ? {label: "تراجع", action: "opsUndo", id: target, danger: true} : null,
      {label: "تعديل المعاد", action: "opsEditTime", id: target}], {label: `إجراءات ${runLabel(run)}`});
    return `<tr class="ops-row ops-state-${state}" data-run-key="${esc(target)}" tabindex="-1" aria-busy="${pendingTargets.has(target)}">
      <td class="ops-row-status"><span>${statusText[state]}</span>${pendingTargets.has(target) ? `<small class="ops-pending-label">${esc(pendingLabel(target))}</small>` : ""}</td>
      <th scope="row"><strong>${esc(run.name || "خدمة")}</strong><small>${esc(runContext(run))}</small></th>
      <td class="ops-row-time">${esc(run.report_text || run.report_time || "—")}</td>
      <td>${esc(shiftText[run.shift] || run.shift || "—")}</td>
      <td class="ops-row-head">${esc(run.head || "غير مسجّل")}</td>
      <td>${esc(run.count == null || run.count === "" ? "—" : `${run.count}${run.weapon ? ` · ${run.weapon}` : ""}`)}</td>
      <td class="ops-row-context">${esc(runContext(run))}</td>
      <td class="ops-row-action">${action ? `<button type="button" class="primary ops-action" data-op="${action}" data-target="${esc(target)}">${pendingTargets.has(target) ? `<span class="spinner" aria-hidden="true"></span> ${esc(pendingLabel(target))}` : actionLabel(action)}</button>` : `<span class="ops-times">${esc(run.back_at?.slice(11, 16) || "")}</span>`}${menu}${rowErrors.has(target) ? `<span class="ops-row-error" role="alert">${esc(rowErrors.get(target))}</span>` : ""}</td>
    </tr>`;
  }

  function groupMarkup(group) {
    const eligibleDepart = group.runs.filter(run => ["upcoming", "prep", "late"].includes(displayState(run)));
    const eligibleReturn = group.runs.filter(run => ["out", "carried"].includes(displayState(run)));
    const collapsed = Boolean(prefs.collapsed[`${prefs.groupBy}:${group.id}`]);
    const actions = [];
    if (eligibleDepart.length) actions.push(`<button type="button" class="btn" data-op="line" data-mode="depart" data-line="${esc(group.title)}" data-meta="" data-keys="${esc(JSON.stringify(eligibleDepart.map(actionTarget)))}">قيام الكل (${eligibleDepart.length})</button>`);
    if (eligibleReturn.length) actions.push(`<button type="button" class="btn ok" data-op="line" data-mode="return" data-line="${esc(group.title)}" data-meta="" data-keys="${esc(JSON.stringify(eligibleReturn.map(actionTarget)))}">عودة الكل (${eligibleReturn.length})</button>`);
    const body = viewMode() === "cards" ? `<div class="ops-grid">${group.runs.map(card).join("")}</div>` : `<div class="ops-table-wrap"><table class="ops-list"><colgroup><col class="ops-col-status"><col class="ops-col-service"><col class="ops-col-time"><col class="ops-col-shift"><col class="ops-col-person"><col class="ops-col-count"><col class="ops-col-context"><col class="ops-col-action"></colgroup><thead><tr><th>الحالة</th><th>الخدمة</th><th>المعاد</th><th>الفترة</th><th>القائم بها</th><th>القوام</th><th>الخط / القسم</th><th>الإجراء</th></tr></thead><tbody>${group.runs.map(row).join("")}</tbody></table></div>`;
    return `<section class="ops-group ${collapsed ? "is-collapsed" : ""}" data-group-id="${esc(group.id)}">
      <div class="ops-group-header"><button type="button" class="ops-group-toggle" aria-expanded="${!collapsed}" data-op="collapse" data-group="${esc(group.id)}"><span aria-hidden="true">${collapsed ? "›" : "⌄"}</span><strong>${esc(group.title)}</strong><span class="ops-group-count">${group.runs.length}/${group.total || group.runs.length}</span><small>${esc(stateSummary(group.runs))}</small></button><div class="ops-group-actions">${actions.join("")}</div></div>
      <div class="ops-group-body">${body}</div>
    </section>`;
  }

  function viewMode() { return window.matchMedia("(max-width: 760px)").matches ? "cards" : prefs.view; }

  function renderBoard() {
    const current = allRuns();
    const filtered = current.filter(matchesFilters).sort((a, b) => {
      const ca = displayState(a) === "carried" ? 0 : 1, cb = displayState(b) === "carried" ? 0 : 1;
      return ca - cb || (minutes(a.report_time) ?? 9999) - (minutes(b.report_time) ?? 9999);
    });
    const groups = groupRuns(filtered);
    const totals = Object.fromEntries(groupRuns(current).map(group => [group.id, group.runs.length]));
    groups.forEach(group => { group.total = totals[group.id] || group.runs.length; });
    $id("opsBoard").setAttribute("aria-busy", "false");
    $id("opsBoard").className = `ops-board ops-view-${viewMode()}`;
    $id("opsBoard").innerHTML = filtered.length ? groups.map(groupMarkup).join("") : renderEmptyResult();
    paintAttention();
    updateToolbar();
    paintClock();
    setRovingRows();
  }

  function setRovingRows(preferred) {
    const rows = [...document.querySelectorAll("#opsBoard [data-run-key]")];
    if (!rows.length) return;
    const current = preferred || document.activeElement?.closest?.("[data-run-key]")?.dataset.runKey;
    rows.forEach((el, index) => { el.tabIndex = (current && el.dataset.runKey === current) || (!current && index === 0) ? 0 : -1; });
  }

  function updateGroupDom(group, affectedTargets) {
    let section = document.querySelector(`#opsBoard .ops-group[data-group-id="${CSS.escape(String(group.id))}"]`);
    if (!section) {
      const holder = document.createElement("div");
      holder.innerHTML = groupMarkup(group);
      section = holder.firstElementChild;
      const ordered = [...document.querySelectorAll("#opsBoard .ops-group")].find(item => item.dataset.groupId.localeCompare(String(group.id), "ar") > 0);
      $id("opsBoard").insertBefore(section, ordered || null);
      return section;
    }
    const oldBody = section.querySelector(".ops-group-body");
    const oldHeader = section.querySelector(".ops-group-header");
    const holder = document.createElement("div");
    holder.innerHTML = groupMarkup(group);
    const fresh = holder.firstElementChild;
    oldHeader.replaceWith(fresh.querySelector(".ops-group-header"));
    const freshBody = fresh.querySelector(".ops-group-body");
    // محتوى الجدول بيتحدث للصفوف المتأثرة فقط؛ جسم المجموعة الجديد يستخدم
    // كمرجع ترتيب، لكننا لا نستبدل الصفوف الموجودة حتى تفضل القائمة المفتوحة.
    for (const run of group.runs) {
      const target = actionTarget(run);
      const current = section.querySelector(`[data-run-key="${CSS.escape(String(target))}"]`);
      const desired = fresh.querySelector(`[data-run-key="${CSS.escape(String(target))}"]`);
      if (current && desired && affectedTargets.has(target)) current.replaceWith(desired);
      else if (!current && desired) {
        const body = section.querySelector("tbody") || section.querySelector(".ops-grid");
        body?.appendChild(desired);
      }
    }
    if (oldBody && !section.querySelector("[data-run-key]")) section.remove();
    return section;
  }

  function reconcileBoard(previousRuns, affectedTargets, focusSnapshot) {
    const current = allRuns();
    const visible = current.filter(matchesFilters).sort((a, b) => {
      const ca = displayState(a) === "carried" ? 0 : 1, cb = displayState(b) === "carried" ? 0 : 1;
      return ca - cb || (minutes(a.report_time) ?? 9999) - (minutes(b.report_time) ?? 9999);
    });
    const groups = groupRuns(visible);
    const oldElements = new Map([...document.querySelectorAll("#opsBoard [data-run-key]")].map(el => [el.dataset.runKey, el]));
    if (affectedTargets.size && document.querySelector("#rowMenuPopup:not(.hidden)")) document.querySelector("#rowMenuPopup").classList.add("hidden");
    affectedTargets.forEach(target => oldElements.get(String(target))?.remove());
    for (const group of groups) {
      const totals = Object.fromEntries(groupRuns(current).map(item => [item.id, item.runs.length]));
      group.total = totals[group.id] || group.runs.length;
      const section = updateGroupDom(group, affectedTargets);
      for (const run of group.runs.filter(item => affectedTargets.has(actionTarget(item)))) {
        const target = actionTarget(run);
        if (section.querySelector(`[data-run-key="${CSS.escape(String(target))}"]`)) continue;
        const holder = document.createElement("div"); holder.innerHTML = viewMode() === "cards" ? card(run) : row(run);
        const body = section.querySelector("tbody") || section.querySelector(".ops-grid");
        body?.appendChild(holder.firstElementChild);
      }
    }
    groups.forEach(group => {
      const section = document.querySelector(`#opsBoard .ops-group[data-group-id="${CSS.escape(String(group.id))}"]`);
      if (section) $id("opsBoard").appendChild(section);
    });
    document.querySelectorAll("#opsBoard .ops-group").forEach(section => {
      if (!section.querySelector("[data-run-key]")) section.remove();
    });
    if (!visible.length) $id("opsBoard").innerHTML = renderEmptyResult();
    paintCounters(); paintAttention(); updateToolbar(); paintClock(); setRovingRows(focusSnapshot?.target);
    restoreFocus(focusSnapshot || {scroll: window.scrollY}, affectedTargets[0]);
  }

  function paintSync() {
    const label = $id("opsLastUpdated");
    if (!label) return;
    const age = lastRefreshOkAt ? Math.max(0, Math.floor((Date.now() - lastRefreshOkAt) / 1000)) : Infinity;
    const time = lastRefreshOkAt ? new Date(lastRefreshOkAt).toLocaleTimeString("en-GB", {hour: "2-digit", minute: "2-digit", second: "2-digit"}) : "—";
    const stale = age > 90;
    label.textContent = stale ? `لم يتم التحديث منذ ${age < 3600 ? `${Math.floor(age / 60)} دقيقة` : "مدة طويلة"}` : `آخر تحديث ${time}`;
    $id("opsSync")?.classList.toggle("is-stale", stale);
    $id("opsRefreshNow")?.classList.toggle("hidden", !stale);
  }

  function renderEmptyResult() {
    const scope = [activeShift !== "all" ? shiftText[activeShift] : "", filters.states.size ? [...filters.states].map(s => statusText[s]).join(" أو ") : "", filters.attention ? "تحتاج إجراء الآن" : "", filters.query ? `بحث «${filters.query}»` : ""].filter(Boolean).join(" + ") || "الفلاتر الحالية";
    return `<div class="ops-empty"><strong>لا توجد نتائج ضمن: ${esc(scope)}</strong><div><button type="button" class="btn" data-op="clear-search">مسح البحث</button><button type="button" class="btn" data-op="clear-filters">مسح كل الفلاتر</button></div></div>`;
  }

  function paintAttention() {
    const counters = ops.counters || {};
    $id("opsAttention").innerHTML = `<span>إجراء الآن:</span> <button type="button" data-attention-state="late">${counters.late || 0} متأخرة</button> · <button type="button" data-attention-state="prep">${counters.prep || 0} تجهّز</button> · <button type="button" data-attention-state="carried">${counters.carried || 0} مترحّلة</button>`;
  }

  function updateToolbar() {
    $id("opsSearch").value = filters.query;
    $id("opsShiftFilter").value = activeShift;
    $id("opsGroupBy").value = prefs.groupBy;
    $id("opsAttentionToggle").setAttribute("aria-pressed", String(filters.attention));
    document.querySelectorAll("[data-view]").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.view === viewMode())));
    const filterCount = filters.types.size + filters.lines.size + (filters.timeWindow !== "all" ? 1 : 0)
      + filters.states.size + (filters.attention ? 1 : 0) + (filters.query ? 1 : 0) + (activeShift !== "all" ? 1 : 0);
    $id("opsFiltersToggle").textContent = filterCount ? `فلاتر نشطة: ${filterCount}` : "فلاتر";
    $id("opsTimeWindow").value = filters.timeWindow;
    document.querySelectorAll("[data-filter-type]").forEach(input => { input.checked = filters.types.has(input.dataset.filterType); });
    const lineValues = new Map();
    for (const run of allRuns()) lineValues.set(lineKey(run), run.line_meta?.name || run.line || "بلا خط");
    $id("opsLineFilters").innerHTML = [...lineValues.entries()].sort((a, b) => a[1].localeCompare(b[1], "ar"))
      .map(([key, label]) => `<button type="button" class="ops-filter-chip ${filters.lines.has(key) ? "is-selected" : ""}" data-filter-line="${esc(key)}" aria-pressed="${filters.lines.has(key)}">${esc(label)}</button>`).join("");
    $id("opsClear").classList.toggle("hidden", !(filters.query || filters.states.size || filters.attention || activeShift !== "all" || filterCount));
  }

  async function loadOps() {
    const next = await api(`/api/ops/${day}`, {noLoader: true});
    if (!next) { paintSync(); return; }
    // التحديث الدوري مايعيدش رسم اللوحة لو مفيش حاجة اتغيّرت — إعادة الرسم
    // بتقفل أي قايمة ⋯ مفتوحة وبتضيّع مكان التركيز من الكيبورد كل 30 ثانية.
    // التلميحات (جهّز/متأخرة) بتتحسب على السيرفر بالدقيقة، فبنقارنها برضه.
    const sig = data => JSON.stringify([data.revision, data.counters, data.next?.key]);
    const previous = ops;
    const changed = !ops || sig(ops) !== sig(next);
    ops = next;
    lastRefreshOkAt = Date.now(); paintSync();
    if (!changed) return;
    const before = new Map((previous ? allRuns() : []).map(run => [actionTarget(run), run]));
    const after = new Map(allRuns().map(run => [actionTarget(run), run]));
    const affected = new Set([...before.keys(), ...after.keys()].filter(key => JSON.stringify(before.get(key)) !== JSON.stringify(after.get(key))));
    // الرسم الكامل (أول تحميل) لازم يرسم العدادات والسطر العلوي كمان —
    // reconcileBoard بيرسمهم لوحده، لكن renderBoard لأ.
    if (!previous || !document.querySelector("#opsBoard [data-run-key]")) {
      renderBoard(); paintCounters(); paintAttention(); paintClock();
    } else reconcileBoard(before, affected, rememberFocus());
  }

  async function mutate(url, body, button, success, method = "POST") {
    if (button?.dataset.pending === "1") return;
    const targets = body.keys || (body.key ? [body.key] : []);
    const action = url.endsWith("/return") || body.mode === "return" ? "return" : url.endsWith("/time") ? "time" : url.endsWith("/undo") ? "undo" : "depart";
    const busyText = action === "return" ? "جارٍ تسجيل العودة…" : action === "time" ? "جارٍ حفظ تعديل المعاد…" : action === "undo" ? "جارٍ التراجع…" : "جارٍ تسجيل القيام…";
    targets.forEach(target => {
      pendingTargets.add(target); pendingLabels.set(target, busyText);
      pendingTimers.set(target, setTimeout(() => slowNotice(target), 3000));
    });
    const originalText = button?.innerHTML;
    syncPendingDom(targets);
    if (button) {
      button.dataset.pending = "1";
      button.disabled = true;
      button.classList.add("is-pending");
      button.innerHTML = `<span class="spinner" aria-hidden="true"></span> ${esc(targets.length > 1 ? busyText : busyText)}`;
    }
    let stale = false;
    const out = await api(url, {
      ...jsonReq(method, {...body, revision: ops.revision, now: new Date().toISOString()}),
      loadingLabel: busyText,
      onError: (payload, status) => {
        if (status === 409 && payload.code === "stale_revision") {
          stale = true;
          return true;
        }
        return false;
      },
    });
    if (button) {
      delete button.dataset.pending;
      button.disabled = false;
      button.classList.remove("is-pending");
      button.innerHTML = originalText;
    }
    clearPending(targets);
    if (stale) {
      await loadOps();
      showToast("تم تحديث اللوحة من جهاز آخر — أعد المحاولة", true);
      return false;
    }
    if (out) {
      const snapshot = rememberFocus();
      const previous = new Map(allRuns().map(run => [actionTarget(run), run]));
      ops = out;
      const after = new Map(allRuns().map(run => [actionTarget(run), run]));
      const changedTargets = new Set(targets);
      for (const key of new Set([...previous.keys(), ...after.keys()])) {
        if (JSON.stringify(previous.get(key)) !== JSON.stringify(after.get(key))) changedTargets.add(key);
      }
      rowErrors.clear();
      reconcileBoard(previous, changedTargets, snapshot);
      announce(success);
      showToast(success);
      return true;
    }
    targets.forEach(target => {
      rowErrors.set(target, "فشل التسجيل — حاول مرة أخرى");
      const el = currentRunElement(target);
      if (el && !el.querySelector(".ops-row-error")) el.insertAdjacentHTML("beforeend", `<span class="ops-row-error" role="alert">فشل التسجيل — حاول مرة أخرى</span>`);
    });
    showToast("فشل التسجيل — لم تتغير اليومية", true);
    return false;
  }

  function openLine(mode, line, meta, keys) {
    const count = keys.length;
    $id("opsLineTitle").textContent = mode === "return" ? `عودة خدمات ${line}` : `قيام خدمات ${line}`;
    $id("opsLineSubmit").textContent = mode === "return" ? `عودة ${count} خدمة` : `قيام ${count} خدمة`;
    $id("opsLineMeta").textContent = [line, meta].filter(Boolean).join(" · ");
    const byTarget = Object.fromEntries(allRuns().map(run => [actionTarget(run), run]));
    $id("opsLineChecks").innerHTML = keys.map(key => {
      const run = byTarget[key] || {name: key};
      const warning = !run.head || run.count == null || run.count === "" ? " · بيانات ناقصة" : "";
      return `<label><input type="checkbox" name="lineKey" value="${esc(key)}" checked><span>${esc(runLabel(run))}${esc(warning)}</span></label>`;
    }).join("");
    $id("opsLineWarning").classList.toggle("hidden", !keys.length);
    $id("opsLineWarning").textContent = "يمكن إلغاء اختيار أي خدمة قبل التسجيل.";
    $id("opsLineForm").dataset.mode = mode;
    openModal("opsLineModal");
  }

  function openTime(target) {
    const run = allRuns().find(item => actionTarget(item) === target);
    if (!run) return;
    $id("opsTimeService").textContent = runLabel(run);
    $id("opsTimeInput").value = run.report_time || "";
    $id("opsTimeInput").dataset.hhmm = run.report_time || "";
    $id("opsTimeForm").dataset.target = target;
    const defaultScope = $id("opsTimeDefault");
    const hint = $id("opsTimeHint");
    defaultScope.disabled = !run.catalog_id;
    defaultScope.checked = Boolean(run.catalog_id);
    $id("opsTimeForm").querySelector('input[value="day"]').checked = !run.catalog_id;
    hint.textContent = run.catalog_id
      ? ""
      : "الخدمة دي مش موجودة في دليل الخدمات، فالتعديل لليوم بس. لو عايزها ميعاد ثابت أضفها من دليل الخدمات.";
    hint.classList.toggle("hidden", Boolean(run.catalog_id));
    upgradeTimeInputs($id("opsTimeModal"));
    openModal("opsTimeModal");
  }

  ACTIONS.opsUndo = (target, extra, button) =>
    mutate(`/api/ops/${day}/undo`, {key: target}, button, "تم التراجع عن آخر تغيير");
  ACTIONS.opsEditTime = target => openTime(target);

  document.addEventListener("click", event => {
    const element = event.target.closest("[data-op]");
    if (!element) return;
    if (element.dataset.op === "collapse") {
      const key = `${prefs.groupBy}:${element.dataset.group}`;
      prefs.collapsed[key] = !prefs.collapsed[key]; savePrefs(); renderBoard();
    } else if (element.dataset.op === "clear-search") {
      filters.query = ""; renderBoard();
    } else if (element.dataset.op === "clear-filters") {
      clearFilters();
    } else if (element.dataset.op === "shift") {
      activeShift = element.dataset.shift;
      renderBoard();
    } else if (element.dataset.op === "line") {
      openLine(element.dataset.mode, element.dataset.line, element.dataset.meta,
        JSON.parse(element.dataset.keys || "[]"));
    } else if (["depart", "return"].includes(element.dataset.op)) {
      if (pendingTargets.has(element.dataset.target)) return;
      mutate(`/api/ops/${day}/${element.dataset.op}`, {keys: [element.dataset.target]},
        element, element.dataset.op === "depart" ? "تم تسجيل القيام" : "تم تسجيل العودة");
    }
  });

  function clearFilters() {
    filters = {query: "", states: new Set(), types: new Set(), lines: new Set(), timeWindow: "all", attention: false}; activeShift = "all"; savePrefs(); renderBoard(); paintCounters();
  }

  $id("opsSearch").addEventListener("input", event => { filters.query = event.target.value; renderBoard(); });
  $id("opsSearch").addEventListener("keydown", event => { if (event.key === "Escape") { filters.query = ""; renderBoard(); } });
  $id("opsShiftFilter").addEventListener("change", event => { activeShift = event.target.value; savePrefs(); renderBoard(); });
  $id("opsGroupBy").addEventListener("change", event => { prefs.groupBy = event.target.value; savePrefs(); renderBoard(); });
  $id("opsAttentionToggle").addEventListener("click", () => { filters.attention = !filters.attention; savePrefs(); renderBoard(); });
  $id("opsFiltersToggle").addEventListener("click", event => {
    const panel = $id("opsFiltersPanel");
    panel.classList.toggle("hidden");
    event.currentTarget.setAttribute("aria-expanded", String(!panel.classList.contains("hidden")));
  });
  document.addEventListener("change", event => {
    if (event.target.matches("[data-filter-type]")) {
      const type = event.target.dataset.filterType;
      event.target.checked ? filters.types.add(type) : filters.types.delete(type);
      savePrefs(); renderBoard();
    } else if (event.target.id === "opsTimeWindow") {
      filters.timeWindow = event.target.value; savePrefs(); renderBoard();
    }
  });
  document.addEventListener("click", event => {
    const line = event.target.closest("[data-filter-line]");
    if (!line) return;
    const key = line.dataset.filterLine;
    filters.lines.has(key) ? filters.lines.delete(key) : filters.lines.add(key);
    savePrefs(); renderBoard();
  });
  $id("opsClear").addEventListener("click", clearFilters);
  document.querySelectorAll("[data-view]").forEach(button => button.addEventListener("click", () => { prefs.view = button.dataset.view; savePrefs(); renderBoard(); }));
  document.addEventListener("click", event => {
    const stateButton = event.target.closest("[data-filter-state]");
    if (stateButton) { const state = stateButton.dataset.filterState; filters.states.has(state) ? filters.states.delete(state) : filters.states.add(state); savePrefs(); paintCounters(); renderBoard(); return; }
    const attention = event.target.closest("[data-attention-state]");
    if (attention) { filters.states = new Set([attention.dataset.attentionState]); filters.attention = false; savePrefs(); paintCounters(); renderBoard(); }
  });
  document.addEventListener("keydown", event => {
    const typing = ["INPUT", "TEXTAREA", "SELECT"].includes(event.target.tagName) || event.target.isContentEditable;
    if (event.key === "Escape") {
      if (isModalOpen()) return;
      if (filters.query) { filters.query = ""; renderBoard(); event.preventDefault(); return; }
      const panel = $id("opsFiltersPanel"), help = $id("opsShortcutsHelp");
      if (panel && !panel.classList.contains("hidden")) { panel.classList.add("hidden"); $id("opsFiltersToggle").setAttribute("aria-expanded", "false"); event.preventDefault(); return; }
      if (help && !help.classList.contains("hidden")) { help.classList.add("hidden"); $id("opsShortcutsToggle").setAttribute("aria-expanded", "false"); event.preventDefault(); }
      return;
    }
    if (typing || isModalOpen()) return;
    // event.code عشان الكيبورد العربي: نفس الزرار بيكتب «ظ» مش «/»
    if (event.key === "/" || event.code === "Slash") { event.preventDefault(); $id("opsSearch").focus(); return; }
    if (event.key === "F6") {
      event.preventDefault();
      const zones = [$id("opsStrip"), $id("opsToolbar"), $id("opsBoard"), document.querySelector(".admin-followup")].filter(Boolean);
      keyboardZone = (keyboardZone + (event.shiftKey ? zones.length - 1 : 1)) % zones.length;
      const focusable = zones[keyboardZone].querySelector("button, input, select, summary, [tabindex]") || zones[keyboardZone];
      focusable.setAttribute("tabindex", focusable.tabIndex < 0 ? "-1" : String(focusable.tabIndex)); focusable.focus(); return;
    }
    const focused = event.target.closest?.("#opsBoard [data-run-key]");
    if (focused && ["ArrowDown", "ArrowUp"].includes(event.key)) {
      event.preventDefault();
      const rows = [...document.querySelectorAll("#opsBoard [data-run-key]")];
      const next = rows[Math.max(0, Math.min(rows.length - 1, rows.indexOf(focused) + (event.key === "ArrowDown" ? 1 : -1)))];
      setRovingFocus(next); return;
    }
    if (focused && event.key === "Enter") {
      const action = focused.querySelector(".ops-action:not([disabled])");
      if (action) { event.preventDefault(); action.click(); }
    }
    if (focused && (event.key === "F10" && event.shiftKey || event.key === "ContextMenu")) {
      event.preventDefault(); focused.querySelector(".row-menu-btn")?.click();
    }
    const groupToggle = event.target.closest?.(".ops-group-toggle");
    if (groupToggle && event.key === " ") { event.preventDefault(); groupToggle.click(); }
  });

  function setRovingFocus(el) {
    if (!el) return;
    document.querySelectorAll("#opsBoard [data-run-key]").forEach(item => { item.tabIndex = item === el ? 0 : -1; });
    el.focus({preventScroll: true});
  }

  document.addEventListener("focusin", event => {
    const rowEl = event.target.closest?.("#opsBoard [data-run-key]");
    if (rowEl) setRovingFocus(rowEl);
  });

  $id("opsShortcutsToggle").addEventListener("click", event => {
    const help = $id("opsShortcutsHelp");
    help.classList.toggle("hidden");
    event.currentTarget.setAttribute("aria-expanded", String(!help.classList.contains("hidden")));
  });
  $id("opsRefreshNow").addEventListener("click", () => loadOps());
  $id("dayPrev").addEventListener("click", () => setDay(addDays(day, -1)));
  $id("dayNext").addEventListener("click", () => setDay(addDays(day, 1)));
  $id("dayToday").addEventListener("click", () => setDay(today));
  $id("dashboardDate").addEventListener("change", event => setDay(event.target.value));
  window.addEventListener("popstate", () => {
    const value = new URLSearchParams(location.search).get("day") || today;
    setDay(value, {replace: true});
  });
  paintDayContext();

  const regularityPanel = $id("regularityPanel");
  if (prefs.collapsed.regularity === undefined) prefs.collapsed.regularity = true;
  regularityPanel.open = !prefs.collapsed.regularity;
  regularityPanel.addEventListener("toggle", () => {
    prefs.collapsed.regularity = !regularityPanel.open; savePrefs();
  });
  $id("regularitySave").addEventListener("click", () => saveRegularity());
  $id("regularityReset").addEventListener("click", () => saveRegularity(true));
  $id("regularityAddNote").addEventListener("click", () => {
    const values = regularityNoteValues();
    if (values.length >= 12) return showToast("لا يمكن إضافة أكثر من 12 ملاحظة", true);
    values.push(""); regularityNotes(values); markRegularityDirty();
    $id("regularityNotes").lastElementChild?.querySelector("input")?.focus();
  });
  $id("regularityRestoreNotes").addEventListener("click", () => {
    regularityNotes(regularity.defaults.notes); markRegularityDirty();
  });
  $id("regularityBody").addEventListener("input", event => {
    if (event.target.matches("input")) markRegularityDirty();
  });
  $id("regularityBody").addEventListener("change", event => {
    if (event.target.matches("select")) markRegularityDirty();
  });
  $id("regularityNotes").addEventListener("click", event => {
    const button = event.target.closest("[data-regularity-note]");
    if (!button) return;
    const item = button.closest("li"), all = [...item.parentElement.children], index = all.indexOf(item);
    const values = regularityNoteValues();
    if (button.dataset.regularityNote === "remove") values.splice(index, 1);
    if (button.dataset.regularityNote === "up" && index > 0) [values[index - 1], values[index]] = [values[index], values[index - 1]];
    if (button.dataset.regularityNote === "down" && index < values.length - 1) [values[index + 1], values[index]] = [values[index], values[index + 1]];
    regularityNotes(values); markRegularityDirty();
  });
  window.addEventListener("beforeunload", event => {
    if (!regularityDirty) return;
    event.preventDefault(); event.returnValue = "";
  });

  $id("opsLineForm").addEventListener("submit", event => {
    event.preventDefault();
    const keys = [...event.currentTarget.querySelectorAll("input:checked")]
      .map(input => input.value);
    if (!keys.length) return showToast("اختر خدمة واحدة على الأقل", true);
    const mode = event.currentTarget.dataset.mode;
    mutate(`/api/ops/${day}/${mode}`, {keys}, $id("opsLineSubmit"),
      mode === "depart" ? "تم تسجيل قيام الخط" : "تم تسجيل عودة الخط")
      .then(ok => { if (ok) closeModal("opsLineModal", true); });
  });

  $id("opsTimeForm").addEventListener("submit", async event => {
    event.preventDefault();
    const input = $id("opsTimeInput");
    const time = input.dataset.hhmm || parseTimeAr(input.value);
    if (!time) return showToast("اختر معادًا صحيحًا", true);
    const target = event.currentTarget.dataset.target;
    const scope = document.querySelector('input[name="opsTimeScope"]:checked').value;
    const submit = $id("opsTimeSubmit");
    const ok = await mutate(`/api/ops/${day}/time`, {key: target, time, scope}, submit, "تم تعديل المعاد", "PATCH");
    if (ok) closeModal("opsTimeModal", true);
  });

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) loadOps();
  });
  setInterval(() => { if (!document.hidden) loadOps(); }, 30000);
  setInterval(paintSync, 1000);
  setInterval(paintClock, 1000);

  await loadOps();
  await loadRegularity();
  renderAdmin(d);
})();

function renderAdmin(d) {
  const counts = d.counts || {};
  const hhmm = value => (value || "").slice(11, 16);
  const upcoming = d.upcoming || {};
  const confirm = d.confirm || {};

  $("#clockWarning").innerHTML = d.clock_warning
    ? `<div class="alert-card"><div class="alert-head">
        <span class="alert-ico">${icon("clock", "ico-lg")}</span>
        <strong>تنبيه: ساعة الجهاز</strong></div>
        <p class="muted">${esc(d.clock_warning)}</p></div>`
    : "";
  const suspension = META.rest_suspension || {};
  $("#restSuspension").innerHTML = (suspension.active || []).length
    ? `<div class="alert-card susp-banner"><div class="alert-head">
        <span class="alert-ico">${icon("block", "ico-lg")}</span>
        <strong>الراحات موقوفة: ${(suspension.types || []).map(esc).join("، ")}</strong>
        <span class="muted">من ${fmt(suspension.active[0].started_on)} — يُرفض تسجيل راحة من هذه الأنواع لأي ضابط.</span>
        <a class="mini" href="/leaves">إدارة الوقف</a></div></div>`
    : "";

  const tile = (href, label, value, cls = "") =>
    `<a class="stat stat-link ${cls}" href="${href}"><span>${label}</span><strong>${value}</strong></a>`;
  $("#dashStats").innerHTML = tile("/officers", "الضباط على القوة", counts.officers) +
    tile("/personnel", "الأفراد على القوة", counts.personnel) +
    tile("/leaves", "في راحة اليوم", counts.on_rest) +
    tile("/officers", "تنبيهات تقصيرة", counts.taqseera,
      counts.taqseera > 0 ? "stat-accent-orange" : "");
  renderAlerts(d.alerts);

  const task = (state, text, href, label) => `<li class="task task-${state}">
    <span class="status-dot ${state}" aria-hidden="true"></span>
    <span class="task-text">${text}</span>
    ${href ? `<a class="btn" href="${href}">${esc(label)}</a>` : ""}</li>`;
  const confirmTask = !confirm.confirmed && !confirm.count
    ? task("muted", "لا توجد خدمات مسجّلة في اليومية التفصيلية اليوم", "/board", "فتح اليومية")
    : !confirm.confirmed
      ? task("warn", "<b>اليومية التفصيلية لم تُؤكَّد بعد</b> — التغييرات لا تُسجَّل في سجل التغييرات قبل التأكيد", "/board", "تأكيد اليومية")
      : confirm.pending
        ? task("warn", `<b>توجد تعديلات بعد آخر تأكيد</b> (الساعة ${esc(hhmm(confirm.at))})`, "/board", "مراجعة وتأكيد")
        : task("ok", `اليومية مؤكدة الساعة ${esc(hhmm(confirm.at))}${confirm.by ? ` — ${esc(confirm.by)}` : ""}`, "/board", "عرض اليومية");
  const vacant = (upcoming.tomorrow_vacant || []).length;
  const returning = (upcoming.leaves_ending_soon || []).length;
  $("#dashTasks").innerHTML = confirmTask +
    (vacant ? task("warn", `<b>الخدمات الشاغرة غدًا: ${countLabel(vacant, "خدمة")}</b>`, "/board", "تعيين") : task("ok", "لا توجد خدمات شاغرة غدًا", "", "")) +
    (returning ? task("muted", `العائدون من الراحة خلال ${countLabel(3, "يوم")}: ${countLabel(returning, "ضابط")}`, "/leaves", "سجل الراحات") : task("muted", `لا يعود أحد من الراحة خلال ${countLabel(3, "يوم")}`, "", ""));

  const entities = {leave: "راحة", mission: "مأمورية", officer_state: "حالة ضابط", assignment: "خدمة", duty_move: "حركة ضابط/فرد", person: "بيانات فرد/ضابط"};
  const actions = {create: "إضافة", update: "تعديل", delete: "حذف"};
  const fallback = entry => `${entities[entry.entity] || "تغيير"} — ${actions[entry.action] || "تعديل"}`;
  const recent = d.recent_changes || [];
  $("#dashChanges").innerHTML = recent.length
    ? `<h4>آخر التغييرات <a href="/changes">عرض الكل</a></h4><ul class="change-list">${recent.map(entry => `<li>
        <time>${esc(fmtShort((entry.ts || "").slice(0, 10)))} ${esc(hhmm(entry.ts))}</time>
        <span>${esc(humanizeDates(entry.text || fallback(entry)))}</span>
        ${entry.edited_by ? `<em>${esc(entry.edited_by)}</em>` : ""}</li>`).join("")}</ul>`
    : `<p class="recent-empty">لا توجد تغييرات حديثة.</p>`;

  const column = (title, rows, render) => `<section class="dash-col"><h4>${title} <em>${rows.length || ""}</em></h4>
    ${rows.length ? `<ul class="dash-list">${rows.map(render).join("")}</ul>` : emptyState({compact: true, title: "لا يوجد شيء مستحق"})}</section>`;
  $("#dashUpcoming").innerHTML =
    column(`راحات ستنتهي خلال ${countLabel(3, "يوم")}`, upcoming.leaves_ending_soon || [], leave => `<li>
      <b>${esc(leave.person_role)} / ${esc(leave.person_name)}</b>
      <span>${esc(leave.type)} · يعود ${esc(dayName(leave.return_date))} ${esc(fmt(leave.return_date))}</span></li>`) +
    column(`فرق ستبدأ خلال ${countLabel(3, "يوم")}`, upcoming.courses_starting_soon || [], course => `<li>
      <b>${esc(course.officer_name)}</b><span>${esc(course.course_name)} — يبدأ ${fmt(course.start)}</span></li>`) +
    column("خدمات غدٍ ما زالت شاغرة", upcoming.tomorrow_vacant || [], vacantRun => `<li><b>${esc(vacantRun.text)}</b></li>`);
}
