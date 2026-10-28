/* قادة الأهداف الثابتون — كشف واحد يُحفظ كوحدة ذرية بتاريخ سريان. */
let TARGET_COMMANDERS = null;
let TARGET_COMMANDERS_DAY = "";

const officerLabel = officer => {
  const post = officer.post ? ` — ${officer.post}` : " — بلا منصب";
  return `${officer.role ? officer.role + "/ " : ""}${officer.name}${post}`;
};

function commanderCell(commanders) {
  if (!commanders.length) return `<span class="target-vacant">شاغر</span>`;
  return commanders.map(person => `<div class="target-current-person">
    <b>${esc(person.name)}</b><span>${esc(person.role || "")}</span>
  </div>`).join("");
}

function optionsFor(selected) {
  return [`<option value="">— شاغر (بدون قائد) —</option>`,
    ...TARGET_COMMANDERS.officers.map(officer => `<option value="${esc(officer.id)}"
      ${officer.id === selected ? "selected" : ""}>${esc(officerLabel(officer))}</option>`)
  ].join("");
}

function targetRow(target) {
  const selected = target.commanders[0]?.id || "";
  return `<tr data-target="${esc(target.name)}">
    <td class="target-name"><strong>${esc(target.name)}</strong><span>${esc(target.post)}</span></td>
    <td class="target-current">${commanderCell(target.commanders)}</td>
    <td class="target-choice">
      <select class="select select-officer target-commander-select" aria-label="القائد الجديد لـ ${esc(target.name)}">
        ${optionsFor(selected)}
      </select>
    </td>
    <td class="target-row-state"><span class="chip done">ثابت</span></td>
  </tr>`;
}

function currentIds(target) {
  return target.commanders.map(person => person.id).sort();
}

function selectedMap() {
  return Object.fromEntries($$("#targetCommanderRows tr[data-target]").map(row => [
    row.dataset.target, row.querySelector("select").value || null,
  ]));
}

function syncTargetCommanderState() {
  if (!TARGET_COMMANDERS) return;
  const selected = selectedMap();
  const used = {};
  Object.values(selected).filter(Boolean).forEach(id => { used[id] = (used[id] || 0) + 1 });
  let changed = 0, duplicate = false, occupied = 0;

  for (const target of TARGET_COMMANDERS.targets) {
    const row = [...$$("#targetCommanderRows tr[data-target]")]
      .find(item => item.dataset.target === target.name);
    const next = selected[target.name];
    const current = currentIds(target);
    const same = current.length === (next ? 1 : 0) && (!next || current[0] === next);
    const repeated = next && used[next] > 1;
    const state = row.querySelector(".target-row-state");
    row.classList.toggle("is-changed", !same);
    row.classList.toggle("has-error", !!repeated);
    if (repeated) {
      duplicate = true;
      state.innerHTML = `<span class="chip err">مكرر</span><small>الضابط مختار لهدف آخر</small>`;
    } else if (same) {
      state.innerHTML = `<span class="chip done">ثابت</span>`;
    } else if (!next) {
      state.innerHTML = `<span class="chip soon">إخلاء</span>`;
      changed += 1;
    } else {
      const officer = TARGET_COMMANDERS.officers.find(item => item.id === next);
      const move = officer?.post && officer.post !== target.post
        ? `<small>من: ${esc(officer.post)}</small>` : "";
      state.innerHTML = `<span class="chip soon">تغيير</span>${move}`;
      changed += 1;
    }
    if (next) occupied += 1;
  }

  const historical = TARGET_COMMANDERS_DAY < META.today;
  $("#saveTargetCommanders").disabled = historical || duplicate || changed === 0;
  $("#targetCommandersSummary").innerHTML = historical
    ? `<span class="chip w">عرض تاريخي</span> هذا اليوم للقراءة فقط.`
    : duplicate ? `<span class="target-commanders-error">يجب إزالة التعيين المكرر قبل الحفظ.</span>`
    : `${occupied} هدف له قائد من أصل ${TARGET_COMMANDERS.targets.length}`
      + (changed ? ` — <b>${changed} تغيير في انتظار الحفظ</b>` : "");
}

function renderTargetCommanders() {
  const rows = $("#targetCommanderRows");
  rows.innerHTML = TARGET_COMMANDERS.targets.map(targetRow).join("");
  upgradeSelects(rows);
  syncTargetCommanderState();
}

async function loadTargetCommanders(day) {
  const data = await api(`/api/target-commanders/${encodeURIComponent(day)}`);
  if (!data) return false;
  TARGET_COMMANDERS = data;
  TARGET_COMMANDERS_DAY = day;
  $("#targetCommandersDay").value = day;
  renderTargetCommanders();
  return true;
}

$("#targetCommanderRows").addEventListener("change", event => {
  if (event.target.matches(".target-commander-select")) syncTargetCommanderState();
});

$("#targetCommandersDay").addEventListener("change", async event => {
  const next = event.target.value;
  if (!next) return;
  const dirty = !$("#saveTargetCommanders").disabled && TARGET_COMMANDERS_DAY;
  if (dirty && !(await confirmDialog({title: "تعيينات لم تُحفظ",
      body: "هناك تعيينات لم تُحفظ على هذا اليوم. هل تريد تركها والانتقال لتاريخ آخر؟",
      confirmLabel: "ترك التعيينات", danger: true}))) {
    event.target.value = TARGET_COMMANDERS_DAY;
    return;
  }
  await loadTargetCommanders(next);
});

$("#reloadTargetCommanders").onclick = () => loadTargetCommanders(TARGET_COMMANDERS_DAY);

$("#saveTargetCommanders").onclick = async () => {
  const out = await api(`/api/target-commanders/${encodeURIComponent(TARGET_COMMANDERS_DAY)}`,
    jsonReq("PUT", {assignments: selectedMap(), revision: TARGET_COMMANDERS.revision}));
  if (!out) return;
  TARGET_COMMANDERS = out;
  renderTargetCommanders();
  showToast(out.changed.length ? `تم حفظ ${countLabel(out.changed.length, "تغيير")}`
                               : "لا توجد تغييرات للحفظ");
};

(async () => {
  const boot = await bootstrap();
  if (!boot) return;
  await loadTargetCommanders(META.today || curDate());
})();
