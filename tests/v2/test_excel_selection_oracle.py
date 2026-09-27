"""Independent saved selection oracle rejects supersets, split views and absence."""
from zipfile import ZipFile

import pytest

from .verify_excel_workbook import verify


def workbook(tmp_path, views):
    path = tmp_path/"test.xlsx"
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    with ZipFile(path, "w") as archive:
        archive.writestr("xl/worksheets/sheet1.xml", f'<worksheet {ns}>{views}<sheetData/></worksheet>')
    return path


@pytest.mark.parametrize("anchor", ['', ' activeCell="A1"', ' activeCell="B2"'])
def test_exact_selection_is_separate_from_missing_cell_data(tmp_path, anchor):
    path = workbook(tmp_path, '<sheetViews><sheetView workbookViewId="0"><selection'+anchor+' sqref="A1:B2"/></sheetView></sheetViews>')
    result = verify(path, expected_selection="A1:B2")
    assert result["checks"]["selected_range_persisted"] is True
    assert result["passed"] is False  # Selection is not evidence of data/formulas.
    assert "selected_range_persisted" not in verify(path)["checks"]


@pytest.mark.parametrize("content", [
    '', '<selection activeCell="A1" sqref="A1"/>',
    '<selection activeCell="A1" sqref="A1:C2"/>',
    '<selection activeCell="A1" sqref="A1:B2 D4"/>',
    '<selection activeCell="A1" sqref="A1:B2"/><selection activeCell="D4" sqref="D4"/>',
    '<pane state="frozen"/><selection activeCell="A1" sqref="A1:B2"/>',
    '<selection pane="bottomRight" activeCell="A1" sqref="A1:B2"/>',
])
def test_inexact_or_unqualified_view_never_proves_requested_range(tmp_path, content):
    path = workbook(tmp_path, '<sheetViews><sheetView workbookViewId="0">'+content+'</sheetView></sheetViews>')
    assert verify(path, expected_selection="A1:B2")["checks"]["selected_range_persisted"] is False


def test_multiple_or_missing_views_do_not_prove_selection(tmp_path):
    view = '<sheetView workbookViewId="0"><selection activeCell="A1" sqref="A1:B2"/></sheetView>'
    for views in ('', '<sheetViews>'+view+view+'</sheetViews>'):
        assert verify(workbook(tmp_path, views), expected_selection="A1:B2")["checks"]["selected_range_persisted"] is False
