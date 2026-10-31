# -*- coding: utf-8 -*-
"""左栏分类树扁平模型（D1，方案 C——设计 §2.1）。

树真相在 controller（_col_open 驱动 DFS 扁平化，与生产 VirtualTreeList
`_rows[iid]["open"]` → `_order` 同构）；模型只承载扁平可见序列。
roles 按 spike/设计：cid/name/depth/open/hasChildren/isBuiltin/isTrash。
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


class CategoriesModel(QAbstractListModel):
    CidRole = Qt.ItemDataRole.UserRole + 1
    NameRole = Qt.ItemDataRole.UserRole + 2
    DepthRole = Qt.ItemDataRole.UserRole + 3
    OpenRole = Qt.ItemDataRole.UserRole + 4
    HasChildrenRole = Qt.ItemDataRole.UserRole + 5
    IsBuiltinRole = Qt.ItemDataRole.UserRole + 6
    IsTrashRole = Qt.ItemDataRole.UserRole + 7
    CountRole = Qt.ItemDataRole.UserRole + 8

    _ROLE_MAP = {
        CidRole: "cid", NameRole: "name", DepthRole: "depth",
        OpenRole: "open", HasChildrenRole: "hasChildren",
        IsBuiltinRole: "isBuiltin", IsTrashRole: "isTrash",
        CountRole: "count",
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

    def sync_rows(self, rows: list[dict]) -> None:
        """增量同步：只发必要的 insert/remove/dataChanged，绝不用 reset。

        M17 关键：beginResetModel 会销毁 ListView 的全部 delegate（连同其
        中的 MouseArea），双击手势进行中接收事件的 MouseArea 一旦被销毁，
        mouseDoubleClickEvent 就落空——这是「双击父分类只展开、不进改名」
        的根因。本方法按 cid 剥前/后缀，只动真正变化的中段，让既有行的
        delegate（含 MouseArea）跨开合存活。

        ⚠️ 前后缀比对必须用 cid，不能用整行 dict 相等：展开时父行的 open
        会翻转，按整行比对前缀一位都剥不掉，父行会被当"中段"销毁重建。
        """
        new = list(rows)
        old = self._rows
        n, m = len(old), len(new)
        pre = 0
        while pre < n and pre < m and old[pre]["cid"] == new[pre]["cid"]:
            pre += 1
        suf = 0
        while (suf < n - pre and suf < m - pre
               and old[n - 1 - suf]["cid"] == new[m - 1 - suf]["cid"]):
            suf += 1
        old_mid, new_mid = n - pre - suf, m - pre - suf
        if old_mid:
            self.beginRemoveRows(QModelIndex(), pre, pre + old_mid - 1)
            del self._rows[pre:pre + old_mid]
            self.endRemoveRows()
        if new_mid:
            self.beginInsertRows(QModelIndex(), pre, pre + new_mid - 1)
            self._rows[pre:pre] = new[pre:pre + new_mid]
            self.endInsertRows()
        # 保留段内容变化（open 翻转 / 改名 / depth）：逐行比对发 dataChanged
        for i in range(pre):
            if self._rows[i] != new[i]:
                self._rows[i] = new[i]
                self.dataChanged.emit(self.index(i), self.index(i))
        for j in range(suf):
            i = m - 1 - j
            if self._rows[i] != new[i]:
                self._rows[i] = new[i]
                self.dataChanged.emit(self.index(i), self.index(i))

    @Slot(int, result="QVariantMap")
    def row_at(self, i: int) -> dict:
        return self._rows[i] if 0 <= i < len(self._rows) else {}

    @Slot(str, result=int)
    def index_of_cid(self, cid: str) -> int:
        for i, r in enumerate(self._rows):
            if r["cid"] == cid:
                return i
        return -1

    @property
    def rows(self) -> list[dict]:
        return self._rows
