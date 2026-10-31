# -*- coding: utf-8 -*-
"""右栏版本双行时间轴模型（C1–C3）。

装配在 controller.render_versions（_render_versions L7829 平移）。
roles：vNo（时间正序编号，C2②最新着 C_ACCENT 由 QML 按 isLatest 渲染）、
timeDisplay（[:10] 显示到日，C6 display/sort 分离）、chip（截断 8 全角字，
C3）、chipFull（全文进 tooltip）、star/isLatest/auto/vid。
"""

from __future__ import annotations

from PySide6.QtCore import (
    Slot,
    QAbstractListModel,
    QByteArray,
    QModelIndex,
    QObject,
    Qt,
)


class VersionsModel(QAbstractListModel):
    VidRole = Qt.ItemDataRole.UserRole + 1
    VNoRole = Qt.ItemDataRole.UserRole + 2
    TimeDisplayRole = Qt.ItemDataRole.UserRole + 3
    TimeSortRole = Qt.ItemDataRole.UserRole + 4
    StarRole = Qt.ItemDataRole.UserRole + 5
    ChipRole = Qt.ItemDataRole.UserRole + 6
    ChipFullRole = Qt.ItemDataRole.UserRole + 7
    IsLatestRole = Qt.ItemDataRole.UserRole + 8
    AutoRole = Qt.ItemDataRole.UserRole + 9
    TooltipRole = Qt.ItemDataRole.UserRole + 10

    _ROLE_MAP = {
        VidRole: "vid", VNoRole: "vNo", TimeDisplayRole: "timeDisplay",
        TimeSortRole: "timeSort", StarRole: "star", ChipRole: "chip",
        ChipFullRole: "chipFull", IsLatestRole: "isLatest",
        AutoRole: "auto", TooltipRole: "tooltip",
    }

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._rows: list[dict] = []

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        r = self._rows[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return r["vNo"]
        return r.get(self._ROLE_MAP.get(role, ""))

    def roleNames(self) -> dict:
        return {k: QByteArray(v.encode()) for k, v in self._ROLE_MAP.items()}

    def reset_rows(self, rows: list[dict]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    @Slot(int, result="QVariantMap")
    def row_at(self, i: int) -> dict:
        return self._rows[i] if 0 <= i < len(self._rows) else {}

    @Slot(str, result=int)
    def index_of_vid(self, vid: str) -> int:
        for i, r in enumerate(self._rows):
            if r["vid"] == vid:
                return i
        return -1

    @property
    def rows(self) -> list[dict]:
        return self._rows
