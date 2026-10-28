/* الرئيسية — لوحة تشغيل الخدمات اليومية، والمتابعة الإدارية القديمة تحتها. */
(async () => {
  const d = await bootstrap();
  if (!d) return;

  let ops = null;
  const day = curDate();
  const userKey = document.getElementById("userChipWrap")?.dataset.userId || "anonymous";
  const prefKey = `opsBoardPrefs:v2:${userKey}`;
  const defaults = {view: "list", groupBy: "time", shift: "all", states: [], attention: false, collapsed: {}};
  let prefs = loadPrefs();
  let activeShift = prefs.shift || "all";
  let filters = {query: "", states: new Set(prefs.states || []), attention: Boolean(prefs.attention)};
  const pendingTargets = new Set();

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
    try { localStorage.setItem(prefKey, JSON.stringify({...prefs, shift: activeShift, states: [...filters.states], attention: filters.attention})); }
    catch (_error) { /* التخزين المحلي ممكن يكون مقفول في وضع التصفح الخاص. */ }
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
    for (const key of ["line_id", "line", "lorry", "driver", "vehicle", "warning"]) {
      if (!merged[key] && run[key]) merged[key] = run[key];
    }
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

  function paintClock() {
    const now = new Date();
    $id("opsClock").textContent = now.toLocaleTimeString("en-GB", {
      hour: "2-digit", minute: "2-digit", second: "2-digit",
    });
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

  function runContext(run) { return [run.line, run.lorry ? `لوري ${run.lorry}` : "", run.category].filter(Boolean).join(" · ") || "بلا خط"; }

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

    return `<article class="ops-card ops-state-${state}" data-run-key="${esc(target)}" data-state="${state}"
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
        <span class="ops-status-label">${statusText[state]}</span>
      </div>
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
  function searchText(run) { return normaliseArabic([run.name, run.head, run.line, run.lorry, run.weapon, run.report_text, run.report_time, run.category].join(" ")); }
  function matchesFilters(run) {
    const state = displayState(run);
    if (activeShift !== "all" && run.shift !== activeShift) return false;
    if (filters.states.size && !filters.states.has(state)) return false;
    if (!filters.states.size && state === "back") return false;
    if (filters.attention && !["late", "prep", "carried"].includes(state)) return false;
    const terms = normaliseArabic(filters.query).split(/\s+/).filter(Boolean);
    return terms.every(term => searchText(run).includes(term));
  }

  function groupRuns(runs) {
    if (prefs.groupBy === "none") return [{id: "all", title: "كل الخدمات", runs}];
    const groups = new Map();
    for (const run of runs) {
      const id = prefs.groupBy === "line" ? (run.line_id || "none") : (run.report_time || "none");
      const title = prefs.groupBy === "line" ? (run.line || "بلا خط") : (run.report_text || run.report_time || "بدون معاد");
      if (!groups.has(id)) groups.set(id, {id, title, runs: []});
      groups.get(id).runs.push(run);
    }
    return [...groups.values()].sort((a, b) => prefs.groupBy === "time"
      ? (minutes(a.runs[0].report_time) ?? 9999) - (minutes(b.runs[0].report_time) ?? 9999)
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
    return `<tr class="ops-row ops-state-${state}" data-run-key="${esc(target)}" aria-busy="${pendingTargets.has(target)}">
      <td class="ops-row-status"><span>${statusText[state]}</span></td>
      <th scope="row"><strong>${esc(run.name || "خدمة")}</strong><small>${esc(runContext(run))}</small></th>
      <td class="ops-row-time">${esc(run.report_text || run.report_time || "—")}</td>
      <td>${esc(shiftText[run.shift] || run.shift || "—")}</td>
      <td class="ops-row-head">${esc(run.head || "غير مسجّل")}</td>
      <td>${esc(run.count == null || run.count === "" ? "—" : `${run.count}${run.weapon ? ` · ${run.weapon}` : ""}`)}</td>
      <td class="ops-row-action">${action ? `<button type="button" class="primary ops-action" data-op="${action}" data-target="${esc(target)}">${actionLabel(action)}</button>` : `<span class="ops-times">${esc(run.back_at?.slice(11, 16) || "")}</span>`}${menu}</td>
    </tr>`;
  }

  function groupMarkup(group) {
    const eligibleDepart = group.runs.filter(run => ["upcoming", "prep", "late"].includes(displayState(run)));
    const eligibleReturn = group.runs.filter(run => ["out", "carried"].includes(displayState(run)));
    const collapsed = Boolean(prefs.collapsed[`${prefs.groupBy}:${group.id}`]);
    const actions = [];
    if (eligibleDepart.length) actions.push(`<button type="button" class="btn" data-op="line" data-mode="depart" data-line="${esc(group.title)}" data-meta="" data-keys="${esc(JSON.stringify(eligibleDepart.map(actionTarget)))}">قيام الكل (${eligibleDepart.length})</button>`);
    if (eligibleReturn.length) actions.push(`<button type="button" class="btn ok" data-op="line" data-mode="return" data-line="${esc(group.title)}" data-meta="" data-keys="${esc(JSON.stringify(eligibleReturn.map(actionTarget)))}">عودة الكل (${eligibleReturn.length})</button>`);
    const body = viewMode() === "cards" ? `<div class="ops-grid">${group.runs.map(card).join("")}</div>` : `<div class="ops-table-wrap"><table class="ops-list"><thead><tr><th>الحالة</th><th>الخدمة</th><th>المعاد</th><th>الفترة</th><th>القائم بها</th><th>القوام</th><th>الإجراء</th></tr></thead><tbody>${group.runs.map(row).join("")}</tbody></table></div>`;
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
    $id("opsClear").classList.toggle("hidden", !(filters.query || filters.states.size || filters.attention || activeShift !== "all"));
  }

  async function loadOps() {
    const next = await api(`/api/ops/${day}`, {noLoader: true});
    if (!next) return;
    // التحديث الدوري مايعيدش رسم اللوحة لو مفيش حاجة اتغيّرت — إعادة الرسم
    // بتقفل أي قايمة ⋯ مفتوحة وبتضيّع مكان التركيز من الكيبورد كل 30 ثانية.
    // التلميحات (جهّز/متأخرة) بتتحسب على السيرفر بالدقيقة، فبنقارنها برضه.
    const sig = data => JSON.stringify([data.revision, data.counters, data.next?.key]);
    const changed = !ops || sig(ops) !== sig(next);
    ops = next;
    if (!changed) return;
    paintCounters();
    renderBoard();
  }

  async function mutate(url, body, button, success) {
    if (button?.dataset.pending === "1") return;
    const targets = body.keys || (body.key ? [body.key] : []);
    targets.forEach(target => pendingTargets.add(target));
    const originalText = button?.innerHTML;
    if (button) {
      button.dataset.pending = "1";
      button.disabled = true;
      button.classList.add("is-pending");
      button.innerHTML = '<span class="spinner" aria-hidden="true"></span> جارٍ التنفيذ…';
    }
    targets.forEach(target => pendingTargets.delete(target));
    let stale = false;
    const out = await api(url, {
      ...jsonReq("POST", {...body, revision: ops.revision, now: new Date().toISOString()}),
      loadingLabel: "جارٍ تنفيذ الإجراء…",
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
    if (stale) {
      await loadOps();
      showToast("تم تحديث اللوحة من جهاز آخر — أعد المحاولة", true);
      return false;
    }
    if (out) {
      ops = out;
      paintCounters();
      renderBoard();
      announce(success);
      showToast(success);
      return true;
    }
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
    filters = {query: "", states: new Set(), attention: false}; activeShift = "all"; savePrefs(); renderBoard(); paintCounters();
  }

  $id("opsSearch").addEventListener("input", event => { filters.query = event.target.value; renderBoard(); });
  $id("opsSearch").addEventListener("keydown", event => { if (event.key === "Escape") { filters.query = ""; renderBoard(); } });
  $id("opsShiftFilter").addEventListener("change", event => { activeShift = event.target.value; savePrefs(); renderBoard(); });
  $id("opsGroupBy").addEventListener("change", event => { prefs.groupBy = event.target.value; savePrefs(); renderBoard(); });
  $id("opsAttentionToggle").addEventListener("click", () => { filters.attention = !filters.attention; savePrefs(); renderBoard(); });
  $id("opsClear").addEventListener("click", clearFilters);
  document.querySelectorAll("[data-view]").forEach(button => button.addEventListener("click", () => { prefs.view = button.dataset.view; savePrefs(); renderBoard(); }));
  document.addEventListener("click", event => {
    const stateButton = event.target.closest("[data-filter-state]");
    if (stateButton) { const state = stateButton.dataset.filterState; filters.states.has(state) ? filters.states.delete(state) : filters.states.add(state); savePrefs(); paintCounters(); renderBoard(); return; }
    const attention = event.target.closest("[data-attention-state]");
    if (attention) { filters.states = new Set([attention.dataset.attentionState]); filters.attention = false; savePrefs(); paintCounters(); renderBoard(); }
  });
  document.addEventListener("keydown", event => {
    if (event.key === "/" && !["INPUT", "TEXTAREA", "SELECT"].includes(event.target.tagName)) { event.preventDefault(); $id("opsSearch").focus(); }
    if (event.key === "Escape" && document.activeElement === $id("opsSearch") && filters.query) { filters.query = ""; renderBoard(); }
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
    if (submit.dataset.pending === "1") return;
    const originalText = submit.innerHTML;
    submit.dataset.pending = "1";
    submit.disabled = true;
    submit.classList.add("is-pending");
    submit.innerHTML = '<span class="spinner" aria-hidden="true"></span> جارٍ التنفيذ…';
    const out = await api(`/api/ops/${day}/time`, {
      ...jsonReq("PATCH", {key: target, time, scope, revision: ops.revision}),
      loadingLabel: "جارٍ تنفيذ تعديل المعاد…",
      onError: (payload, status) => {
        // 409 تاني غير «نسخة قديمة» (زي «الخدمة غير موجودة») رسالته بتظهر عادي
        if (status === 409 && payload.code === "stale_revision") {
          loadOps();
          showToast("تم تحديث اللوحة من جهاز آخر — أعد المحاولة", true);
          return true;
        }
        return false;
      },
    });
    if (out) {
      ops = out;
      paintCounters();
      renderBoard();
      closeModal("opsTimeModal", true);
      announce("تم تعديل المعاد");
      showToast("تم تعديل المعاد");
    }
    delete submit.dataset.pending;
    submit.disabled = false;
    submit.classList.remove("is-pending");
    submit.innerHTML = originalText;
  });

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) loadOps();
  });
  setInterval(() => { if (!document.hidden) loadOps(); }, 30000);
  setInterval(paintClock, 1000);

  await loadOps();
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
