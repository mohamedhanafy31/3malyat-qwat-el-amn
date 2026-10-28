/* الرئيسية — لوحة تشغيل الخدمات اليومية، والمتابعة الإدارية القديمة تحتها. */
(async () => {
  const d = await bootstrap();
  if (!d) return;

  let ops = null;
  const day = curDate();
  let activeShift = new Date().getHours() < 15 ? "am" : "pm";

  const $id = id => document.getElementById(id);
  const shiftText = {am: "صباحية", pm: "ليلية"};
  const statusText = {upcoming: "قادمة", out: "بالخارج", back: "عادت"};
  const stateClass = {upcoming: "soon", out: "on", back: "done"};

  const runLabel = run =>
    `${run.name || "الخدمة"} — ${shiftText[run.shift] || run.shift || ""}`;
  const actionTarget = run => run.ref || run.key;
  const runIdentity = run => actionTarget(run);
  const minutes = time => {
    if (!time) return null;
    const [hour, minute] = time.split(":").map(Number);
    return hour * 60 + minute;
  };

  // المرجع المترحّل أهم من المفتاح؛ المفتاح وحده ممكن يطابق تشغيل النهاردة.
  function uniqueRuns(runs) {
    const seen = new Set();
    return runs.filter(run => {
      const id = runIdentity(run);
      if (seen.has(id)) return false;
      seen.add(id);
      return true;
    });
  }

  function todayRuns() {
    if (!ops) return [];
    const runs = [...(ops.groups.officers || [])];
    for (const block of [ops.groups.basic?.am, ops.groups.basic?.pm,
      ops.groups.emergency]) {
      runs.push(...(block?.single || []));
      for (const line of block?.lines || []) runs.push(...(line.runs || []));
    }
    return uniqueRuns(runs);
  }

  function allRuns() {
    return uniqueRuns([...(ops?.carried || []), ...todayRuns()]);
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
      ["upcoming", "قادمة"], ["prep", "جهّز"], ["late", "متأخرة"],
      ["out", "بالخارج"], ["back", "عادت"], ["carried", "مترحّلة"],
    ];
    $id("opsCounters").innerHTML = items.map(([key, label]) => `
      <div class="ops-counter ops-counter-${key}${counters[key] ? "" : " ops-counter-zero"}">
        <b>${counters[key] ?? 0}</b><span>${label}</span>
      </div>`).join("");
  }

  function carriedMeta(run) {
    if (!run.day) return "";
    const time = run.out_at ? run.out_at.slice(11, 16) : "—";
    return `خرجت يوم ${dayName(run.day)} ${fmtShort(run.day)} الساعة ${time}`;
  }

  function card(run, compact = false) {
    const state = run.state || "upcoming";
    const action = state === "upcoming" ? "قيام" : state === "out" ? "عودة" : "";
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
           data-op="${state === "out" ? "return" : "depart"}"
           data-target="${esc(target)}"
           aria-label="${action}: ${esc(runLabel(run))}">${action}</button>`
      : `<span class="ops-times">خرج ${esc(run.out_at?.slice(11, 16) || "—")}
          · عاد ${esc(run.back_at?.slice(11, 16) || "—")}</span>`;
    const menu = rowMenu([
      undoable ? {label: "تراجع", action: "opsUndo", id: target, danger: true} : null,
      {label: "تعديل المعاد", action: "opsEditTime", id: target},
    ], {label: `إجراءات ${runLabel(run)}`});

    return `<article class="ops-card ops-state-${state}
        ${run.hint ? `ops-hint-${run.hint}` : ""}${compact ? " ops-card-compact" : ""}">
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
        ${run.hint ? `<span class="chip ${run.hint === "late" ? "err" : "soon"}">
          ${run.hint === "late" ? "متأخرة" : "جهّز"}
        </span>` : ""}
      </div>
      <div class="ops-card-detail">
        <span title="${esc(details)}">${esc(details)}</span>
        ${run.day ? `<span class="ops-carried-meta">${esc(carriedMeta(run))}</span>` : ""}
      </div>
      <div class="ops-card-foot">
        ${run.hint ? `<span class="ops-state-text">${statusText[state]}</span>`
          : `<span class="chip ${stateClass[state]}">${statusText[state]}</span>`}
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

  function lineBlock(line, options = {}) {
    const runs = line.runs || [];
    const upcoming = runs.filter(run => run.state === "upcoming");
    const out = runs.filter(run => run.state === "out");
    const mode = options.forceMode || null;
    const actions = mode === "return" ? [{mode: "return", label: "عودة الخط", runs: out}]
      : mode === "depart" ? [{mode: "depart", label: "قيام الخط", runs: upcoming}]
      : upcoming.length && out.length
        ? [{mode: "depart", label: `قيام المتبقي (${upcoming.length})`, runs: upcoming},
           {mode: "return", label: `عودة القائم (${out.length})`, runs: out}]
        : upcoming.length ? [{mode: "depart", label: "قيام الخط", runs: upcoming}]
        : out.length ? [{mode: "return", label: "عودة الخط", runs: out}] : [];
    const buttons = actions.map(action => `<button type="button" class="btn ${action.mode === "return" ? "ok" : ""}"
      aria-label="${action.label}: ${esc(line.line || "خط سير")}"
      data-op="line" data-mode="${action.mode}"
      data-line="${esc(line.line || "خط سير")}"
      data-meta="${esc(lineMetaText(line))}"
      data-keys="${esc(JSON.stringify(action.runs.map(run => actionTarget(run))))}">${action.label}</button>`).join("");

    return `<section class="ops-line">
      <header class="ops-line-head">
        <div><h3>${esc(line.line || "خط سير")}</h3><p>${lineMeta(line)}</p></div>
        <div class="ops-line-actions">${buttons || '<span class="ops-line-idle">لا توجد حركة</span>'}</div>
      </header>
      <div class="ops-grid">${runs.map(run => card(run)).join("")}</div>
    </section>`;
  }

  function group(title, block, options = {}) {
    const singles = block?.single || [];
    const lines = block?.lines || [];
    const content = [
      ...lines.map(line => lineBlock(line)),
      singles.length ? `<div class="ops-grid">${singles.map(run => card(run)).join("")}</div>` : "",
    ].join("");
    return `<section class="ops-group" aria-labelledby="${options.id}">
      <div class="ops-group-title"><h2 id="${options.id}">${title}</h2>${options.switch || ""}</div>
      ${content || `<p class="ops-empty">لا توجد خدمات في هذه المجموعة.</p>`}
    </section>`;
  }

  function outSection() {
    const outRuns = todayRuns().filter(run => run.state === "out");
    if (!outRuns.length) return "";

    const lineRuns = new Map();
    const standalone = [];
    for (const run of outRuns) {
      if (!run.line_id) {
        standalone.push(run);
        continue;
      }
      const line = lineRuns.get(run.line_id) || {
        line: run.line, lorry: run.lorry, driver: run.driver,
        vehicle: run.vehicle, warning: run.warning, runs: [],
      };
      line.runs.push(run);
      lineRuns.set(run.line_id, line);
    }
    const lines = [...lineRuns.values()].map(line => lineBlock(line, {forceMode: "return"}));
    if (standalone.length) {
      lines.push(`<div class="ops-grid">${standalone.map(run => card(run)).join("")}</div>`);
    }
    return `<section class="ops-out" aria-labelledby="opsOutTitle">
      <div class="ops-section-title"><h2 id="opsOutTitle">بالخارج</h2>
        <span>${countLabel(outRuns.length, "خدمة")}</span></div>
      ${lines.join("")}
    </section>`;
  }

  function renderBoard() {
    const current = allRuns();
    const nowRuns = current.filter(run => run.hint === "prep" || run.hint === "late")
      .sort((a, b) => (a.hint === "late" ? 0 : 1) - (b.hint === "late" ? 0 : 1) ||
        (minutes(a.report_time) ?? 9999) - (minutes(b.report_time) ?? 9999));
    const carried = ops.carried || [];
    const switcher = `<div class="ops-shift-switch" role="group" aria-label="فترة الخدمات الأساسية">
      <button type="button" class="${activeShift === "am" ? "selected" : ""}"
        data-op="shift" data-shift="am">صباحية</button>
      <button type="button" class="${activeShift === "pm" ? "selected" : ""}"
        data-op="shift" data-shift="pm">ليلية</button>
    </div>`;
    const nowSection = nowRuns.length ? `<section class="ops-now" aria-labelledby="opsNowTitle">
      <div class="ops-section-title"><h2 id="opsNowTitle">الآن</h2>
        <span>${countLabel(nowRuns.length, "خدمة")} تحتاج انتباهًا</span></div>
      <div class="ops-grid">${nowRuns.map(run => card(run, true)).join("")}</div>
    </section>` : "";
    const carriedSection = carried.length ? `<section class="ops-carried" aria-labelledby="opsCarriedTitle">
      <div class="ops-section-title"><h2 id="opsCarriedTitle">مترحّلة</h2>
        <span>خرجت في يوم سابق ولم تعد</span></div>
      <div class="ops-grid">${carried.map(run => card(run)).join("")}</div>
    </section>` : "";

    $id("opsBoard").setAttribute("aria-busy", "false");
    $id("opsBoard").innerHTML = [
      nowSection,
      carriedSection,
      outSection(),
      group("خدمات الضباط الأساسية", {single: ops.groups.officers}, {id: "opsOfficersTitle"}),
      group("الخدمات الأساسية", ops.groups.basic?.[activeShift],
        {id: "opsBasicTitle", switch: switcher}),
      group("الخدمات الطارئة", ops.groups.emergency, {id: "opsEmergencyTitle"}),
    ].join("");
    paintClock();
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
    if (button) {
      button.dataset.pending = "1";
      button.disabled = true;
      button.classList.add("is-pending");
    }
    let stale = false;
    const out = await api(url, {
      ...jsonReq("POST", {...body, revision: ops.revision, now: new Date().toISOString()}),
      noLoader: true,
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
    }
    if (stale) {
      await loadOps();
      showToast("تم تحديث اللوحة من جهاز آخر — أعد المحاولة", true);
      return;
    }
    if (out) {
      ops = out;
      paintCounters();
      renderBoard();
      announce(success);
      showToast(success);
    }
  }

  function openLine(mode, line, meta, keys) {
    $id("opsLineTitle").textContent = mode === "return" ? "عودة الخط" : "قيام الخط";
    $id("opsLineSubmit").textContent = mode === "return" ? "عودة الخط" : "قيام الخط";
    $id("opsLineMeta").textContent = [line, meta].filter(Boolean).join(" · ");
    const byTarget = Object.fromEntries(allRuns().map(run => [actionTarget(run), run]));
    $id("opsLineChecks").innerHTML = keys.map(key => `
      <label><input type="checkbox" name="lineKey" value="${esc(key)}" checked>
        <span>${esc(runLabel(byTarget[key] || {name: key}))}</span>
      </label>`).join("");
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
    upgradeTimeInputs($id("opsTimeModal"));
    openModal("opsTimeModal");
  }

  ACTIONS.opsUndo = (target, extra, button) =>
    mutate(`/api/ops/${day}/undo`, {key: target}, button, "تم التراجع عن آخر تغيير");
  ACTIONS.opsEditTime = target => openTime(target);

  document.addEventListener("click", event => {
    const element = event.target.closest("[data-op]");
    if (!element) return;
    if (element.dataset.op === "shift") {
      activeShift = element.dataset.shift;
      renderBoard();
    } else if (element.dataset.op === "line") {
      openLine(element.dataset.mode, element.dataset.line, element.dataset.meta,
        JSON.parse(element.dataset.keys || "[]"));
    } else if (["depart", "return"].includes(element.dataset.op)) {
      mutate(`/api/ops/${day}/${element.dataset.op}`, {keys: [element.dataset.target]},
        element, element.dataset.op === "depart" ? "تم تسجيل القيام" : "تم تسجيل العودة");
    }
  });

  $id("opsLineForm").addEventListener("submit", event => {
    event.preventDefault();
    const keys = [...event.currentTarget.querySelectorAll("input:checked")]
      .map(input => input.value);
    if (!keys.length) return showToast("اختر خدمة واحدة على الأقل", true);
    const mode = event.currentTarget.dataset.mode;
    mutate(`/api/ops/${day}/${mode}`, {keys}, $id("opsLineSubmit"),
      mode === "depart" ? "تم تسجيل قيام الخط" : "تم تسجيل عودة الخط")
      .then(() => closeModal("opsLineModal", true));
  });

  $id("opsTimeForm").addEventListener("submit", async event => {
    event.preventDefault();
    const input = $id("opsTimeInput");
    const time = input.dataset.hhmm || parseTimeAr(input.value);
    if (!time) return showToast("اختر معادًا صحيحًا", true);
    const target = event.currentTarget.dataset.target;
    const scope = document.querySelector('input[name="opsTimeScope"]:checked').value;
    const out = await api(`/api/ops/${day}/time`, {
      ...jsonReq("PATCH", {key: target, time, scope, revision: ops.revision}),
      noLoader: true,
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
