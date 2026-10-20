# Afraad export fidelity specification

This specification covers the `afraad` / «يومية الأفراد» Word kind for 2026-08-01 through 2026-09-29. It is an analysis artifact only; it does not change the exporter or stored data. Evidence was taken from the dated DOCX XML, the read-only system exports in `/tmp/fidelity-afraad`, and the current backend/import code.

## 1. File naming and location rules

The archive root is `../../2026/<month>/<day>/`, where month and day are not zero-padded. The intended file is `<d>-<m>-2026 أفراد.docx`. Ignore `~$` lock files, `.tmp`, `desktop.ini`, `ارقام الافراد.docx`, and `داتا افراد.docx`.

The internal title date is authoritative. Therefore `2026-09-08` uses `2026/9/8/8-9-2026 أفراد.docx`; its filename is stale but its title identifies 8 September. No archive file was found for 2026-08-29 or 2026-09-29. The comparison tool reports those as `ARCHIVE_MISSING` and does not invent an archive baseline.

The system endpoint is `GET /api/afraad/<day>/export.docx` (`backend/routes/afraad.py:38-46`). The supplied probe writes the resulting file as `<out>/<YYYY-MM-DD>/afraad.docx`.

## 2. Evolution timeline

All 58 present archive files have one table, portrait A4 page geometry, a seven-cell logical header, a basic block followed by a merged «الخدمات الطارئة» heading, and emergency rows. The archive is not one stable OOXML layout: grid-column widths, merge spans, emergency-row shapes, and margins were manually changed repeatedly.

| First observed day | Evidence and change |
|---|---|
| 2026-08-01 to 2026-08-26 | 22 basic rows. The 22nd is «كمين شرق النفق المستحدث». Grid-column counts vary: 13 on 8/1, 15 on 8/12, 13 on 8/18, 15 on 8/19, 16 on 8/21, 14 on 8/22, and 16 on 8/24. These are layout edits, not data semantics. |
| 2026-08-27 | Basic block becomes 21 rows; «كمين شرق النفق المستحدث» is absent. The emergency heading moves from row 23 to row 22. Grid count is 12. Evidence: `27-8-2026 أفراد.docx`, table row 22 is the heading and row 21 is «ارتكاز قسم فيصل الجديد». |
| 2026-08-30 to 2026-09-26 | Still 21 basic rows, but manual grid variants continue: 14/16 columns on 8/30-9/4, 15 on 9/5-9/13, 14 on 9/14-9/16, 12 on 9/17-9/18, 15 on 9/19-9/22, and 14 on 9/23-9/26. |
| 2026-09-27 to 2026-09-28 | Latest available format family. 16 grid columns; seven logical basic cells with spans `[1,3,3,3,3,2,1]`; 109 rows use eight logical cells with `[1,2,1,3,3,3,2,1]`; the emergency heading spans all 16 grid columns. `28-9-2026 أفراد.docx` is the last available exemplar and is the recommended latest-format reference. |

The latest-format choice is therefore the 2026-09-28 structure, with one important qualification: the emergency area itself is variable. On 2026-09-28, row 23 is a six-cell horizontal multi-assignment row (`المنطقة الحره ليل`, `مقدم/ حسام رضوان`, `بتروجيت صبح`, `م.اول / أحمد فوزي`, `قنصلية صبح`, `نقيب/عبدالرحمن طارق`), while later rows are ordinary five-cell rows. A correct latest exporter must support both forms.

LibreOffice rendering was attempted for the 2026-09-28 archive/system pair. It failed before conversion because the sandbox is read-only for `/run/user/1000/snap.libreoffice`; the measurements below are consequently XML-level, not a visual-layout claim.

## 3. Latest format specification

### Page and table

Evidence: `2026/9/28/28-9-2026 أفراد.docx`, `word/document.xml` and `word/styles.xml`.

- A4 portrait: `w=11906`, `h=16838` twips.
- Margins: top/bottom `142`, right `424`, left `426` twips; header/footer `709` twips.
- One continuous table. The latest table grid has 16 `w:gridCol` entries. Exact widths are `[685,863,82,1180,579,145,1130,1134,298,695,1134,425,596,496,656,1232]` twips in the 2026-09-28 file. Widths drift across days, so preserve the latest exemplar rather than copying an average.
- Header row: seven logical cells, bold 8 pt, light gray `F2F2F2`, centered: `م`, `الخدمــــــــة`, `الخدمـــــة الصباحـــــية`, `الخدمـــــة الليليـــــــة`, `قوام الخدمــــــــة`, `التسليح`, `الانتظام`.
- Ordinary basic rows use the same seven logical cells and spans `[1,3,3,3,3,2,1]`. The first cell is an empty/placeholder number column in the late archive. Do not infer a displayed sequence number from it.
- The two «كمين 109» rows use eight logical cells: empty number, parent `كمين 109`, subtype (`بيك اب` or `مدرعة`), morning, night, strength, weapon, schedule; spans `[1,2,1,3,3,3,2,1]` in the latest exemplar.
- The emergency heading is one merged cell spanning all 16 columns, bold 8 pt, centered, with the literal stretched text `الخدمـــــــــــات الطارئــــــــــــــــــــــــــة`.
- Standard emergency rows have five logical cells: service label, leader/person, count, weapon, and time/location. On 2026-09-28 the normal spans are `[5,4,1,2,4]`; the first multi-assignment row is six cells with `[2,4,2,3,3,2]`. Empty values use a long dash filler, but the exact dash length varies by copied/manual row.
- Basic person cells put the phone on a second paragraph/line when present. Examples: 2026-09-28 table row 2, morning `م.ش/ محمد نصار` has no phone; row 3, morning `ا.ش/ شريف صلاح جودة احمد` then `01208590765` is two lines. The exporter must preserve the archive convention: person label first, phone second line, and a dash filler only when the entire slot is empty.
- Body font sizes in the latest archive are role-dependent: basic service labels are commonly 9 pt bold, basic person/weapon/schedule cells 8 pt bold, strength text 7 pt bold; emergency cells use the `Bahnschrift SemiBold` direct font, commonly 10 pt for the multi-assignment row. The document style table names `Simplified Arabic` for Heading 1; direct cell runs are the stronger evidence.

### Data regions and ordering

1. Header.
2. Fixed basic services in the dated order. Latest archive order is 21 rows: the 22-row August order loses «كمين شرق النفق المستحدث» after 2026-08-26. The `كمين 109` service is represented by two adjacent subtype rows.
3. Merged emergency heading.
4. Emergency/custom rows in the operator's displayed order and shape. They are not safely reducible to one fixed five-column schema because the archive uses multi-pair horizontal rows and sometimes combines multiple people in one cell.

## 4. Data mapping and formatting rules

| Archive region/cell | Required source and current code | Archive formatting rule and evidence |
|---|---|---|
| Title | Day argument passed through `backend/afraad_export.py:_title` (lines 20-26) | `يومية الخدمات عن يوم <Arabic weekday> d/m/2026م خدمات الاساسية والطارئة`. Archive title date is also the discovery truth. |
| Basic service label/order | `backend/dated.py:afraad_basic_on`; `backend/afraad.py:84-105` | Use the dated list for that day, but render the latest 21-row format for all output days. Do not silently substitute the current 22-row list. Evidence: archive loses «كمين شرق النفق المستحدث» on 8/27; current `BASIC_SERVICE_NAMES` still contains it at `backend/afraad.py:28-52`. |
| 109 parent/subtype | `backend/afraad_export.py:109-122` | Parent `كمين 109` and subtype are separate cells. Current exporter only does this when the name starts `كمين 109 -`; the 9/28 system export instead has a regular `كمين 109` row followed by `مدرعة`, so it does not reproduce the archive's two-row identity. |
| Morning/night person | `backend/afraad.py:69-81,84-105`; person IDs are resolved through `PeopleRepo` | Archive text is an operator abbreviation plus `/` plus a space/name, not the stored full role string. Evidence across 58 files: `م.ش/` (1,492 observed rank-prefix tokens), `ا.ش/` (1,066), `اش/` (117), `أ.ش/` (77), plus `رقيب/`, `مقدم/`, `رائد/`, `نقيب/`, `م.اول/`. Abbreviations are inconsistent (`م.ش`, `ا.ش`, `اش`, `أ.ش`, spacing and punctuation). This must be a documented/ configurable rank map, not guessed from one day. |
| Phone | `backend/afraad.py:_slot`; `backend/afraad_export.py:_person_text` lines 28-30 | Print the phone as a second line in the same cell. Current `_person_text` already inserts `\n`, but it prints the full stored role/name and can print a stored phone that is absent in the archive. A missing phone is not permission to invent one. |
| Basic strength | `backend/afraad.py:96-101`; emitted by `backend/afraad_export.py:_strength` lines 64-67 | Preserve operator text, spacing, parentheses, Arabic digits, and combined morning/night text. Empty uses `ــــــــ`; a slash is not a safe delimiter because ordinary archive rows put both shifts in one merged strength cell separated by a line break. |
| Weapon | `backend/afraad.py:98-101`; direct row value in `afraad_export.py:118,122` | Preserve literal spelling (`الي`/`آلي`/`ألي`), plus signs, and dashes. The archive is manually inconsistent; normalize only for comparison, not for output. |
| Schedule/time | `backend/afraad.py:101`; emergency sorting in `backend/afraad.py:_time_key` lines 146-161 | Basic schedule is free text such as `8 ص / 8 م`, `8 ص فترة صباحة`, or `11 ص حتى الانتهاء`. Emergency rows retain time plus quoted location, e.g. `9ص "الجناين"`; the archive's displayed order is the evidence, not a newly sorted order. |
| Emergency label/person/count/weapon/time | `backend/afraad.py:164-176`; `_row` source through `backend/board.py`; formatting in `backend/afraad_export.py:130-136` | The current source is generic assignments and the current exporter forces five cells. The archive may have a multi-pair row, multiple people separated by `|`, `،`, or manual line breaks, officer and personnel ranks, and a location in the time cell. Preserve row shape and literal text. |
| Empty values | `backend/afraad_export.py:30,66,73,80,88` | Current exporter uses long dash fillers. Archive uses several lengths and sometimes `//` or short dashes (for example 2026-08-01 basic row «ارتكاز سوميد»). Treat filler variants as equivalent only in the comparison tool. |

The import tools explain why IDs alone are insufficient. `tools/import_afraad_rosters.py:136-152` extracts phones and tries phone/name matching, then replaces the archive spelling with the system person's full role/name when a match succeeds. `tools/import_afraad_rosters.py:208-218` stores only normalized fields plus person IDs. `tools/import_afraad_emergency.py:53-80` parses emergency rows, and `:121-147` skips officers and only adds matched personnel to generic assignment rows; it does not preserve the archive's complete multi-person row shape or officer text. This is data loss, not merely Word formatting.

## 5. Gap analysis

Measurement command used:

```bash
python3 tools/fidelity/afraad.py --archive-root ../../2026 \
  --system-root /tmp/fidelity-afraad \
  --json-out /tmp/afraad-final.json --text-out /tmp/afraad-final.txt
```

The tool compares logical cell values after tatweel/diacritic/whitespace cleanup, Arabic-Indic digit conversion, and Alef/Yaa comparison variants. It aligns basic and emergency rows by displayed order. Counts below are cell-level events over 60 requested days, not unique people. A structural event is emitted when grid/merge/page signature or row count differs.

| Rank | Gap | Count | Cause assessment and evidence |
|---:|---|---:|---|
| 1 | Basic morning values differ | 1,181 | (b) system data differs after import/role expansion. Archive uses abbreviations and sometimes shortened names; system prints full stored role/name. Example: 2026-09-28 basic row 1 archive `م.ش/ محمد نصار`, system `معاون شرطة ثالث/ محمد عطية منصور نصار` plus phone. |
| 2 | Basic night values differ | 956 | (b) system data differs, with the same rank/name expansion and missing/changed phone evidence. Example: 2026-09-28 row 2 archive `ا.ش/ محمد السيد عبدالرحيم` vs system `أمين شرطة ثالث/ محمد السيد عبدالرحيم عفيفي`. |
| 3 | Structure/grid/merge/page differs | 123 | (a) exporter/template cannot reproduce the archive's per-day/latest geometry, plus (c) manual archive variants. This includes 58 grid/merge/page signature events and 49 row/grid-count events. The late archive uses 16 grid columns while the generated file uses the template's own shape. |
| 4 | Basic service labels differ | 274 | 160 are abbreviation/spacing-only; 114 are real label/list differences. Cause is mixed (b)/(c): dated reference lists and the archive change over time. Example: archive 2026-09-28 has `المحور`/`قول18لاسلكى`-style manual labels while current system data has a different dated-list label; 2026-08-27 removes «كمين شرق النفق المستحدث». |
| 5 | System-only rows | 14 | (a)+(b): the current system has a basic/emergency row with no same-position archive row, principally because its data/list shape is not the latest 21-row archive shape and emergency counts/order are different. The tool marks the event `DATA-EXTRA`; it does not claim the source row is semantically invalid without review. |

Other measured facts: 58 of 60 requested days have an archive file; 2026-08-29 and 2026-09-29 are missing. There were 58 layout-signature differences, 49 additional row-count differences, 2,309 substantive value differences, and 160 abbreviation/formatting-only differences. Top field patterns were basic morning (1,181), basic night (956), basic service abbreviation-only (160), basic service substantive (114), and basic count (58). These totals overlap by day and are deliberately not presented as independent defects.

### Recommended exporter changes ordered by impact

1. Change the source model/mapping before changing typography. Add a date-effective afraad format/list profile that can represent the latest 21 basic rows, the two 109 subtype cells, and a reviewable archive spelling/rank abbreviation. The current `backend/dated.py:afraad_basic_on` plus `backend/afraad.py:28-52` is not enough because it retains the 22nd service and historical names.
2. In `backend/afraad_export.py:91-136`, use a latest-format template/row prototype with the measured 16-column grid and latest merge spans. Do not assume the copied template's 14 logical/table geometry is the archive geometry.
3. Replace `_person_text` with an explicit archive-label formatter: preserve the archive rank abbreviation and operator name as separate display data, then append phone on a second line. Do not regenerate the archive label from the full personnel role/name unless the product owner approves that fidelity trade-off.
4. Represent emergency rows as either a standard five-cell row or a list of horizontal `(label, person)` pairs, followed by count/weapon/time fields where present. `occasional_rows` and `_occasional_who` currently collapse that information into a generic row and `_occasional_who` joins people with `،`.
5. Preserve archive order and row shape for emergency/custom rows. `backend/afraad.py:175` sorts by an approximate parsed time; that is not equivalent to the handwritten/displayed archive order when times are missing or manually arranged.
6. Add an export-fidelity fixture test using 2026-09-28 (latest geometry), 2026-08-27 (21-row transition), and 2026-09-08 (stale filename/title truth). Assert XML grid/merge signatures and representative literal cells, not only row counts.

## 6. OPEN QUESTIONS

- Is the latest required format definitively the 2026-09-28 shape, or should the exporter reproduce the 2026-09-27/28 manual emergency-row variation? The final available 2026-09-29 archive is missing.
- Is «كمين شرق النفق المستحدث» intentionally retired on 2026-08-27, or was it accidentally omitted from the archive? The system currently still has it in the baseline list.
- Should the product preserve operator-entered rank abbreviations and names as display strings, or is full personnel identity intentionally preferred? The archive and system disagree materially on both rank and full name.
- Does the system store enough information for archive-equivalent emergency rows, especially officer names, multiple label/person pairs, and the quoted location? The emergency importer explicitly skips officer text and appends only matched personnel.
- Are the archive's variable column widths, filler lengths, `//`, and manual spelling variants part of the contractual format, or should only the latest structural template be contractual?
- Should missing phones remain blank, or should a current personnel phone be substituted? 2026-09-28 `مدرعة المديرية` demonstrates an archive person with no printed phone while the system prints one.

## 7. Deliverables

- `tools/fidelity/afraad.py`: importable, read-only CLI producing JSON and readable summaries with STRUCTURE, DATA-MISSING, DATA-EXTRA, DATA-DIFFERENT, and normalization-aware subcategories.
- This specification: `docs/export-spec/afraad.md`.
