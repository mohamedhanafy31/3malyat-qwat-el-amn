"""V2 Excel export for the daily ``اعداد الخدمات`` sheet."""

from copy import copy
from datetime import date
from io import BytesIO
from math import ceil

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from .afraad import _time_key
from .service_sections import block_title, split_custom_sections
from .utils import weekday_name


AM_MIN, PM_MIN, EM_MIN = 9, 10, 9
_MEDIUM = Side(style="medium", color="000000")
_THIN = Side(style="thin", color="000000")
_GRAY_HEADER = PatternFill("solid", fgColor="E4E4E4")
_GRAY_TOTAL = PatternFill("solid", fgColor="D9D9D9")


def _rows(payload, key):
    return list(payload.get(key) or [])


def _custom_rows(payload):
    ordinary, _special = split_custom_sections(_rows(payload, "custom_sections"), _time_key)
    return ordinary


def _emergency_rows(payload):
    rows = _rows(payload, "recurring") + _rows(payload, "emergency") + _custom_rows(payload)
    return sorted(rows, key=lambda row: _time_key(row.get("time")))


def compute_totals(payload):
    """Return the numeric values represented by the seven worksheet formulas."""
    am = sum(int(row.get("count") or 0) for row in _rows(payload, "basic_am"))
    pm = sum(int(row.get("count") or 0) for row in _rows(payload, "basic_pm"))
    _ordinary, special = split_custom_sections(_rows(payload, "custom_sections"), _time_key)
    emergency = sum(int(row.get("count") or 0) for row in _emergency_rows(payload))
    emergency += sum(int(row.get("count") or 0) for section in special
                     for row in section["rows"])
    return {"basic_am": am, "basic_pm": pm, "emergency": emergency,
            "grand_total": am + pm + emergency}


def _height(n, minimum):
    return max(minimum, ceil(n / 3))


def _border(left, right, top, bottom):
    return Border(left=left, right=right, top=top, bottom=bottom)


def _normal_border(col, row, start, end):
    left = _MEDIUM if col == 0 else _THIN
    right = _MEDIUM
    top = _MEDIUM if row == start else _THIN
    bottom = _MEDIUM if row == end else _THIN
    return _border(left, right, top, bottom)


def _put_cell(cell, value, *, font, alignment=None, fill=None, border=None, number_format=None):
    cell.value = value
    cell.font = copy(font)
    if alignment is not None:
        cell.alignment = copy(alignment)
    if fill is not None:
        cell.fill = copy(fill)
    if border is not None:
        cell.border = copy(border)
    if number_format is not None:
        cell.number_format = number_format


def _write_block(ws, rows, start, height, service_cols):
    service_font = Font(name="AdvertisingMedium", size=16, bold=True)
    align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for index in range(height * 3):
        item = rows[index] if index < len(rows) else {}
        col_index, offset = divmod(index, height)
        row = start + offset
        service_col, count_col = service_cols[col_index]
        name = str(item.get("name") or "")
        party = str(item.get("party") or "")
        if party:
            name = f"{name} ({party})"
        value = int(item.get("count") or 0) if item else None
        _put_cell(ws.cell(row, service_col), name or None, font=service_font, alignment=align,
                  border=_normal_border(col_index, row, start, start + height - 1))
        _put_cell(ws.cell(row, count_col), value, font=service_font,
                  alignment=align, border=_normal_border(col_index, row, start, start + height - 1))


def _style_header_row(ws, row, emergency=False, total_label=None):
    font = Font(name="AdvertisingMedium", size=16, bold=True)
    align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for col in range(2, 9):
        left = _MEDIUM if col in (2, 8) else _THIN
        right = _MEDIUM if col in (2, 7, 8) else _THIN
        value = ("الخدمة" if col in (2, 4, 6) else "عدد المجندين")
        if col == 8 and total_label:
            value = total_label
        _put_cell(ws.cell(row, col), value,
                  font=font, alignment=align, fill=_GRAY_HEADER if emergency else None,
                  border=_border(left, right, _MEDIUM, _MEDIUM))
    if emergency:
        _put_cell(ws.cell(row, 8), "المجموع الكلي", font=Font(name="AF_Aseer", size=16, bold=True),
                  alignment=Alignment(horizontal="center", vertical="center", wrap_text=True,
                                      textRotation=90), fill=_GRAY_HEADER,
                  border=_border(_MEDIUM, _MEDIUM, _MEDIUM, _MEDIUM))


def _style_title(ws, row, value):
    _put_cell(ws.cell(row, 2), value, font=Font(name="AdvertisingExtraBold", size=22, bold=True),
              alignment=Alignment(horizontal="center", vertical="center", wrap_text=True),
              border=_border(_MEDIUM, _MEDIUM, _MEDIUM, _MEDIUM))
    ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=8)


def _write_emergency_block(ws, title_row, title, rows, *, with_header=False):
    """يكتب كتلة طوارئ ويعيد موضع إجماليها وموضع الصف التالي."""
    ws.row_dimensions[title_row].height = 34.5
    _style_title(ws, title_row, title)
    if with_header:
        header = title_row + 1
        start = header + 1
        ws.row_dimensions[header].height = 50.25
        _style_header_row(ws, header, emergency=True)
    else:
        header = None
        start = title_row + 1
    height = _height(len(rows), EM_MIN if with_header else 1)
    end = start + height - 1
    subtotal = end + 1
    _write_block(ws, rows, start, height, ((2, 3), (4, 5), (6, 7)))
    if header is not None:
        if end - 1 >= header:
            ws.merge_cells(start_row=header, start_column=8, end_row=end - 1, end_column=8)
        _put_cell(ws.cell(header, 8), "المجموع الكلي", font=Font(name="AF_Aseer", size=16, bold=True),
                  alignment=Alignment(horizontal="center", vertical="center", wrap_text=True, textRotation=90),
                  fill=_GRAY_HEADER, border=_border(_MEDIUM, _MEDIUM, _MEDIUM, _MEDIUM))
    for col, letter in ((3, "C"), (5, "E"), (7, "G")):
        _put_cell(ws.cell(subtotal, col), f"=SUM({letter}{start}:{letter}{end})",
                  font=Font(name="Arial", size=16, bold=True),
                  alignment=Alignment(horizontal="center", vertical="center", wrap_text=True),
                  fill=_GRAY_TOTAL, border=_border(_THIN, _THIN, Side(style=None), _MEDIUM),
                  number_format=r'0;\-0;;@')
    for col in (2, 4, 6):
        _put_cell(ws.cell(subtotal, col), "المجموع", font=Font(name="Arial", size=16, bold=True),
                  alignment=Alignment(horizontal="center", vertical="center", wrap_text=True),
                  fill=_GRAY_TOTAL, border=_border(_MEDIUM if col == 2 else _THIN, _THIN,
                                                   Side(style=None), _MEDIUM))
    ws.merge_cells(start_row=end, start_column=8, end_row=subtotal, end_column=8)
    _put_cell(ws.cell(end, 8), f"=C{subtotal}+E{subtotal}+G{subtotal}",
              font=Font(name="Arial", size=16, bold=True),
              alignment=Alignment(horizontal="center", vertical="center", textRotation=90),
              fill=_GRAY_TOTAL, border=_border(_MEDIUM, _MEDIUM, _MEDIUM, _MEDIUM),
              number_format=r'0;\-0;;@')
    ws.row_dimensions[subtotal].height = 21.75
    return subtotal, end, subtotal + 1


def build_xlsx(counts_payload):
    """Build a V2-format workbook from the payload returned by ``counts.build``."""
    am, pm = _rows(counts_payload, "basic_am"), _rows(counts_payload, "basic_pm")
    emergency = _emergency_rows(counts_payload)
    _ordinary_custom, special_blocks = split_custom_sections(_rows(counts_payload, "custom_sections"), _time_key)
    rows_am, rows_pm = _height(len(am), AM_MIN), _height(len(pm), PM_MIN)
    am_start, am_end = 4, 3 + rows_am
    pm_header, pm_start, pm_end = am_end + 1, am_end + 2, am_end + 1 + rows_pm
    emergency_title = pm_end + 2

    wb = Workbook()
    ws = wb.active
    ws.title = "اعداد الخدمات"
    ws.sheet_view.rightToLeft = True
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = 9
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 1
    ws.page_margins.left = ws.page_margins.right = 0.25
    ws.page_margins.top = ws.page_margins.bottom = 0.30
    ws.page_margins.header = ws.page_margins.footer = 0
    for col, width in {"A": 2.42578125, "B": 54.0, "C": 14.0, "D": 50.7109375,
                       "E": 14.0, "F": 50.7109375, "G": 15.28515625,
                       "H": 27.42578125}.items():
        ws.column_dimensions[col].width = width

    ws.row_dimensions[1].height = 9.75
    ws.row_dimensions[2].height = 34.5
    _style_title(ws, 2, f"اعداد الخدمات الصباحية والمسائية الاساسية يوم "
                         f"{weekday_name(counts_payload.get('date'))} "
                         f"{date.fromisoformat(counts_payload['date']).day} / "
                         f"{date.fromisoformat(counts_payload['date']).month} / "
                         f"{date.fromisoformat(counts_payload['date']).year} م")
    _style_header_row(ws, 3, total_label="اجمالي الخدمات الصباحية")
    _write_block(ws, am, am_start, rows_am, ((2, 3), (4, 5), (6, 7)))
    ws.merge_cells(start_row=am_start, start_column=8, end_row=am_end, end_column=8)
    _put_cell(ws.cell(am_start, 8), f"=SUM(C{am_start}:C{am_end})+SUM(E{am_start}:E{am_end})+SUM(G{am_start}:G{am_end})",
              font=Font(name="Arial", size=16, bold=True), alignment=Alignment(horizontal="center", vertical="center", wrap_text=True),
              fill=_GRAY_TOTAL, border=_border(_MEDIUM, _MEDIUM, _MEDIUM, _THIN), number_format='0" مجند"')

    ws.row_dimensions[pm_header].height = 50.25
    _style_header_row(ws, pm_header, total_label="اجمالي الخدمات المسائية")
    _write_block(ws, pm, pm_start, rows_pm, ((2, 3), (4, 5), (6, 7)))
    ws.merge_cells(start_row=pm_start, start_column=8, end_row=pm_end, end_column=8)
    _put_cell(ws.cell(pm_start, 8), f"=SUM(C{pm_start}:C{pm_end})+SUM(E{pm_start}:E{pm_end})+SUM(G{pm_start}:G{pm_end})",
              font=Font(name="Arial", size=16, bold=True), alignment=Alignment(horizontal="center", vertical="center", wrap_text=True),
              fill=_GRAY_TOTAL, border=_border(_MEDIUM, _MEDIUM, _MEDIUM, _THIN), number_format='0" مجند"')

    ws.row_dimensions[pm_end + 1].height = 13.5
    emergency_subtotal, _emergency_end, next_row = _write_emergency_block(
        ws, emergency_title, "خدمات الطوارئ", emergency, with_header=True)
    block_totals = [_emergency_end]
    for section in special_blocks:
        subtotal, block_end, next_row = _write_emergency_block(
            ws, next_row + 1, block_title(section["name"]), section["rows"])
        block_totals.append(block_end)
    grand_start, grand_end = next_row + 4, next_row + 11
    used_end = grand_end + 4
    ws.print_area = f"B2:H{used_end}"
    ws.row_dimensions[next_row].height = 15.75
    for row in range(grand_start, grand_end + 1):
        ws.row_dimensions[row].height = 15.0 if row <= grand_start + 1 else 15.75
    for row in range(grand_end + 1, used_end + 1):
        ws.row_dimensions[row].height = 15.75
    ws.cell(1, 1).font = Font(name="Arial", size=10)  # archive dimensions include A1
    ws.cell(used_end, 8).font = Font(name="Arial", size=10)  # Preserve A1:H52 shape.
    ws.merge_cells(start_row=grand_start, start_column=3, end_row=grand_end, end_column=5)
    ws.merge_cells(start_row=grand_start, start_column=6, end_row=grand_end, end_column=6)
    _put_cell(ws.cell(grand_start, 3), "إجمالي اعداد الخدمات", font=Font(name="Lucida Console", size=22, bold=True),
              alignment=Alignment(horizontal="center", vertical="center", wrap_text=True), fill=_GRAY_TOTAL,
              border=_border(_MEDIUM, _MEDIUM, _MEDIUM, _MEDIUM))
    formula = "=" + "+".join([f"H{am_start}", f"H{pm_start}"] + [f"H{row}" for row in block_totals])
    _put_cell(ws.cell(grand_start, 6), formula,
              font=Font(name="Arial", size=22, bold=True), alignment=Alignment(horizontal="center", vertical="center", wrap_text=True),
              fill=_GRAY_TOTAL, border=_border(_MEDIUM, _MEDIUM, _MEDIUM, _MEDIUM), number_format='0" مجند"')

    wb.calculation.fullCalcOnLoad = True
    output = BytesIO()
    wb.save(output)
    return output.getvalue()
