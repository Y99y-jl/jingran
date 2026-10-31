# -*- coding: utf-8 -*-
"""中栏文件列表模型（B1/B14 + C6 口径）。

装配在 controller.build_rows（_refresh_files 平移），模型只承载只读行。
排序 display/sort 分离：C6 时间列 display=MM-DD HH:MM（latest_time[5:16]），
sort 用完整 latest_time。
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


class FilesModel(QAbstractListModel):
    NameRole = Qt.ItemDataRole.UserRole + 1
    KindRole = Qt.ItemDataRole.UserRole + 2
    CategoryRole = Qt.ItemDataRole.UserRole + 3
    LatestRole = Qt.ItemDataRole.UserRole + 4        # display：MM-DD HH:MM
    LatestSortRole = Qt.ItemDataRole.UserRole + 5    # sort：完整时间串
    CountRole = Qt.ItemDataRole.UserRole + 6
    IsTrashRole = Qt.ItemDataRole.UserRole + 7
    FidRole = Qt.ItemDataRole.UserRole + 8
    TooltipRole = Qt.ItemDataRole.UserRole + 9
    StarRole = Qt.ItemDataRole.UserRole + 10
    # M40：回收站列专用——控制器 _fill_trash_rows 早已产出这两个字段，
    # 但模型没注册角色，QML 里 model.origCat / model.delTime 恒为 undefined
    # （原分类永远"未分类"、删除时间永远空白）。这里补上角色。
    OrigCatRole = Qt.ItemDataRole.UserRole + 11
    DelTimeRole = Qt.ItemDataRole.UserRole + 12

    _ROLE_MAP = {
        NameRole: "name", KindRole: "kind", CategoryRole: "category",
        LatestRole: "latest", LatestSortRole: "latestSort",
        CountRole: "count", IsTrashRole: "isTrash", FidRole: "fid",
        TooltipRole: "tooltip", StarRole: "star",
        OrigCatRole: "origCat", DelTimeRole: "delTime",
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
            return r["name"]
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
    def index_of_fid(self, fid: str) -> int:
        for i, r in enumerate(self._rows):
            if r["fid"] == fid:
                return i
        return -1

    @property
    def rows(self) -> list[dict]:
        return self._rows
