# اعداد الخدمات: Excel export-fidelity knowledge base

Scope: archive workbooks in `2026/8/1..31` and `2026/9/1..29`, compared with
the Flask `GET /api/counts/<day>` response using the specified read-only copy
of `PERSONNEL_DATA_DIR`. There is no current Excel exporter for this kind.
The API is the system-side reference, not a claim that it already produces an
`.xlsx` file.

## 1. File naming and location rules

The observed archive location is `../../2026/<month>/<day>/` relative to the
project, with one sheet normally named `اعداد الخدمات`. Candidate files are
non-lock, non-`.tmp` files whose name contains `اعداد الخدمات`.

The requested interval has all 60 day folders and no missing folder/file. It
has 61 workbooks because `2026/9/9` contains both `اعداد الخدمات يوم 8-9-2026.xlsx`
and `اعداد الخدمات يوم 9-9-2026.xlsx`.

The folder/name/content audit found these stale or ambiguous cases:

| Folder | Evidence | Finding |
|---|---|---|
| `2026/8/8` | `B2` says `7 / 8 / 2026`, filename says `8-8-2026` | content date is stale by one day |
| `2026/8/27` | `B2` says `26 / 8 / 2026`, filename says `27-8-2026` | content date is stale by one day |
| `2026/8/28` | `B2` says `27 / 8 / 2026`, filename says `28-8-2026` | content date is stale by one day |
| `2026/9/9` | `اعداد الخدمات يوم 8-9-2026.xlsx`, `B2` says `8 / 9 / 2026` | stale duplicate in the 9/9 folder; the 9/9-named workbook is also present |
| `2026/9/20` | filename and `B2` both say `19 / 9 / 2026` | stale content/name relative to folder 9/20 |
| `2026/9/22` | filename says `21-9-2026`, `B2` says `22 / 9 / 2026` | stale filename; content agrees with folder |
| `2026/9/28` | filename says `27-9-2026`, `B2` says `28 / 9 / 2026` | stale filename; content agrees with folder |

The parser in `tools/fidelity/counts.py` uses the folder date to select the
API payload and records both filename and `B2` title date, so these cases are
not silently collapsed.

## 2. Evolution timeline

The workbook structure is stable in columns and visual styling but the
emergency/total area moved down by three rows.

| Days | Version | Evidence |
|---|---|---|
| 2026-08-01 through 2026-08-25 | V1, 49 rows, `A1:H49` | `2026/8/1`, merges include `C38:E45`, `F38:F45`, `H26:H30`, `H32:H33`; grand total formula is `F38` |
| 2026-08-26 through 2026-09-29 | V2/latest, `A1:H52` with active content `B2:H52` | `2026/8/26` and `2026/9/29`, merges include `C41:E48`, `F41:F48`, `H26:H34`, `H35:H36`; grand total formula is `F41` |

V2 is the defensible latest format because it starts on 2026-08-26 and is
used through the final archive day. Individual V2 files differ in the number
of populated emergency slots and in manual text, but not in the latest grid,
merges, page setup, or formula coordinates. The project-wide rule should
therefore render every target day in V2, including days whose historical file
was V1.

## 3. Latest format specification (V2)

### Workbook and page

- One worksheet exactly: `اعداد الخدمات`.
- Right-to-left sheet view: `sheet_view.rightToLeft = True`.
- Used content area: `B2:H52`; openpyxl dimension commonly reports `A1:H52`
  because of row/column formatting.
- Landscape, paper size code 9 (A4), fit-to-page enabled.
- Margins: left/right `0.25`, top/bottom `0.30` (header/footer `0`).
- Column widths: A `2.425781`, B `54.0`, C `14.0`, D `50.710938`, E `14.0`,
  F `50.710938`, G `15.285156`, H `27.425781`.
- Merges: `B2:H2`, `B25:H25`, `H4:H12`, `H14:H23`, `H26:H34`, `H35:H36`,
  `C41:E48`, `F41:F48`.

### Row geometry

The latest workbook fixes the grid rather than growing it dynamically:

| Rows | Role | Height evidence from `2026/9/29` |
|---|---|---|
| 1 | spacer | 9.75 |
| 2 | title | 34.5 |
| 3 | morning header | 50.25 |
| 4:12 | morning data slots | 18 each, except row 9 is 2.25 in the observed file |
| 13 | night header | 50.25 |
| 14:23 | night data slots | 18 each |
| 24 | spacer | 13.5 |
| 25 | emergency title | 34.5 |
| 26 | emergency header | 50.25 |
| 27:35 | emergency data slots | 18, with row 27 `25.5` and row 35 `24.75` in the observed file |
| 36 | emergency subtotals | 21.75 |
| 37:39 | blank/legacy spacer | row 37 `25.5`; rows 38:39 default |
| 40 | spacer | 15.75 |
| 41:48 | merged grand-total area | rows 41:42 `15`, row 43 `15.75`, rows 44:48 `15.75` |

The unusual row 9/27 heights are archive-specific manual layout artifacts. A
new exporter should preserve the V2 geometry deliberately, but the product
owner should decide whether these two one-off heights are part of the official
format.

### Fonts, fills, borders, alignment, number formats

- Title cells `B2` and `B25`: `AdvertisingExtraBold`, 22 pt, bold, centered,
  wrapped, medium border on all sides, no fill.
- Main headers and normal service/count cells: `AdvertisingMedium`, 16 pt,
  bold, centered, wrapped, no fill. Service cells use medium outer/side
  borders; count cells use thin left and medium right borders. The same style
  is used for rows 3, 4:23.
- Emergency header row 26: `AdvertisingMedium`, 16 pt, bold, centered,
  wrapped, solid theme gray fill (observed RGB fallback `E4E4E4`), thin inner
  borders and medium outer borders. `H26` uses `AF_Aseer`, 16 pt, bold,
  centered, vertical text rotation `90`.
- Emergency data rows 27:35 use `AdvertisingMedium`, 16 pt, bold, centered.
  Subtotal row 36 uses Arial 16 pt bold, gray fill (RGB fallback `D9D9D9`),
  and number format `0;\-0;;@` in numeric cells.
- Merged service-total cells `H4` and `H14` use Arial 16 pt bold, gray fill,
  centered/wrapped, medium borders, number format `0" مجند"`.
- `H35` is the emergency total: Arial 16 pt bold, gray fill, centered,
  rotation `90`, number format `0;\-0;;@`.
- Grand total label `C41:E48`: Lucida Console 22 pt bold, gray fill, centered,
  wrapped, medium border. Grand total value `F41:F48`: Arial 22 pt bold, gray
  fill, centered, number format `0" مجند"`, medium border.
- Ordinary service/count constants use `General`; blank filler cells remain
  genuinely blank, not zero or a dash. The UI may display `—`, but the archive
  workbook uses empty cells for unused slots.

### Every formula in V2

The following list is complete for `2026/9/29` and the same formula pattern is
present in V2 files, with the same coordinates:

```text
H4  =SUM(C4:C12)+SUM(E4:E12)+SUM(G4:G12)
H14 =SUM(C14:C23)+SUM(E14:E23)+SUM(G14:G23)
C36 =SUM(C27:C35)
E36 =SUM(E27:E35)
G36 =SUM(G27:G35)
H35 =C36+E36+G36
F41 =H4+H14+H35
```

Formula cached values were read with `openpyxl.load_workbook(...,
data_only=True)` and formula text with `data_only=False`. V2 examples are
`H4=51`, `H14=53`, `C36=14`, `E36=8`, `G36=36`, `H35=58`, `F41=162` on
2026-09-29 (`H4`, `H14`, `H35`, `F41` are evidence cells; the subtotal cells
are `C36`, `E36`, `G36`).

## 4. Data mapping and formatting rules

The API contract is the object returned by `backend/routes/counts.py:get_counts`
and built by `backend/counts.py:build`. The comparison tool calls it through
Flask's test client with the same `testadmin` session pattern as
`tools/export_days_probe.py`.

| Workbook region | API source | Mapping/formatting rule | Evidence |
|---|---|---|---|
| `B2:H2` | payload `date`; weekday derived from the date | `اعداد الخدمات الصباحية والمسائية الاساسية يوم <Arabic weekday> <d> / <m> / 2026 م` | `2026/9/29!B2`; API `build` returns `date`, not a ready-made title |
| AM `B4:C12`, `D4:E12`, `F4:G12` | `basic_am` | Take the ordered list and place it column-major: first 9 in B/C, next 9 in D/E, remainder in F/G. Service text is `name` plus ` (party)` when `party` is non-empty; count is integer `count`. | `2026/9/29!B4`, `D4`, `F4`; `backend/counts.py:build` |
| PM `B14:C23`, `D14:E23`, `F14:G23` | `basic_pm` | Same column-major rule with 10 slots per first two columns. | `2026/9/29!B14`, `D14`, `F14`; `backend/counts.py:build` |
| `H4`, `H14` | AM/PM counts | Formula totals of the three count columns, displayed with `مجند`. | `2026/9/29!H4`, `H14` |
| Emergency `B27:G35` | `recurring`, then `emergency`, then rows from every `custom_sections` block | Flatten to one ordered list and place column-major, 9 rows per column. The archive has no separate label for recurring versus daily/custom. Unused slots are blank. | `2026/9/29!B27:F35`; `backend/counts.py:build`, `custom_sections`, `emergency_rows` |
| `C36`, `E36`, `G36` | Emergency count cells | Formula subtotal of each emergency count column. | `2026/9/29!C36`, `E36`, `G36` |
| `H35` | Emergency subtotal | Formula `=C36+E36+G36`; it is merged vertically with `H36` and rotated 90 degrees at `H26`'s label. | `2026/9/29!H35:H36` |
| `C41:E48`, `F41:F48` | all three totals | Label constant `إجمالي اعداد الخدمات`; formula `=H4+H14+H35`. Note that V2's archive total has no separate custom-section total. | `2026/9/29!C41`, `F41`; `backend/counts.py:build:totals` |

Archive spelling is manual, not a clean catalog projection. Examples from the
latest workbook include `نقطه` versus API `نقطة`, `سياره` versus `سيارة`, and
`المخابرات الحربيه` versus API `المخابرات الحربية`. AM often carries the party
in parentheses, while the same PM service often does not: for example
`2026/9/29!B6` is `جنيفة (الطرق)` but `B16` is `جنيفة`. This is a formatting
and source-data policy decision, not a safe normalization rule for an exporter.

## 5. Gap analysis

The reusable run was:

```bash
PERSONNEL_DATA_DIR=/tmp/claude-1000/-run-media-hanafy-aa9ee400-c081-4d3b-b831-a2a8c83c9f44-personal--------------/4a67d6c4-d1a3-4f58-b7fe-1f28f9a5974c/scratchpad/tmpdata \
  python3 tools/fidelity/counts.py --json /tmp/fidelity-counts-report.json
```

Measured across 60 requested days and 61 archive workbooks:

| Rank | Gap | Count | Decided cause |
|---:|---|---:|---|
| 1 | DATA-DIFFERENT, count values | 1,123 | system data differs from the manual archive; the API's `count` is not the historical cell value on many days |
| 2 | DATA-DIFFERENT, spelling/labels | 973 label-quirk instances plus 323 formatting-only instances | archive manual spelling/parenthetical convention; no exporter bug exists yet |
| 3 | ORDER | 783 | archive manual/column-major ordering quirk; the target generator must make the placement rule explicit |
| 4 | DATA-EXTRA | 370 | system-side list has rows not present in that archive workbook, usually daily/custom services |
| 5 | DATA-MISSING | 185 | archive has rows absent from the API payload for that day |
| 6 | STRUCTURE | 50 | historical V1 format evolution, not a data bug; latest-format-wins requires V2 for all days |

The exact run summary is: `STRUCTURE=50`, `DATA-DIFFERENT=2605`,
`ORDER=783`, `DATA-EXTRA=370`, and `DATA-MISSING=185`. Cause totals are
`system_data_differs_archive=1864`, `archive_manual_label_quirk=973`,
`archive_manual_order_or_layout=783`, `archive_manual_formatting=323`, and
`archive_format_evolution=50`.

The `DATA-DIFFERENT=2605` total includes 1,123 count-value differences, 973
label differences, 323 formatting-only differences, and 186 formula-cache
differences. These are the tool's JSON `subcategories` counts.

Representative recurring patterns are evidence-backed by the latest files:

- `2026/9/29!B4` vs API `basic_am[0]`: archive `نقطه تفتيش...`, API
  `نقطة تفتيش...` (manual spelling).
- `2026/9/29!B6` vs `B16`: AM includes `(الطرق)` while PM omits it (manual
  formatting policy).
- `2026/9/29!B27` starts `كول كورنيش`, while the API's recurring list order is
  `المحكمة`, then `كول كورنيش`; this is an order/source convention that must be
  resolved before a deterministic exporter can claim byte-level fidelity.
- `2026/9/29!F41` cached value is 162, while the API snapshot for that day has
  a different total; this is a real data mismatch, not a formula-style issue.

Because there is no existing Excel exporter, there are zero measured current-
exporter bugs. The comparison's `STRUCTURE` category measures archive files
that are not the selected V2 target, and the other categories measure API vs
archive data/ordering. The tool deliberately does not call these exporter
defects.

## 6. Recommended exporter changes, ordered by impact

1. Add a new Excel-only export module outside the analysis scope, with a
   single V2 template and explicit `B2:H52` geometry. Do not reuse the V1
   row coordinates. Keep formulas exactly as listed above.
2. Add a deterministic adapter beside the exporter that maps
   `backend/counts.py:build` into three ordered lists and applies the
   column-major capacities 9/10/9. Preserve blank cells for unused slots.
3. Decide and document whether the archive's parenthetical party text is
   authoritative. If yes, use `name + " (" + party + ")"` consistently; if
   not, store party separately in a future workbook design. Current evidence
   shows both conventions in one day.
4. Define emergency ordering and custom-section inclusion. The API exposes
   `recurring`, daily `emergency`, and `custom_sections`, while the archive
   exposes one unlabeled block. This belongs in the adapter, not in
   `backend/counts.py`.
5. Add an export-time validation pass: exact sheet name, merges, dimensions,
   formula coordinates, formula cached values after recalculation, and title
   date. Reject ambiguous dates rather than deriving the filename from a stale
   archive name.
6. Add a data-review report for rows whose normalized names/counts disagree
   with archive evidence. Do not silently “fix” Arabic labels or assign an
   archive row to a system row when the match is uncertain.

## 7. OPEN QUESTIONS

- Is the operator's AM/PM parenthetical party convention intentional, or should
  one canonical rule be enforced? Evidence conflicts within `2026/9/29`.
- When the API has both `recurring` and daily/custom rows, what exact order is
  required in the single archive emergency block?
- Should `custom_sections` be included in `إجمالي اعداد الخدمات`? The API has a
  `totals.custom` field, but the V2 grand-total formula is only `H4+H14+H35`.
- Are the title's Arabic weekday words and `م` required for fidelity, or only
  the numeric date?
- Are row heights 9 and 27 (and similar manual row-height edits) contractual,
  or should the exporter use the dominant V2 heights?
- For stale files such as `2026/9/20/اعداد الخدمات يوم 19-9-2026.xlsx`, should
  the product treat the folder, filename, or `B2` title as the source of truth?
- Does the system retain historical counts snapshots that correspond to each
  archive workbook, or is the current `/api/counts/<day>` payload the only
  available system-side record? This determines whether count mismatches are
  import loss or expected historical manual edits.
- `openpyxl` 3.1.5 is installed in the environment, but it is not listed in
  `requirements.txt`; should it be added to the analysis/export dependency set?
