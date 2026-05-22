from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from zipfile import ZipFile
import xml.etree.ElementTree as ElementTree


WORD_NAMESPACE = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML_NAMESPACE = {"w": WORD_NAMESPACE}


@dataclass(frozen=True)
class DocxCell:
    text: str


@dataclass(frozen=True)
class DocxRow:
    cells: list[DocxCell]


@dataclass(frozen=True)
class DocxTable:
    rows: list[DocxRow]

    def cell(self, row_index: int, column_index: int) -> DocxCell:
        return self.rows[row_index].cells[column_index]


def read_docx_tables(docx_path: Path) -> list[DocxTable]:
    with ZipFile(docx_path) as archive:
        document_xml = archive.read("word/document.xml")

    root = ElementTree.fromstring(document_xml)
    tables: list[DocxTable] = []
    for table_element in root.findall(".//w:tbl", XML_NAMESPACE):
        rows: list[DocxRow] = []
        for row_element in table_element.findall("w:tr", XML_NAMESPACE):
            cells: list[DocxCell] = []
            for cell_element in row_element.findall("w:tc", XML_NAMESPACE):
                cells.append(DocxCell(text=_extract_cell_text(cell_element)))
            rows.append(DocxRow(cells=cells))
        tables.append(DocxTable(rows=rows))

    return tables


def _extract_cell_text(cell_element: ElementTree.Element) -> str:
    parts: list[str] = []
    for text_element in cell_element.findall(".//w:t", XML_NAMESPACE):
        if text_element.text:
            parts.append(text_element.text)
    return "".join(parts).strip()
