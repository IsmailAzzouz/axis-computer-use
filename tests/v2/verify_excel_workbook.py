"""Read-only persisted-file oracle. Never imported or consulted by AXIS runtime.

Read raw OOXML, including the cache Excel actually saved: importing into a
calculation engine could silently recalculate and conceal a stale saved value.
"""
import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from zipfile import ZipFile

NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def verify(path, *, expected_selection=None):
    path = Path(path)
    if path.stat().st_size > 5*1024*1024:
        raise ValueError("Unexpected test workbook size")
    with ZipFile(path) as archive:
        def xml(name):
            if archive.getinfo(name).file_size > 1024*1024:
                raise ValueError("Unexpected test XML size")
            return ET.fromstring(archive.read(name))
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            strings = ["".join(item.itertext()) for item in xml("xl/sharedStrings.xml").findall("s:si", NS)]
        sheet = xml("xl/worksheets/sheet1.xml")
        cells = {}
        for cell in sheet.findall(".//s:sheetData/s:row/s:c", NS):
            raw = cell.findtext("s:v", namespaces=NS)
            kind = cell.get("t", "n")
            value = strings[int(raw)] if kind == "s" else raw
            cells[cell.get("r")] = {"value": value, "type": kind, "formula": cell.findtext("s:f", namespaces=NS)}
        checks = {
            "unicode_persisted": cells.get("A1", {}).get("value") == "élève 中文 😀",
            "a2_numeric": cells.get("A2", {}) == {"value": "21", "type": "n", "formula": None},
            "b1_numeric": cells.get("B1", {}) == {"value": "2", "type": "n", "formula": None},
            "formula_persisted": cells.get("B2", {}).get("formula") == "A2*B1",
            "excel_saved_cache": cells.get("B2", {}).get("value") == "42",
        }
        views = sheet.findall("s:sheetViews/s:sheetView", NS)
        selections = [dict(selection.attrib) for view in views for selection in view.findall("s:selection", NS)]
        if expected_selection is not None:
            # Fresh test workbook: one view, no split/frozen pane, exact single
            # range. Additional/disjoint selections must not pass a subset test.
            checks["selected_range_persisted"] = (
                len(views) == 1 and views[0].find("s:pane", NS) is None and len(selections) == 1
                and selections[0].get("sqref") == expected_selection
                # sqref is the selected range. The active cell is a different
                # fact; Excel can omit it (observed for A1) or focus another
                # cell within the same range. Do not require an unrequested anchor.
                and "pane" not in selections[0])
    return {"oracle": "raw_saved_ooxml_read_only", "path": str(path.resolve()),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "checks": checks,
            "passed": all(checks.values()), "cells": cells, "selections": selections}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument("--report")
    parser.add_argument("--expected-selection")
    args = parser.parse_args()
    result = verify(args.path, expected_selection=args.expected_selection)
    if args.report:
        Path(args.report).write_text(json.dumps(result, ensure_ascii=True, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
