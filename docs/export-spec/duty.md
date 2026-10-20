# Duty roster export fidelity specification

Scope: `KIND=duty`, the officers' daily duty roster (`يومية تشغيل الضباط`). Evidence covers every canonical archive file `2026-08-01` through `2026-09-29` (60/60 files) and the read-only system exports made with `tools/export_days_probe.py` against the supplied data copy. XML table coordinates below are zero-based; `table[0]` is the roster and `table[1]` is the compact summary.

## 1) File naming and location rules

The archive file is exactly:

`<archive-root>/<month>/<day>/<day>-<month>-2026.docx`

For example, `2026/9/28/28-9-2026.docx`. The archive root used here was `/run/media/hanafy/aa9ee400-c081-4d3b-b831-a2a8c83c9f44/personal/سيستم المعسكر/2026`. Lock files, `.tmp`, and `desktop.ini` were ignored. `"<d>.docx"` is the detailed log; `"<d>-<m>-2026 افراد.docx"` is the personnel roster and was not used.

The system artifact was `.../<YYYY-MM-DD>/duty.docx`, produced by `GET /api/duty/<day>/export.docx` (`backend/routes/duty.py:55-66`) with `backend/duty_export.py::build_docx` (`backend/duty_export.py:118-156`).

## 2) Evolution timeline

All archive files use A4 portrait page settings, but the table format changes materially:

| First day | Archive structure | Evidence |
|---|---|---|
| 2026-08-01 | One roster table, 27 rows × 7 logical columns. 2026-08-02 and 08-03 are also one table, with 26 and 24 rows. | `2026/8/1/1-8-2026.docx`, `table[0]` |
| 2026-08-04 | One 37 × 7 roster; header changes to `العمل المسند مجددا` and `ملاحظات`. | `2026/8/4/4-8-2026.docx`, `table[0]/row[0]` |
| 2026-08-05 | Roster becomes 37 × 9: phone, seniority, and duplicated التشغيل columns; 3 × 6 rank summary appears. | `2026/8/5/5-8-2026.docx`, `table[0]`, `table[1]` |
| 2026-08-07 | Roster becomes 37 × 8: phone, seniority, and one التشغيل column; rank summary remains. | `2026/8/7/7-8-2026.docx` |
| 2026-08-09 | Roster becomes 37 × 7 with the current five content columns plus merged `الراحات`; the rank summary is absent on 08-09 through 08-16. | `2026/8/9/9-8-2026.docx` |
| 2026-08-17 | The 4 × 16 `جدول الإجمالي` appears. It is absent again on 08-18 and 09-14, so “from 08-17” is not literally continuous in the archive. | `2026/8/17/17-8-2026.docx`, `table[1]`; absence verified in `2026/8/18` and `2026/9/14` |
| 2026-08-19 onward | 37 × 7 roster plus 4 × 16 summary, with changing manual contents and summary header variants. | `2026/8/19`–`2026/9/21` |
| 2026-09-22 | Stable final shape through 09-29: 37 × 7 roster plus 4 × 16 summary; summary header ends in `الصافي` without a count. | `2026/9/22`–`2026/9/29`, `table[1]/row[0]/cell[15]` |

The latest-format choice is therefore the stable 22–29 September shape, not the one-off 09-15 38-row roster or earlier 16-column summary header variants. The product requirement says the latest format wins for all days; early archive shapes are historical evidence and should not be copied into a future exporter.

## 3) LATEST FORMAT SPEC

### Page and title

The final archive XML uses A4 portrait `w=11906`, `h=16838` twips, `code=9`, with margins `top=180`, `right=542`, `bottom=142`, `left=450`, `header=709`, `footer=709`, `gutter=0` (`2026/9/29/29-9-2026.docx`, `word/document.xml/w:sectPr`). The title is centered and reads:

`يومية تشغيل الضبـــاط بإدارة قـوات أمن السويس عـن يوم <weekday>  الموافق <d> /<m>/2026م`

The archive has a visible double space before `الموافق` and a space before the day slash; the current `_title` removes those spaces (`backend/duty_export.py:40-43`). The weekday comes from `WEEKDAY_BY_INDEX` (`backend/duty_export.py:11`, `_title`).

### Main roster table (`table[0]`)

The final table is 37 physical rows and 7 logical columns. Its grid widths are `[574, 572, 2410, 2680, 3700, 971, 7]` twips and table width is `4903` (`2026/9/29`, `w:tblGrid`). Each logical row has:

1. `م`: display ordinal `1-` through `34-`.
2. `الرتبة`: raw/effective rank, including the observed `م.اول` abbreviation.
3. `الاســـــــــــــــــــــم`: full officer name.
4. `العمــــــــل المســـــند إليـــــة`: fixed post/assignment description.
5. `التشغيل اليومي`: the day's note/service/leave/status text.
6. `الراحات`: weekly day, monthly/semi-monthly system, or dash filler.
7. The second physical half of the merged `الراحات` cell; it is structurally present but text-empty in the latest XML (`w:gridSpan=2`).

Rows are: row 0 header; rows 1–24 force officers; row 25 merged section label `الحراسات المشددة`; rows 26–33 guard officers; row 34 merged section label `الخــــــــــــــــــــــــــوارج`; rows 35–36 outside officers. Latest evidence is `2026/9/29`, `table[0]/row[25]`, `row[34]` and `row[35:36]`. The archive's ordinary data rows use approximately 9pt bold runs (`w:sz=18`); section rows are shaded `F2F2F2`. The archive row heights vary by manual text and are not a reliable fixed-height contract; the current exporter forces 13pt-equivalent rows (`backend/duty_export.py:81-90, 143-150`).

### Compact summary (`table[1]`)

The latest summary is 4 × 16 logical columns, grid widths `[734,869,699,869,629,635,471,603,471,517,488,568,450,531,762,1834]` twips (`2026/9/29`, `w:tblGrid`). The first row is grouped/merged headers; the second row is subheaders plus the net-name list; row 2 is totals; row 3 is an optional manual/continuation row. Logical columns are:

`أصل القوة | خارجية صباحية | خارجية ليلية | داخلية صباحية | داخلية ليلية | طبية موجود | طبية راحة | خوارج تقصيرة | خوارج راحة | طارئة | غياب | مرضي | فرقة | انتداب | الحراسات المشددة | الصافي`.

Final archive examples: `2026/9/29/table[1]/row[2]` is `34, 3+ 1 بحث, 2, 3, 2, 1, 1, 1, 5, 0, 0, 0, 1, 1, 8`; `row[1]/cell[15]` contains abbreviated slash-separated net names such as `عقيد/احمد سمير`, and `row[3]` contains manual continuation values `1 معسكر فرعي` and `منتدب` in some days. Do not assume row 3 is a duplicate totals row: it is often sparse and manually authored. `2026/9/29` is the clearest evidence.

## 4) Data mapping and formatting rules

| Archive region | System source and code | Formatting rule/evidence |
|---|---|---|
| Officer population/order | `officers_on(data, day)` via `backend/duty.py:161-178`; effective dated fields via `backend/people.py:5-33` | One row per officer on force for that day. The current exporter groups by `OFFICER_SECTIONS` (`backend/duty_export.py:72-78`), which is a different order from several archive days; archive 09-29 and system export demonstrate this in `table[0]` name order. |
| `م` | local `number` in `build_docx`, `backend/duty_export.py:131-146` | Sequential `1-`…`34-` within the rendered roster, excluding section rows. The number is presentation-only; the comparator reports changes caused by reorder as `ORDER`. |
| Rank | `effective(o, day)['role']`, `backend/duty.py:118-143`; `RANK_SHORT`, `backend/duty_export.py:16,146` | Only `ملازم أول` is shortened to `م.اول`; other values pass through. Archive and system use this in `2026/9/29/table[0]/rows[21:24]`. |
| Name | `o['name']`, `backend/duty.py:140`; `_cell_text` call at `backend/duty_export.py:146-150` | Full name, bold in the system export. Summary net names are not a separate stored field: `summarise` constructs `role + '/ ' + name` at `backend/duty.py:167-175`, while the archive uses shorter manual/abbreviated forms. |
| Fixed work/post | `effective(o, day)['post']`, `backend/duty.py:140-143` | Raw post text; preserve punctuation, parentheses, plus signs, and line breaks. `2026/9/29/table[0]/row[12]/cell[3]` proves that `+` spacing differs between archive and system; this is a formatting-only difference. |
| Daily operation | `note`, `assignments_of`, `leave_on`, `officer_state`, `backend/duty.py:119-151`; `_daily_text`, `backend/duty_export.py:55-69` | Priority is note; then service names with ` فترة <shift>` joined by ` + `; then leave type; then status/group/`عمل`. `assignments_of` is ordered from `day_assignments` (`backend/assignments.py:97-99`). The archive contains manual spelling variants such as `احتياطي طوارئ` vs `احتباطي طوارئ` (`2026/9/9/table[0]/row[17]/cell[3]`). |
| Rest | `effective` rest fields, `backend/duty.py:142-143`; `_rest_text`, `backend/duty_export.py:46-52` | Empty/`—` becomes `------------`; weekly with a day becomes the weekday; otherwise the system string is emitted. On final days the system emits `أسبوعية` for three officers where the archive has dash filler (`2026/9/29/table[0]/rows[1,2,12]`), so the data contract is not enough to reproduce the archive without a product decision. |
| Section rows | `row['section']`, `_grouped_rows`, `backend/duty_export.py:72-78,132-140`; constants `backend/constants.py:118-124` | Fixed order: force, guards, outside. The labels are `الحراسات المشددة` and `الخوارج`; the archive section label may be stretched with tatweel, and latest row 34 uses the stretched form. |
| Summary totals | `_bucket`, `summarise`, `backend/duty.py:82-111,161-186`; `_fill_summary`, `backend/duty_export.py:93-115` | Counts are assigned by priority: explicit status, medical role/service, leave, taqseera, guards, first counted service, course, net. External search adds `+N بحث` only for external service (`backend/duty.py:58-66`; exporter `:96-103`). The archive's sparse row 3 and subcamp text are not represented by the current summary schema. |
| Summary net names | `summary['net_names']`, `backend/duty.py:167-175` | System writes full names separated by newlines into both rows 1 and 2/3 target cells (`backend/duty_export.py:111-115`); final archive writes compact rank/name abbreviations and may repeat the list (`2026/9/29/table[1]/rows[1,3]/cell[15]`). |

## 5) Gap analysis

The reusable comparator was run against all 60 days after XML logical-grid expansion, tatweel/diacritic/whitespace normalization, Arabic-Indic digit normalization, and alef/yaa variant normalization. It aligns main roster rows by normalized officer name and reports order separately. Full measured counts: `STRUCTURE 74`, `ORDER 60`, `DATA-DIFFERENT 1,090`, `DATA-MISSING 203`, `DATA-EXTRA 467` (1,894 total findings). The final stable-format window 09-22…09-29 still has 180 findings: 8 structure, 8 order, 140 different, 16 missing, 8 extra.

Ranked recurring gaps:

1. **Summary/roster structure is not the archive geometry — 74 STRUCTURE findings.** The exporter always uses its template geometry and always emits the summary, while early archive files have no summary and final archive grids differ. On 09-29 the archive roster grid is `[574,572,2410,2680,3700,971,7]`; system is `[574,626,2344,2419,3968,976,7]`. Summary grids also differ in the first five widths. Cause: exporter/template structure; emitting the latest summary for historical days is intentional under “latest wins,” but the latest grid still needs to be copied.

2. **Officer order is different on every day — 60 ORDER findings.** Example: on 09-29 archive rows 5–8 are عبدالرحمن, محمد احمد, حسام, طاهر; system rows 5–8 are حسام, طاهر, عبدالرحمن, محمد احمد. Cause: archive/manual ordering versus `officers_on`/`_grouped_rows`; the display ordinal changes are a consequence and are not counted as data mismatches.

3. **Rest text is not reproducible — 156 repeated `------------` → `أسبوعية` mismatches, plus 31 `نصف شهرية`/`شهرية` and 14 weekday mismatches among the top patterns.** Example: 09-29 rows 1, 2, and 12 have archive dash filler but system `أسبوعية`; 09-12 guard row 26 has archive `الاحد` and system `الأربعاء`. Cause: mixed system rest metadata and manual archive conventions; the archive does not consistently expose whether dash means “no rest” or an omitted schedule.

4. **Summary counts do not model the archive’s second/continuation row — 203 missing and 467 extra findings overall.** Examples: 09-29 `table[1]/row[3]/cell[3]` has archive `1 معسكر فرعي` but system empty; `row[3]/cell[5]` has archive `منتدب` but system empty; on 08-17 `row[3]/cell[6]` is system-only `0`. Cause: exporter/schema gap plus archive manual continuation values. This is not safely fixable by changing a count formula alone; the data model needs an explicit continuation/manual-summary representation.

5. **Summary numeric allocation and net list differ — 1090 DATA-DIFFERENT findings overall; in the final window the largest recurring cells are `table[1]/cell[15]` (16 net-header differences), `cell[1]` (8), and several bucket cells.** On 09-29 archive totals are `3+ 1 بحث, 2, 3, 2, 1, 1, 1, 5…`; system totals are `3, 2, 0, 0, 0, 0, 0, 8…`, and archive net names are abbreviated while system writes 11 full names. Cause: system summary computation/mapping differs from the manually prepared archive and the current exporter formats the wrong summary cell contents.

The most severe days by finding count are 08-05 (192), 08-06 (191), 08-08 (181), 08-07 (180), and 08-04 (119). These are primarily historical structure transitions (9/8/7-column rosters and rank summary), so they should not drive the final template choice.

## 6) Recommended exporter changes, ordered by impact

1. Make a latest-format template whose roster and summary grids, merges, fills, and row geometry match `2026/9/29` XML exactly; update `TEMPLATE`/`build_docx` and `_fill_summary` in `backend/duty_export.py`. The current template is visibly based on a different width set.
2. Always render the latest 37 × 7 + 4 × 16 format for every requested day, as required by the product rule, but preserve historical data values rather than historical table shapes.
3. Add an explicit summary presentation model for the sparse fourth row: subcamp continuation (`N معسكر فرعي`), manual status labels such as `منتدب`, and the archive’s repeated/abbreviated net-name convention. Do not overload the existing 16-value `values` list in `_fill_summary`.
4. Decide and encode officer ordering separately from `officers_on`: the archive order is not the same as the current section/order sequence. If the order is a business rule, store it; if it is historical manual order, mark it non-authoritative and use a stable system order consistently.
5. Resolve the rest contract. `rest_system`, `rest_day`, leave records, and dash filler need a documented precedence. In particular, decide whether a weekly system value with no day is invalid, whether dash means “not applicable,” and whether monthly/semi-monthly text is authoritative for a given date.
6. Make the title spacing and section-label spelling/tatweel explicit if byte/layout fidelity is required (`_title` at `backend/duty_export.py:40-43`; section labels at `:138-140`).
7. Keep the comparator in CI or an analyst runbook; it should compare logical XML cells, not `python-docx`’s duplicated merged-cell view.

## 7) OPEN QUESTIONS

- Is the archive’s abbreviated net list (for example `عقيد/احمد سمير`) authoritative, or should the system’s full names be preferred?
- What do the sparse fourth summary-row values mean, and which system fields should supply `1 معسكر فرعي` and `منتدب`?
- Is `الراحات` a standing officer schedule, a day-specific rest result, or a manual note? What is the semantic meaning of dash filler?
- Is the archive officer order a required operational order, or is a deterministic current-system order acceptable under the latest-format rule?
- Are the archive spelling variants (`احتياطي`/`احتباطي`, `الاحد`/`الأحد`, spaces around `+` and `/`) intentional text, or should comparison/export canonicalize them?
- Should `الصافي` retain no count in the latest header, or should the parenthesized count be retained from earlier 4 × 16 files? Evidence favors no count because all eight final days use `الصافي`, but the product owner should confirm.
- Does “latest format wins” require filling the latest summary for days whose archive had no summary (08-01…08-16, 08-18, 09-14), or only adopting the latest geometry where a region exists?

## Comparison tool

Created `tools/fidelity/duty.py` (importable and CLI). It supports a single day or all 60 days, XML logical-grid extraction, normalization, name-based row alignment, `STRUCTURE`, `DATA-MISSING`, `DATA-EXTRA`, `DATA-DIFFERENT` with formatting-vs-real subcategory, `ORDER`, recurring-pattern summaries, worst days, and heuristic cause labels.

Example:

```bash
python3 tools/fidelity/duty.py --all \
  --system-root /tmp/fidelity-duty-20261020 \
  --json-out /tmp/duty-fidelity.json \
  --text-out /tmp/duty-fidelity.txt
```

LibreOffice visual validation was attempted for the 09-29 archive/system pair, but the sandbox refused to create `/run/user/1000/snap.libreoffice` because that filesystem is read-only. The report therefore relies on DOCX XML and `python-docx` structure evidence; no visual rendering claim is made.
