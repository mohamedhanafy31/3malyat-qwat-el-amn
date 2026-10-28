=== REPORT ===

## 1. Information architecture

### Current structure

The page currently contains:

- A sticky clock/next-run/counter strip ([dashboard.html:9](</media/hanafy/aa9ee400-c081-4d3b-b831-a2a8c83c9f44/personal/سيستم المعسكر/prototype/personnel_system/templates/pages/dashboard.html:9>)).
- A single generated board container ([dashboard.html:15](</media/hanafy/aa9ee400-c081-4d3b-b831-a2a8c83c9f44/personal/سيستم المعسكر/prototype/personnel_system/templates/pages/dashboard.html:15>)).
- A collapsed administrative section below it, which should remain secondary ([dashboard.html:18](</media/hanafy/aa9ee400-c081-4d3b-b831-a2a8c83c9f44/personal/سيستم المعسكر/prototype/personnel_system/templates/pages/dashboard.html:18>)).

`renderBoard()` duplicates runs into “الآن”, “بالخارج”, and their organizational category, then renders every occurrence as a card ([dashboard.js:245](</media/hanafy/aa9ee400-c081-4d3b-b831-a2a8c83c9f44/personal/سيستم المعسكر/prototype/personnel_system/static/js/dashboard.js:245>), [dashboard.js:268](</media/hanafy/aa9ee400-c081-4d3b-b831-a2a8c83c9f44/personal/سيستم المعسكر/prototype/personnel_system/static/js/dashboard.js:268>)). This is the main organizational weakness: the officer encounters the same conceptual run in multiple visual zones.

### Recommendation

Make the page a single operational worklist with three layers:

1. **Sticky command center**
   - Current time.
   - Next service and countdown.
   - “آخر تحديث 10:32:14” sync health.
   - Clickable state counters.

2. **Sticky work controls**
   - Search.
   - «تحتاج إجراء الآن».
   - Shift selector.
   - «فلاتر».
   - Group-by selector.
   - List/cards toggle.
   - A visible «مسح الفلاتر» only when filters are active.

3. **One canonical worklist**
   - Default: compact list grouped by report time.
   - Show each run exactly once.
   - Returned runs hidden by default but accessible through the «عادت» counter.
   - Carried runs remain visible at the top until returned.
   - Administrative follow-up remains collapsed at the bottom.

Replace the full duplicate “الآن” cards with an **attention navigator**, for example:

> إجراء الآن: 3 متأخرة · 6 تجهّز · 2 مترحّلة

Each number filters and jumps to the canonical rows; it does not create duplicate cards.

Recommended default scope:

- States: `upcoming + out + carried`.
- Returned: hidden.
- Shift: both.
- Time window: all remaining today.
- Group: report time.
- View: compact list.

This default answers the duty officer’s three immediate questions: “What is late?”, “What goes next?”, and “What is still outside?”

---

## 2. Filtering

The current counters are non-interactive `<div>` elements ([dashboard.js:86](</media/hanafy/aa9ee400-c081-4d3b-b831-a2a8c83c9f44/personal/سيستم المعسكر/prototype/personnel_system/static/js/dashboard.js:86>)). The AM/PM switch affects only the basic-services section, rather than acting as a board-wide filter ([dashboard.js:251](</media/hanafy/aa9ee400-c081-4d3b-b831-a2a8c83c9f44/personal/سيستم المعسكر/prototype/personnel_system/static/js/dashboard.js:251>)).

### Recommended filter model

Use OR within one category and AND between categories:

- State:
  - قادمة
  - تجهّز
  - متأخرة
  - بالخارج
  - عادت
  - مترحّلة

- Shift:
  - الكل
  - صباحية
  - ليلية

- Type:
  - ضباط
  - أساسية
  - طارئة
  - مناسبة/قسم خاص

- Line/lorry:
  - Individual line chips if there are few.
  - Searchable multi-select if there are many.
  - «بلا خط» for standalone services.

- Time window:
  - كل اليوم
  - خلال ساعتين
  - خلال 4 ساعات
  - بدون معاد

- «تحتاج إجراء الآن»:
  - Recommended definition: `late OR prep OR carried`.
  - Do not include every ordinary “out” run; “بالخارج” already has its own filter.
  - The backend already exposes the configurable preparation window as `prep_minutes` ([ops_board.py:364](</media/hanafy/aa9ee400-c081-4d3b-b831-a2a8c83c9f44/personal/سيستم المعسكر/prototype/personnel_system/backend/ops_board.py:364>)).

### Presentation

- Turn the six counters into real `<button aria-pressed>` filter chips.
- Keep common controls visible: state, shift, search.
- Put type, line, and time window in a compact «فلاتر» popover.
- Display «فلاتر نشطة: 3» on that button.
- Show visible/total counts where useful: `بالخارج 8/15`.

### Search behavior

Search should be client-side and immediate across:

- Service name.
- Responsible person.
- Line and lorry.
- Section/occasion.
- Weapon.
- Report time.

Normalize Arabic variants and diacritics before matching. Treat whitespace-separated terms as AND terms, so `فيصل 8` finds eight-o’clock runs on Faisal line.

Behavior:

- `/` focuses search.
- `Escape` clears it.
- Never silently clear other filters.
- Empty result text should explain the active scope:
  - «لا توجد نتائج ضمن: ليلية + بالخارج».
  - Offer «مسح البحث» and «مسح كل الفلاتر».
- Do not persist the search string across page loads; a forgotten query is too easy to miss.

### Persistence

Persist the following in `localStorage`:

- List/cards view.
- Group-by choice.
- Shift/type/line/time filters.
- Whether returned runs are shown.
- Collapsed groups.

Use a versioned per-user key:

```text
opsBoardPrefs:v2:<stable-user-id>
```

The current base markup exposes username and role, but not a stable user ID ([base.html:32](</media/hanafy/aa9ee400-c081-4d3b-b831-a2a8c83c9f44/personal/سيستم المعسكر/prototype/personnel_system/templates/base.html:32>)). Recommendation: expose `data-user-id="{{ current_user.id }}"`; username is an acceptable temporary fallback but may change.

---

## 3. Group-by

### Options

Provide a single group selector:

1. **حسب المعاد — default**
2. حسب الخط/اللوري
3. حسب القسم/المناسبة
4. حسب الحالة
5. بدون تجميع

### Time grouping

Use exact operational slots rather than vague periods:

- `8ص — 14 خدمة`
- `2م — 6 خدمات`
- `8م — 19 خدمة`
- `بدون معاد — 2`

Sort slots chronologically, but keep carried runs first. Late rows remain visibly late inside their original time group.

### Line/lorry grouping

Each header should show:

- Line name.
- Lorry/driver/vehicle metadata.
- Visible count and state breakdown.
- «قيام المتبقي (N)».
- «عودة القائم (N)».

The current line blocks already calculate separate upcoming/out actions ([dashboard.js:175](</media/hanafy/aa9ee400-c081-4d3b-b831-a2a8c83c9f44/personal/سيستم المعسكر/prototype/personnel_system/static/js/dashboard.js:175>)), so this behavior should be generalized rather than rewritten.

One current structural limitation: line metadata lives on the line group, while `outSection()` tries to reconstruct it from individual runs ([dashboard.js:216](</media/hanafy/aa9ee400-c081-4d3b-b831-a2a8c83c9f44/personal/سيستم المعسكر/prototype/personnel_system/static/js/dashboard.js:216>)). Either preserve context while flattening client-side or expose a public `line_meta` object on every run.

### Section/occasion grouping

Examples:

- خدمات الضباط الأساسية
- الخدمات الأساسية
- الخدمات الطارئة
- خدمات مباراة المصري

Backend support is needed here. Custom sections retain their names in `counts.build()` ([counts.py:265](</media/hanafy/aa9ee400-c081-4d3b-b831-a2a8c83c9f44/personal/سيستم المعسكر/prototype/personnel_system/backend/counts.py:265>)), but `build_ops` flattens all custom-section rows into the emergency array without carrying the section name ([ops_board.py:284](</media/hanafy/aa9ee400-c081-4d3b-b831-a2a8c83c9f44/personal/سيستم المعسكر/prototype/personnel_system/backend/ops_board.py:284>)).

Recommended payload fields:

```json
{
  "types": ["emergency", "special"],
  "section_id": "special:match-2026-10-28",
  "section_name": "خدمات مباراة المصري",
  "section_kind": "special"
}
```

Use arrays for `types`, because a shared run can currently belong to more than one group.

### State grouping

Use a mutually exclusive display precedence:

1. مترحّلة
2. متأخرة
3. تجهّز
4. بالخارج
5. قادمة
6. عادت

This avoids showing one upcoming run simultaneously under “قادمة” and “متأخرة”.

### Collapsible group header

Each header should contain:

- Chevron and accessible expand/collapse button.
- Group title.
- `visible/total` count.
- Small textual state summary.
- Eligible bulk actions.

Persist collapsed state by group-by mode and group ID. Do not put action buttons inside a native `<summary>`; use a normal header with a separate `aria-expanded` button.

### Bulk confirmation

The APIs already accept arrays of keys for both departure and return ([ops.py:54](</media/hanafy/aa9ee400-c081-4d3b-b831-a2a8c83c9f44/personal/سيستم المعسكر/prototype/personnel_system/backend/routes/ops.py:54>), [ops.py:67](</media/hanafy/aa9ee400-c081-4d3b-b831-a2a8c83c9f44/personal/سيستم المعسكر/prototype/personnel_system/backend/routes/ops.py:67>)). No new mutation endpoint is necessary.

For `N > 1`, open a review dialog:

```text
قيام خدمات معاد 8ص
سيتم تسجيل قيام 12 خدمة.

[x] خدمة أ — صباحية
[x] خدمة ب — صباحية
...
[قيام 12 خدمة] [إلغاء]
```

- Select all eligible runs initially.
- Exclude returned runs and wrong-state runs.
- Show missing responsible person/count warnings inline.
- Keep the final button explicit: «قيام 12 خدمة».
- A single-run action should remain one-click because the five-minute undo mechanism already exists.

---

## 4. Density and visual scanning

The present card is effectively 212px high ([style.css:2185](</media/hanafy/aa9ee400-c081-4d3b-b831-a2a8c83c9f44/personal/سيستم المعسكر/prototype/personnel_system/static/style.css:2185>)), and the grid creates as many `minmax(260px, 1fr)` columns as fit ([style.css:2113](</media/hanafy/aa9ee400-c081-4d3b-b831-a2a8c83c9f44/personal/سيستم المعسكر/prototype/personnel_system/static/style.css:2113>)). This is comfortable for a handful of services but inefficient for 60+ runs.

### Recommendation

Make **compact list the desktop default**. Keep cards as:

- A user-selectable view.
- The mobile fallback.
- A useful view when filtered down to a small number of runs.

Recommended 48–52px row:

| Column | Content |
|---|---|
| الحالة | Text + small icon/marker |
| الخدمة | Primary, bold |
| المعاد | Large numeric token |
| الفترة | ص / ل |
| القائم بها | One-line ellipsis |
| القوام | Count + weapon |
| السياق | Line or special section |
| الإجراء | قيام/عودة + menu |

Use a native table per board, with `<tbody>` group boundaries and a sticky `<thead>`. On narrow screens, switch to cards instead of forcing horizontal scrolling.

### Color rules

Current CSS uses green for “out” and gold for “prep” ([style.css:2122](</media/hanafy/aa9ee400-c081-4d3b-b831-a2a8c83c9f44/personal/سيستم المعسكر/prototype/personnel_system/static/style.css:2122>), [style.css:2124](</media/hanafy/aa9ee400-c081-4d3b-b831-a2a8c83c9f44/personal/سيستم المعسكر/prototype/personnel_system/static/style.css:2124>)). That conflicts with the stated semantic rule.

Recommended mapping:

- متأخرة: red.
- تجهّز: amber.
- بالخارج: navy/info.
- عادت: green.
- قادمة: neutral gray/navy.
- Pending: neutral navy spinner/progress treatment.
- Gold: structural ruler only.

Apply color to a 3–4px row-edge marker, icon, and short state label—not the whole row. Every state remains understandable without color.

Returned rows should be visually quiet, not gray-disabled: reduced contrast, green check, action removed, timestamps retained.

---

## 5. Slow operations and keyboard use

The code already disables the initiating button and adds `is-pending` during mutation ([dashboard.js:295](</media/hanafy/aa9ee400-c081-4d3b-b831-a2a8c83c9f44/personal/سيستم المعسكر/prototype/personnel_system/static/js/dashboard.js:295>)). It also handles stale revisions and announces success ([dashboard.js:319](</media/hanafy/aa9ee400-c081-4d3b-b831-a2a8c83c9f44/personal/سيستم المعسكر/prototype/personnel_system/static/js/dashboard.js:319>)). However, success triggers a complete board re-render, which can move focus and scroll position ([dashboard.js:324](</media/hanafy/aa9ee400-c081-4d3b-b831-a2a8c83c9f44/personal/سيستم المعسكر/prototype/personnel_system/static/js/dashboard.js:324>)).

### Recommendation: optimistic affordance, authoritative commit

On click:

1. Keep the row in place.
2. Change the button immediately to:
   - «جارٍ تسجيل القيام…»
   - or «جارٍ تسجيل العودة…»
3. Add the target key to `pendingTargets`.
4. Disable all actions for affected runs, not only the clicked button.
5. Set `aria-busy="true"` on those rows.
6. After three seconds, show «الاتصال بطيء — ما زال التسجيل جارياً».
7. On success, update/reposition only affected rows and restore focus.
8. On failure, restore controls and show an inline row error plus toast.
9. On stale revision, retain the existing reload-and-retry message.

Do not optimistically move a row into another group before server confirmation; disappearing rows make uncertain network state look like success.

For bulk operations, show progress in the group header and lock every included key. Keep the confirmation dialog open until success or a recoverable error.

The existing 30-second refresh consciously avoids needless re-rendering to preserve menus and keyboard focus ([dashboard.js:281](</media/hanafy/aa9ee400-c081-4d3b-b831-a2a8c83c9f44/personal/سيستم المعسكر/prototype/personnel_system/static/js/dashboard.js:281>)); mutations should follow the same principle.

### Keyboard model

- `/`: focus search.
- `Escape`: clear search, then close popover/dialog.
- `F6`: cycle command center → filters → worklist → administrative follow-up.
- Up/Down on a focused row: previous/next visible row.
- Enter: execute the row’s primary action.
- Menu key or `Shift+F10`: open the ⋮ menu.
- Space on a group header: collapse/expand.
- Shortcuts disabled while typing in inputs or while a modal is open.
- Show shortcuts in tooltips and a small «اختصارات لوحة المفاتيح» help popover.

Keep normal Tab access to every actual button; keyboard shortcuts are accelerators, not the only access path.

---

## 6. Phased implementation plan

### Phase 1 — smallest high-value release

Goal: replace the long card wall with a searchable, time-grouped operational list without backend changes.

**`dashboard.html`**

- Add `#opsToolbar` beneath the status strip.
- Add search, shift, group-by, view toggle, and advanced-filter trigger.
- Generalize the existing line confirmation modal into a reusable bulk-action dialog.
- Keep `#opsBoard` and administrative follow-up structure.

**`dashboard.js`**

Add:

- `loadPrefs()` / `savePrefs()`.
- `flattenRunsWithContext(ops)` to produce one run per identity while retaining line/category context.
- `matchesFilters(run, filters)`.
- `groupRuns(runs, groupBy)`.
- `renderGroupHeader(group)`.
- `listRow(run)`.
- `renderEmptyResult()`.
- `pendingTargets`.

Refactor:

- `paintCounters()` into filter buttons.
- `renderBoard()` into one filter → group → render pipeline.
- Reuse `mutate()` and the existing array-based depart/return calls.
- Preserve focus, collapsed groups, and scroll position after refresh.

Deliver in this phase:

- Compact list default.
- Time grouping.
- Search.
- State and shift filters.
- Clickable counters.
- Returned hidden by default.
- List/cards persistence.
- Bulk action per time group.

### Phase 2 — complete organizational model

**`backend/ops_board.py`**

Add stable public metadata to every run:

```python
types
section_id
section_name
section_kind
line_meta
```

When processing `custom_sections`, pass the section name into `add_source()` rather than flattening it anonymously into emergency.

Consider returning a flat canonical `runs` array in addition to the legacy nested `groups` during migration. This avoids the frontend repeatedly flattening and deduplicating nested groups; current deduplication is done client-side by `uniqueRuns()` ([dashboard.js:25](</media/hanafy/aa9ee400-c081-4d3b-b831-a2a8c83c9f44/personal/سيستم المعسكر/prototype/personnel_system/static/js/dashboard.js:25>)).

**`dashboard.js`**

- Enable type, line/lorry, and section/occasion filters.
- Enable line, section, and state grouping.
- Add special-section bulk actions.
- Render lorry metadata consistently in all group modes.

**Tests**

Add payload tests covering:

- Special-section name survives `build_ops`.
- A shared officer/basic run appears once with both types.
- Carried identity remains distinct from today’s same key.
- Line metadata survives flattening.
- Bulk keys contain only eligible runs.

### Phase 3 — resilient interaction and polish

**`dashboard.js`**

- Replace full mutation re-render with targeted reconciliation.
- Add slow-operation feedback.
- Add roving row focus and shortcuts.
- Preserve focus after polling and group movement.
- Add visible sync timestamp and stale-state treatment.

**`style.css`**

Create a dedicated vocabulary:

- `.ops-command-center`
- `.ops-toolbar`
- `.ops-filter-chip`
- `.ops-list`
- `.ops-row`
- `.ops-group-header`
- `.ops-status-late/prep/out/back/upcoming`
- `.ops-row-pending`
- `.ops-bulk-progress`

Remove gold from status components and reserve it for the structural ruler.

### Proposed default-view wireframe

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ 10:32:14 │ التالية: خط فيصل — 8م، بعد 18د │ آخر تحديث الآن                 │
│ [قادمة 53] [تجهّز 6] [متأخرة 3] [بالخارج 15] [عادت 21] [مترحّلة 2]       │
├──────────────────────────────────────────────────────────────────────────────┤
│ بحث بالخدمة أو القائم...  [إجراء الآن] [ص/ل: الكل] [فلاتر 2]              │
│ التجميع: [حسب المعاد ▼]                         العرض: [قائمة ●] [بطاقات] │
└──────────────────────────────────────────────────────────────────────────────┘

إجراء الآن: 3 متأخرة · 6 تجهّز · 2 مترحّلة        [عرض ما يحتاج إجراء]

⌄ 8ص — 12 ظاهرة / 14             2 متأخرة · 4 بالخارج   [قيام المتبقي 6]
  [صفوف القائمة المدمجة]

⌄ 2م — 6 خدمات                    مناسبة: مباراة المصري   [قيام الكل 6]
  [صفوف القائمة المدمجة]

› 8م — 19 خدمة                    القادمة التالية         [قيام الكل 19]

› بدون معاد — خدمتان

متابعة إدارية: القوة، التقصيرة، التأكيد، والقادم                         ›
```

### Compact-list wireframe

```text
┌───────┬─────────────────────┬──────┬────┬──────────────────┬────────┬─────────────┬──────────┐
│ الحالة│ الخدمة              │ المعاد│فترة│ القائم بها       │ القوام │ الخط/القسم  │ الإجراء  │
├───────┼─────────────────────┼──────┼────┼──────────────────┼────────┼─────────────┼──────────┤
│ ! متأخر│ تأمين المحكمة      │ 8ص   │ ص  │ أحمد محمود       │ 6 · آلي│ بلا خط      │ [قيام] ⋮ │
│ ◐ تجهّز│ خدمة القنصلية      │ 2م   │ ص  │ محمد السيد       │ 4      │ خط الداخلي  │ [قيام] ⋮ │
│ → خارج │ خدمة فيصل          │ 8ص   │ ص  │ إبراهيم علي      │ 5 · آلي│ خط فيصل     │ [عودة] ⋮ │
│ ✓ عادت │ خدمة البوابة       │ 6ص   │ ص  │ محمود حسن        │ 3      │ أساسية      │ 07:42  ⋮ │
└───────┴─────────────────────┴──────┴────┴──────────────────┴────────┴─────────────┴──────────┘
```

### Open product decisions

- Should returned runs be hidden entirely by default, or shown in one collapsed «عادت» group? Recommendation: hidden, with the counter always accessible.
- Does «تحتاج إجراء الآن» include ordinary outside runs? Recommendation: no; only late, prep, and carried.
- Should bulk confirmation always appear, or only above a threshold? Recommendation: always for two or more runs.
- Should a time group mean exact report time or rounded windows? Recommendation: exact report time because most runs already share operational slots.
- Should cards remain user-selectable on desktop? Recommendation: yes, but compact list remains the default.
- Should local preferences follow the user across devices? The requested `localStorage` solution is device-local; cross-device persistence would require server-side preferences.
- Can the stable user ID be exposed in `base.html`? Recommendation: yes, instead of keying preferences by mutable username.
- Should special-section bulk actions be allowed for every custom section, or only sections explicitly marked operational? Recommendation: require `section_kind="special"` to avoid bulk-operating unrelated custom sections.
--- end report ---
