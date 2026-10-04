"""Shared Qt widgets and icon resource lookup."""

from __future__ import annotations

import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QHeaderView, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)


def icon_directory() -> Path:
    package_icons = Path(__file__).resolve().parent / "resources" / "icons"
    candidates = [package_icons]
    if hasattr(sys, "_MEIPASS"):
        bundle = Path(sys._MEIPASS)
        candidates.extend((bundle / "mt5_workbench" / "ui" / "resources" / "icons",
                           bundle / "src" / "mt5_workbench" / "ui" / "resources" / "icons"))
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return package_icons



def icon(name: str, theme: str, size: int = 20) -> QIcon:
    return QIcon(str(icon_directory() / f"{name}-{theme}-{size}.png"))



def label(value: str = "", *, kind: str = "", size: int | None = None,
          bold: bool = False, wrap: bool = False) -> QLabel:
    item = QLabel(value)
    if kind:
        item.setObjectName(kind)
    if size is not None or bold:
        font = item.font()
        if size is not None:
            font.setPixelSize(size)
        font.setBold(bold)
        item.setFont(font)
    item.setWordWrap(wrap)
    return item



def button(title: str, theme: str, icon_name: str | None = None,
           role: str = "") -> QPushButton:
    item = QPushButton(title)
    if role:
        item.setObjectName(role)
    if icon_name:
        item.setIcon(icon(icon_name, theme))
        item.setIconSize(QSize(18, 18))
    item.setCursor(Qt.CursorShape.PointingHandCursor)
    return item



def card() -> QFrame:
    item = QFrame()
    item.setObjectName("card")
    return item



def make_table(columns: tuple[str, ...], min_height: int = 190) -> QTableWidget:
    table = QTableWidget(0, len(columns))
    table.setHorizontalHeaderLabels(columns)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    table.horizontalHeader().setMinimumSectionSize(65)
    table.verticalHeader().hide()
    table.setAlternatingRowColors(True)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    table.setShowGrid(False)
    table.verticalHeader().setDefaultSectionSize(36)
    table.setMinimumHeight(min_height)
    return table



def fill_table(table: QTableWidget, rows) -> None:
    values = list(rows)
    table.setRowCount(len(values))
    for r, row in enumerate(values):
        for c, value in enumerate(row):
            item = QTableWidgetItem(str(value))
            numeric = isinstance(value, (int, float, Decimal))
            if c and not numeric:
                try:
                    Decimal(str(value).replace(",", "").split()[0])
                    numeric = True
                except (IndexError, InvalidOperation):
                    pass
            if c and numeric:
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            table.setItem(r, c, item)



def metric_card(caption: str) -> tuple[QFrame, QLabel]:
    box = card()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(18, 16, 18, 16)
    layout.setSpacing(6)
    layout.addWidget(label(caption, kind="muted"))
    value = label("—", kind="metricValue")
    layout.addWidget(value)
    return box, value



def chart_card(title: str, chart: QWidget, theme: str,
               icon_name: str, note: str = "") -> tuple[QFrame, QLabel]:
    box = card()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(20, 18, 20, 18)
    header = QHBoxLayout()
    title_label = label(title, kind="sectionTitle")
    header.addWidget(title_label)
    header.addStretch()
    note_label = label(note, kind="muted")
    header.addWidget(note_label)
    layout.addLayout(header)
    layout.addWidget(chart)
    return box, note_label
