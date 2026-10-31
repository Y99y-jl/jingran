# -*- coding: utf-8 -*-
"""AppController —— 唯一 Python↔QML 桥（设计 §1.4 接口表）。

M1：Store 装配 / A1-A5 骨架 / E2 装配。
M2：中栏全功能 B 组——_refresh_files 装配（B1/B14）、_sort_file_tree（B3/C6
双口径）、搜索三态（B10/B11）、file_menu_spec（B8）、B13 刷新保选中、
B1 事件状态机（services/event_sm.py）+ 拖出候选分派（E1 骨架，U3 实测归 M5）。
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import (QObject, Property, QTimer, Signal, Slot)
from PySide6.QtGui import (QDrag, QPixmap, QImage, QPainter,  # noqa: E402
                           QColor, QFont, QFontMetrics, QPen, QGuiApplication)
from PySide6.QtCore import (QMimeData, QUrl, Qt, QPointF, QRectF)

QML_APP = Path(__file__).resolve().parent
if str(QML_APP) not in sys.path:
    sys.path.insert(0, str(QML_APP))

from store import Store, _copy2_writable  # noqa: E402
try:                                    # M74：构建期生成（tools/gen_version.py）
    from app_version import VERSION as APP_VERSION, BUILD_DATE as APP_BUILD
except ImportError:                     # 源码直跑（未生成）时兜底
    APP_VERSION, APP_BUILD = "dev", ""
from models.files_model import FilesModel  # noqa: E402
from models.categories_model import CategoriesModel  # noqa: E402
from models.versions_model import VersionsModel  # noqa: E402
from services import diffworker  # noqa: E402
from services.share import ShareSessions  # noqa: E402
from services.event_sm import FileEventSM  # noqa: E402
from services.sessions import EditSessions  # noqa: E402

SEARCH_DEBOUNCE_MS = 250   # 生产 L472（B4）
FEEDBACK_MS = 4000         # 生产 L473（C14）
# 设计 px（=QML 逻辑像素，PRD 单位口径：禁再乘 1.25）
SASH_MIN_L, SASH_MIN_M, SASH_MIN_R = 180, 320, 250
RIGHT_DEFAULT_W = 250          # M83：与 SASH_MIN_R 对齐，默认就是最窄
LEFT_DEFAULT_W = 248
# B1 列宽（M29：按 UI 规格书 V3 §3 初值；仅展示初值，算法不变）
FILE_COL_DEFAULTS = {"name": 280, "kind": 70, "collection": 110,
                     "latest": 120, "count": 60}
# 生产 L5107 口径
CID_ALL, CID_UNFILED, CID_TRASH = "__all__", "__unfiled__", "__trash__"
BUILTIN_CIDS = (CID_ALL, CID_UNFILED, CID_TRASH)
ACCENT = "#4E6BFF"   # 与 Theme.qml 的 C_ACCENT 保持一致（拖影配色跟主题走）


def _ext_of(name: str) -> str:
    suf = Path(name or "").suffix
    return suf.lower().lstrip(".") if suf else "—"


class AppController(QObject):
    """全部 QML 意图的落点；信号 = Python 侧状态通知。"""

    statusChanged = Signal(str, str)
    filesChanged = Signal()
    rightCollapsedChanged = Signal(bool)
    busyChanged = Signal()               # M89：长任务进行中
    libraryTotalChanged = Signal(int)   # M53：库内总文件数（不含回收站）
    fileColsChanged = Signal()          # M56：文件区列显隐变化
    dragOutFinished = Signal()
    collectionDragOutFinished = Signal()   # M75-2：拖分类出窗口结束（清提示用）
    # M77-6：系统拖放即将开始（exec 之前发）。QML 收到后必须立刻清掉自己画的
    # 跟随卡片——exec 是模态阻塞，之后 QML 再也收不到事件，卡片会僵在原地。
    internalDragStarted = Signal()
    editSaveAsk = Signal(str)                 # G3：编辑会话保存询问（M6 弹窗渲染）
    closeRejected = Signal(str)               # A8：关窗被闸门拦截（pending JSON）
    dialogRequested = Signal(str)             # F 组：弹窗规格（DialogHost 渲染）
    themeChanged = Signal(str)                # T2：主题切换
    hiddenToTray = Signal()                   # M47：隐藏到托盘后通知 main.py
    migrationDone = Signal(str)               # F6：库迁移完成

    def __init__(self, store_dir: str | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._store = Store(store_dir)
        self._model = FilesModel(self)
        self._share = ShareSessions(self._store, after=self._after)
        self._sm = FileEventSM()
        self._timers: list[QTimer] = []

        self._status_args: tuple = ()
        self._feedback_timer: QTimer | None = None
        self._save_fail_warned = False

        # 中栏状态（对齐生产 App 字段口径）
        self._selected_collection = CID_ALL
        self._search_text = ""                # 真实搜索词（占位不算——QML 占位态）
        self._file_sort = ("latest", True)    # C1：默认最近版本倒序（生产 L5122）
        self._selected_fids: list[str] = []   # B5：QML 镜像回写
        self._current_meta = None             # on_file_selected 的 meta 缓存
        self.metas: list[dict] = []
        self._trash_rows: dict[str, dict] = {}
        self._last_view: dict = {}            # 最近一次 refresh 的空态/计数信息
        self._pending_rows: list[dict] = []   # build_rows 产出，reload 消费

        self._library_total = 0
        self.migrationDone.connect(self._on_migration_done)
        # M56：文件区列显隐（存库 config.ui.cols_hidden，键为列 key）
        _ui = self._store.config.get("ui", {}) or {}
        self._cols_hidden = set(x for x in (_ui.get("cols_hidden") or [])
                                if isinstance(x, str))
        # M62：列顺序（存 key 列表；缺省按 FILE_COL_META 原始顺序）
        _ord = [x for x in (_ui.get("cols_order") or []) if isinstance(x, str)]
        _keys = [k for k, _ in self.FILE_COL_META]
        self._cols_order = ([k for k in _ord if k in _keys]
                            + [k for k in _keys if k not in _ord])
        self._right_collapsed = bool(
            (self._store.config.get("ui", {}) or {}).get("right_collapsed", False))
        self._file_col_w = dict(FILE_COL_DEFAULTS)

        # ---- 左栏树状态（D1/D2/D3/D5；生产 App._col_* 字段口径）----
        self._col_open: dict[str, bool] = {}
        saved_open = (self._store.config.get("ui", {}) or {}).get("col_open")
        if isinstance(saved_open, dict):
            self._col_open = {str(k): bool(v) for k, v in saved_open.items()}
        self._col_branch_ids: set[str] = set()
        self._col_click_restore: tuple[str, bool] | None = None  # (cid, 展开态) 双击/拖拽回滚
        self._col_edit_cid: str | None = None
        self._col_edit_at: float = 0.0
        self._col_drag_row: str | None = None
        self._col_drag_hit: bool = False
        self._col_drag_start: tuple[int, int] = (0, 0)
        self._col_pending_toggle = None   # M72：(cid, already, before_open)
        self._reveal_cid: str = ""              # M33：新建分类后滚动可见（takeRevealCid 消费）
        self._new_col_initial: str = ""         # M33：命名弹窗校验失败时保留的输入
        self._cat_model = CategoriesModel(self)
        self._drop_indicator: dict = {}       # {"mode": into/before/after/end, "ref": cid}
        self._rebuild_categories()

        # ---- 右栏版本区（C1–C9）+ Diff（H2，后台线程）----
        self._ver_model = VersionsModel(self)
        self._ver_sort = ("time", True)       # C1：默认时间倒序（生产 L5123）
        self._selected_vids: list[str] = []   # C5：QML 镜像
        self._ver_anchor: int = -1            # M64：Shift 范围选择锚点
        self._diff_seq = 0                    # 丢弃过期 diff 回填（竞态护栏）

        # ---- M5：拖拽三链路 + 编辑会话 ----
        self._edit_sessions = EditSessions(
            self._store, after=self._after,
            on_ask=lambda a: self.editSaveAsk.emit(
                json.dumps(a, ensure_ascii=False)))
        self._edit_sessions.restore()         # G7 重启兜底（A11）
        self._orphan_queue = list(self._edit_sessions.orphans)  # G4：QML 就绪后补弹
        self._save_as_ctx = None            # M85：另存为文件的上下文
        self._busy = False                  # M89：忙碌态
        self._ver_sm = FileEventSM()          # C11：右栏拖出状态机（与 B1 同构）
        self._drag_in_progress = False        # E1 QDrag exec 模态标志
        # M77：当前拖拽载荷（"拖出后又拖回窗口"时靠它判断该做什么）
        #   {"kind": "files", "fids": [...]}  或  {"kind": "collection", "cid": ...}
        self._drag_payload = None

        # ---- M6：F 组弹窗引擎（规格 Python 组装可单测，QML 渲染，结果回调）----
        self._dialog_seq = 0
        self._pending_dialogs: dict[str, callable] = {}

        # T2：主题持久化（ui.theme 新键；生产 theme.json 独立文件，口径已声明）
        self._theme_mode = (self._store.config.get("ui", {}) or {}).get(
            "theme", "light")
        # M47：关闭窗口时隐藏到托盘（默认开，存在库 config.ui.closeToTray）
        self._close_to_tray = bool(
            (self._store.config.get("ui", {}) or {}).get("closeToTray", True))
        self._force_quit = False
        saved = (self._store.config.get("ui", {}) or {}).get("file_col_w")
        if isinstance(saved, dict):
            for k in self._file_col_w:
                # M25：接受任意整数（含 <20 甚至负基准）——M25 相邻让位
                # 的补偿写入（setCWRaw）会让右邻列基准合法低于 min，显示
                # 安全由 lw() 钳底/再分配兜底；若在这里弹回默认值，重启后
                # Σ基准偏移 ⇒ 全部边界平移，拖动结果不能复现。
                if isinstance(saved.get(k), int):
                    self._file_col_w[k] = saved[k]

        self.reload_files()

    # ---------------- 属性 ----------------
    @property
    def model(self) -> FilesModel:
        return self._model

    @property
    def catModel(self) -> CategoriesModel:
        return self._cat_model

    @property
    def verModel(self) -> VersionsModel:
        return self._ver_model

    @property
    def store(self) -> Store:
        return self._store

    @Property(int, notify=libraryTotalChanged)
    def libraryTotal(self) -> int:
        """库内受管文件总数（与当前视图无关，回收站不计）。"""
        return self._library_total

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        """M89：长任务（提交/导出）进行中——QML 用它显示转圈并禁用重复点击。"""
        return self._busy

    def _set_busy(self, on: bool, msg: str = "") -> None:
        """置忙碌态并立刻刷一次事件循环，否则界面在阻塞结束前不会重绘。"""
        if self._busy == on:
            return
        self._busy = on
        self.busyChanged.emit()
        if on and msg:
            self.status(msg, "info")
        try:
            from PySide6.QtWidgets import QApplication
            QApplication.processEvents()
        except Exception:
            pass

    @Property(bool, notify=rightCollapsedChanged)
    def rightCollapsed(self) -> bool:
        """M12：改 PySide @Property（原内建 @property 对 QML 不可读 →
        FileListPane 收起态自动展开分支失效）。"""
        return self._right_collapsed

    @property
    def fileSort(self) -> tuple[str, bool]:
        return self._file_sort

    # ================ 中栏装配（_refresh_files 平移）================
    def build_rows(self) -> dict:
        """_refresh_files 主体（无 Tk）：产出行列表 + 视图信息（空态/计数）。"""
        in_trash = (self._selected_collection == CID_TRASH)
        all_metas = self._store.file_list()
        self.metas = all_metas
        kw = self._search_text.lower()        # 占位文字不算搜索词（QML 已保证）
        # M83：点主分类只看**直属文件**，不含子分类里的。
        # （原来是 collection_scope —— 含全部子孙，用户反馈"点父分类看到
        #  所有子分类的文件"不符合直觉；要看某个子分类就点它自己。）
        # 导出/统计仍走 collection_scope，不受影响。
        scope = None
        if self._selected_collection not in BUILTIN_CIDS:
            scope = {self._selected_collection}

        rows: list[dict] = []
        shown = 0
        self._trash_rows = {}
        if in_trash:
            shown, total = self._fill_trash_rows(kw, rows)
        else:
            scope_total = 0
            for meta in all_metas:
                if self._selected_collection == CID_UNFILED:
                    if meta.get("category"):
                        continue
                elif scope is not None:
                    if meta.get("category") not in scope:
                        continue
                scope_total += 1          # M64：total 按当前范围计（原为全库数）
                if kw and kw not in meta.get("search_text", ""):
                    continue
                rows.append(self._file_row(meta))
                shown += 1
            total = scope_total

        # 排序（生产：默认 (latest,True) 不重排——file_list 装配序即时间倒序）
        if self._file_sort != ("latest", True):
            col, desc = self._file_sort
            rows.sort(key=self._sort_key(col), reverse=desc)

        # 空态三分支（生产 1:1）+ 命中行信息（R7 #7）
        view = {"shown": shown, "total": total, "kw": kw, "inTrash": in_trash,
                "collection": self._collection_label()}
        if shown == 0:
            if kw:
                view["emptyState"] = "search"
                view["emptyTitle"] = "没有匹配的文件"
                view["emptySub"] = ("换个关键词，或点击下面的按钮查看全部文件\n"
                                    "（搜索范围：文件名 / 修改原因 / 意见来源）")
                view["showCommitBtn"] = False
                view["showClearSearchBtn"] = True
            elif in_trash:
                view["emptyState"] = "trash"
                view["emptyTitle"] = "回收站是空的"
                # M35 §3.3：回收站独立空态语（原「在设置里可以一键清空回收站」
                # 是库空态错语——回收站自己的清空入口就在本视图行内）
                view["emptySub"] = ("删除的文件会先保存在这里，可随时还原；\n"
                                    "清空后不可恢复")
                view["showCommitBtn"] = False
                view["showClearSearchBtn"] = False
            else:
                view["emptyState"] = "library"
                # M53：空分类与空库分开说
                if self._selected_collection not in BUILTIN_CIDS:
                    view["emptyTitle"] = "这个分类还没有文件"
                    view["emptySub"] = ("把文件拖到这里，或从其他分类拖过来；\n"
                                        "也可以用右键「移动到分类」")
                else:
                    # P2：本分支文案不再被下方无条件覆盖（空分类错说成空库）
                    view["emptyTitle"] = "还没有受管的文件"
                    view["emptySub"] = ("把文件或文件夹拖到这里，提交第一个版本\n"
                                        "提交第一个版本后，可展开版本历史查看详情；\n"
                                        "另存为/删除版本在版本列表的右键菜单里")
                view["showCommitBtn"] = True
                view["showClearSearchBtn"] = False
        else:
            view["emptyState"] = "none"
            view["showCommitBtn"] = False
            view["showClearSearchBtn"] = False
        _n = len(self.metas)
        if _n != self._library_total:
            self._library_total = _n
            self.libraryTotalChanged.emit(_n)
        view["searchInfo"] = (f"命中 {shown} / 共 {total}（关键词：{kw}）" if kw else "")
        self._last_view = view
        self._pending_rows = rows
        return view

    def _collection_label(self) -> str:
        """M47：中栏标题用——当前分类的显示名（QML 不再靠树反查）。"""
        cid = self._selected_collection
        if cid == CID_TRASH:
            return "回收站"
        if cid == CID_UNFILED:
            return "未分类"
        if cid in (CID_ALL, None, ""):
            return "全部文件"
        try:
            return self._store.collection_name(cid) or "全部文件"
        except Exception:  # noqa: BLE001
            return "全部文件"

    def _file_row(self, meta: dict) -> dict:
        """正常文件行（列口径生产 L6985-7001；时间降噪 L6996）。"""
        cat = meta.get("category")
        cat_disp = ("/".join(self._store.collection_path(cat)) if cat else "—")
        latest_time = meta.get("latest_time", "")
        shown_time = (latest_time[5:16]
                      if isinstance(latest_time, str) and len(latest_time) >= 16
                      else latest_time)
        fid = meta["fid"]
        return {
            "fid": fid, "name": meta.get("name", ""),
            "kind": _ext_of(meta.get("name", "")),
            "category": cat_disp, "latest": shown_time,
            "latestSort": latest_time,
            "count": meta.get("version_count", 0),
            "star": bool((meta.get("versions") or [{}])[-1].get("star")),
            "isTrash": False, "tooltip": self._file_row_tip(fid),
        }

    def _fill_trash_rows(self, kw: str, rows: list[dict]) -> tuple[int, int]:
        """_fill_trash_rows 平移：回收站伪行（B14，iid 前缀 trash#）。"""
        items = self._store.trash_items()
        total = len(items)
        shown = 0
        for it in items:
            name = it.get("name") or "(未命名)"
            if kw and kw not in name.lower() and \
                    kw not in str(it.get("deleted_at") or "").lower():
                continue
            iid = "trash#" + str(it.get("id") or shown)
            self._trash_rows[iid] = it
            cat = it.get("category")
            cat_disp = ("/".join(self._store.collection_path(cat)) if cat else "—")
            t = str(it.get("latest_time") or "")
            shown_time = t[5:16] if len(t) >= 16 else (t or "—")
            cat_path = ("/".join(self._store.collection_path(cat)) if cat else "未分类")
            ver = it.get("version") or {}
            if ver:
                # M50：删的是单个版本时，名字后带上版本标识，回收站里可区分
                _lab = ver.get("no")
                if not _lab:
                    _t = str(ver.get("time") or "")
                    _lab = _t[5:16] if len(_t) >= 16 else "单个版本"
                name = f"{name}（{_lab}）"
            rows.append({
                "fid": iid, "name": name,
                "kind": it.get("ext") or _ext_of(name),
                "category": cat_disp, "latest": shown_time,
                "latestSort": t,
                "count": int(it.get("version_count") or 0),
                "star": False,
                "isTrash": True,
                # M35 §3.2：回收站独立列头（原分类 / 删除时间）——行字段上移，
                # 不再只活在 tooltip 里（FileListPane 据 isTrash 切换列）
                "origCat": cat_path,
                "delTime": it.get("deleted_at") or "未知",
                "tooltip": (f"{name}\n原分类：{cat_path}\n"
                            f"删除时间：{it.get('deleted_at') or '未知'}"),
            })
            shown += 1
        return shown, total

    def reload_files(self, keep_selection: bool = False) -> None:
        """refresh_files：装配 + 选择恢复（B13：存活者保留、消失者丢弃）。

        M32：文件成员的任何变化（转移/提交/删除/冲突结算）都经本方法落
        地，故在此重建分类树——否则计数胶囊停留在旧值（例：把文件拖到
        别的分类后，旧分类计数仍包含它，肉眼与「已移走」矛盾）。
        _rebuild_categories 走 CategoriesModel.sync_rows 增量同步（按 cid
        剥前后缀 + dataChanged），不销毁 delegate，M17 双击改名手势不受
        影响。递归安全：仅当选中分类被删时它会再调本方法一次，届时
        _selected_collection 已回落 CID_ALL（必在树行中），不会继续深入。
        """
        prev = list(self._selected_fids) if keep_selection else []
        view = self.build_rows()
        self._model.reset_rows(self._pending_rows)
        self._rebuild_categories()
        if keep_selection:
            # P0：只保留仍在中栏的 fid（删除后消失的必须丢），随后由
            # _sync_detail_state 按存活 fid 重新载入 meta / 版本模型。
            self._selected_fids = [f for f in prev
                                   if self._model.index_of_fid(f) >= 0]
        else:
            self._selected_fids = []
        self._sync_detail_state()
        self.filesChanged.emit()
        self.set_status_fit(self._last_view.get("total", 0),
                            "回收站" if self._last_view.get("inTrash") else None)

    def _sync_detail_state(self) -> None:
        """P0：右栏缓存（meta / 版本模型 / 版本选中 / 空态）唯一同步点。

        reload_files 的每条路径都必须过这里：否则删掉文件后 _current_meta
        与 _ver_model 仍指着已删文件——右栏继续显示它的版本，甚至还能对
        它执行「删除此版本」。keep_selection 只决定中栏选中集是否保留，
        不决定缓存去留：缓存一律按当前存活选择重新推导。
        """
        if getattr(self, "_ver_model", None) is None:
            return          # __init__ 早期 _rebuild_categories 回灌时的合法空窗
        fids = [f for f in self._selected_fids if not f.startswith("trash#")]
        meta = self._store.load_meta(fids[0]) if len(fids) == 1 else None
        self._current_meta = meta
        if meta:
            ids = {v.get("id") for v in (meta.get("versions") or [])}
            vids = [v for v in self._selected_vids if v in ids]
            if not vids:
                vers = meta.get("versions") or []
                if vers:
                    chrono = sorted(vers, key=lambda v: str(v.get("time") or ""))
                    vids = [chrono[-1].get("id")]
            self._selected_vids = vids
        else:
            self._selected_vids = []
        if meta:
            self.render_versions()          # 内部 reset_rows + 空态 + verChanged
        else:
            self._ver_model.reset_rows([])
            self._set_ver_empty("nofile")
            self.verChanged.emit()
        self._emit_detail()

    # ---------------- 状态栏（A4）----------------
    def set_status_fit(self, total: int, label: str | None = None) -> None:
        self._status_args = (total, label)
        if self._feedback_timer is None or not self._feedback_timer.isActive():
            self._emit_status_fit()

    def _emit_status_fit(self) -> None:
        total, label = self._status_args if self._status_args else (0, None)
        text = f"{label}：{total} 项" if label else f"{total} 个文件"
        self.statusChanged.emit(text, "dim")

    @Slot(str, str)
    def status(self, msg: str, kind: str = "dim") -> None:
        """C14：反馈着色 + 4s 自动回落；反馈期内计数不覆盖（BUG-1 口径）。"""
        self.statusChanged.emit("  " + msg, kind)
        if self._feedback_timer is None:
            self._feedback_timer = QTimer(self)
            self._feedback_timer.setSingleShot(True)
            self._feedback_timer.timeout.connect(self._feedback_expire)
        self._feedback_timer.start(FEEDBACK_MS)

    def _feedback_expire(self) -> None:
        self._emit_status_fit()

    @Slot(str)
    def warnSaveFailed(self, msg: str) -> None:
        if self._save_fail_warned:
            return
        self._save_fail_warned = True
        self.status(f"提示：界面设置写入磁盘失败（{msg}）。"
                    "请检查磁盘空间/权限后重试；数据仍在内存里。", "err")

    # ---------------- 分类切换（on_collection_selected 平移）----------------
    @Slot(str)
    def selectCollection(self, cid: str) -> None:
        """同值/空选择不是真实切换（BUG-1 口径）。"""
        if not cid or cid == self._selected_collection:
            return
        self._selected_collection = cid
        if cid == CID_TRASH:
            self._enter_trash_state()
        self.reload_files()

    def _enter_trash_state(self) -> None:
        """M54：进入回收站的统一副作用——清空文件/版本选中、清版本模型、
        收起右侧版本栏（回到「未选中文件」状态）。selectCollection 与
        treePress 两条入口共用。"""
        self._selected_fids = []
        self._selected_vids = []
        self._current_meta = None
        self._ver_model.reset_rows([])
        if not self._right_collapsed:
            self._right_collapsed = True
            self.rightCollapsedChanged.emit(True)

    @Slot()
    def refresh(self) -> None:
        """F5 整体刷新（不保选中）。"""
        self.reload_files()

    # ---------------- 搜索（B10/B11）----------------
    @Slot(str)
    def searchApply(self, text: str) -> None:
        """_apply_search_filter 平移：250ms 防抖到期 → keep_selection 刷新。"""
        self._search_text = (text or "").strip()
        self.reload_files(keep_selection=True)

    @Slot()
    def clearSearch(self) -> None:
        """M12：QML「× 清空」按钮入口（原调 controller.clearSearch，
        而 controller 无此名 → TypeError 被吞、按钮失效）。"""
        self.clearSearchToPlaceholder()

    @Slot()
    def clearSearchToPlaceholder(self) -> None:
        """_clear_search_to_placeholder 平移（Esc /「清空」按钮复用）。"""
        self._search_text = ""
        self.reload_files()

    # ---------------- 排序（B3/C6）----------------
    @staticmethod
    def _sort_key(col: str):
        """生产 _sort_file_tree 的 _k：数值优先 (0,int,"")，否则 (1,0,lower)。"""
        def key(row: dict):
            v = row["name"] if col == "name" else (
                row.get("latestSort") if col == "latest" else row.get(col, ""))
            try:
                return (0, int(v), "")
            except (TypeError, ValueError):
                return (1, 0, str(v).lower())
        return key

    @Slot(str, result=str)
    def sortFiles(self, col: str) -> str:
        """_sort_file_tree 平移：首点 name 升序、其余列首点降序；不重读盘、不清选中。"""
        cur_col, cur_desc = self._file_sort
        desc = (not cur_desc) if cur_col == col else (col != "name")
        self._file_sort = (col, desc)
        rows = list(self._model.rows)
        rows.sort(key=self._sort_key(col), reverse=desc)
        self._model.reset_rows(rows)
        return json.dumps({"col": col, "desc": desc})

    @Slot(result=str)
    def fileSortState(self) -> str:
        return json.dumps({"col": self._file_sort[0], "desc": self._file_sort[1]})

    # ---------------- 列宽（B4；新键 file_col_w，旧版保存时忽略/覆盖可接受）---
    @Slot(str, int)
    def resizeColumn(self, col: str, w: int) -> None:
        # M21b：原 w >= 40 下限删除——末列（版本数）作为拖动吸收列，其
        # 基准被反向补偿后可低于 40 甚至为负（显示宽由 lw() 抬底 + 水位
        # 分配兜底，永不负宽）。若拒收，重启后 Σ基准偏移 ⇒ 全部边界平移，
        # 拖动结果不能复现。QML 侧 setCW/setCWRaw 已按列各自钳制。
        if col in self._file_col_w:
            self._file_col_w[col] = int(w)
            ui = self._store.config.get("ui", {}) or {}
            ui["file_col_w"] = dict(self._file_col_w)
            self._store.config["ui"] = ui
            self._write_ui_config()

    FILE_COL_META = [("name", "文件名"), ("kind", "文件类型"),
                     ("collection", "分类"), ("latest", "最近版本"),
                     ("count", "版本数"), ("star", "星标")]

    @Slot(result=str)
    def fileColumnsSpec(self) -> str:
        """M56/M62：文件区列清单（按用户顺序返回；visible 为当前显隐）。"""
        meta = dict(self.FILE_COL_META)
        order = list(self._cols_order) or [k for k, _ in self.FILE_COL_META]
        return json.dumps([
            {"key": k, "title": meta.get(k, k),
             "visible": k not in self._cols_hidden}
            for k in order if k in meta])

    @Slot(str)
    def setFileColumnOrder(self, order_json: str) -> None:
        """M62：拖表头换列顺序（只接受已知 key，忽略未知项）。"""
        try:
            order = [str(x) for x in json.loads(order_json)]
        except (ValueError, TypeError):
            return
        keys = [k for k, _ in self.FILE_COL_META]
        order = [k for k in order if k in keys]
        order += [k for k in keys if k not in order]
        if order == self._cols_order:
            return
        self._cols_order = order
        ui = self._store.config.get("ui", {}) or {}
        ui["cols_order"] = order
        self._store.config["ui"] = ui
        self._write_ui_config()
        self.fileColsChanged.emit()

    @Slot(str, bool)
    def setFileColumnVisible(self, key: str, on: bool) -> None:
        if key not in [k for k, _ in self.FILE_COL_META]:
            return
        if on:
            self._cols_hidden.discard(key)
        else:
            self._cols_hidden.add(key)
        ui = self._store.config.get("ui", {}) or {}
        ui["cols_hidden"] = sorted(self._cols_hidden)
        self._store.config["ui"] = ui
        self._write_ui_config()
        self.fileColsChanged.emit()
        # 列变化会改变可视宽度 → 让中栏重新装配一次（列宽再分配）
        self.reload_files(keep_selection=True)

    @Slot()
    def resetFileColumns(self) -> None:
        self._cols_hidden = set()
        ui = self._store.config.get("ui", {}) or {}
        ui["cols_hidden"] = []
        self._store.config["ui"] = ui
        self._write_ui_config()
        self.fileColsChanged.emit()
        self.reload_files(keep_selection=True)

    @Slot(result=str)
    def fileColWidths(self) -> str:
        return json.dumps(self._file_col_w)

    # ---------------- 选择镜像（B5）+ 菜单（B8）----------------
    @Slot(str)
    def setSelection(self, fids_json: str) -> None:
        try:
            self._selected_fids = list(json.loads(fids_json))
        except ValueError:
            self._selected_fids = []
        fids = [f for f in self._selected_fids if not f.startswith("trash#")]
        self._current_meta = self._store.load_meta(fids[0]) if len(fids) == 1 else None
        # M37：版本卡片高亮改跟「选中」走后，点文件默认选中其最新版本
        # （否则点完文件没有任何卡片高亮，默认观感反而丢了）。
        # ⚠️ 「最新」口径必须与 render_versions 的 chrono 逐字一致：
        # 同秒提交时 max() 与 sorted()[-1] 的 tie-break 不同（max 取首个
        # 极大值，stable sort[-1] 取末位）——曾导致默认选中了旧版本。
        self._selected_vids = []
        if self._current_meta:
            vers = self._current_meta.get("versions") or []
            if vers:
                chrono = sorted(vers, key=lambda v: str(v.get("time") or ""))
                self._selected_vids = [chrono[-1].get("id")]
        self.render_versions()
        self._emit_detail()

    @Slot(result=str)
    def fileMenuSpec(self) -> str:
        """_file_menu_spec 平移：按选中集生成（纯数据，M2 单测口径）。"""
        fids = [f for f in self._selected_fids if not f.startswith("trash#")]
        n = len(fids)
        many = n > 1
        spec = [
            {"label": "打开（编辑最新版本）", "key": "open",
             "state": "normal" if n == 1 else "disabled", "danger": False, "accel": ""},
            {"label": f"创建副本（{n} 个）" if many else "创建副本", "key": "copy",
             "state": "normal" if n >= 1 else "disabled", "danger": False, "accel": ""},
            {"label": f"移动到分类…（{n} 个）" if many else "移动到分类…", "key": "move",
             "state": "normal" if n >= 1 else "disabled", "danger": False, "accel": ""},
            {"label": f"重命名…（{n} 个）" if many else "重命名…",
             "key": "rename",
             "state": "normal" if n == 1 else "disabled", "danger": False, "accel": "F2"},
            {"label": (f"另存为…（{n} 个）" if many else "另存为…"),
             "key": "save_as",
             "state": "normal" if n >= 1 else "disabled", "danger": False,
             "accel": ""},
            {"sep": True},
            {"label": (f"删除 {n} 个文件记录（移入回收站）…" if many
                       else "删除整个文件记录（移入回收站）…"), "key": "delete",
             "state": "normal" if n >= 1 else "disabled", "danger": True, "accel": ""},
        ]
        return json.dumps({"spec": spec, "fids": fids,
                           "trash": bool(self._selected_fids) and
                           all(f.startswith("trash#") for f in self._selected_fids)})

    # P1：历史桩 fileMenuAction（M2 的 copy/locate + 假实现提示）已删——
    # Python 后定义覆盖前定义，真实现只保留文末「分派点消费」那一份。

    # ---------------- tooltip（B9/C6）----------------
    def _file_row_tip(self, fid: str) -> str:
        """_file_row_tip 平移：文件行=名+分类路径；回收站行=原分类+删除时间。"""
        it = self._trash_rows.get(fid)
        if it is not None:
            cat = it.get("category")
            path = "/".join(self._store.collection_path(cat)) if cat else "未分类"
            return (f"{it.get('name', '')}\n原分类：{path}\n"
                    f"删除时间：{it.get('deleted_at') or '未知'}")
        e = next((m for m in self.metas if m.get("fid") == fid), None)
        if not e:
            return ""
        cat = e.get("category")
        path = "/".join(self._store.collection_path(cat)) if cat else "未分类"
        return f"{e.get('name', '')}\n分类：{path}"

    # ---------------- B1 事件状态机（services/event_sm.py，可单测）---------
    @Slot(str, result=str)
    def fileEvent(self, ev_json: str) -> str:
        """QML MouseArea 原始事件 → 状态机 → 意图 JSON（QML 应用）。"""
        ev = json.loads(ev_json)
        op = ev.get("op")
        intents: list[dict] = []
        if op == "press":
            # M65：统一操作语言——Ctrl 只做加减选，整段用 Shift
            intents = self._sm.press(
                ev["row"], ev["x"], ev["y"],
                ctrl=ev.get("ctrl", False), shift=ev.get("shift", False),
                selection=list(self._selected_fids),
                is_trash=ev.get("isTrash", False),
                select_range=self._select_range_fn(ev.get("modsAnchor", -1)),
                row_index=ev.get("rowIndex", -1))
        elif op == "move":
            intents = self._sm.move(
                ev["x"], ev["y"], gx=ev["gx"], gy=ev["gy"],
                win_x=ev["winX"], win_y=ev["winY"],
                win_w=ev["winW"], win_h=ev["winH"])
        elif op == "release":
            intents = self._sm.release()
        elif op == "doubleClick":
            intents = self._sm.double_click()
        elif op == "dragOutFinished":
            self._sm.drag_out_finished()
            self._ver_sm.drag_out_finished()
            self.dragOutFinished.emit()
        for it in intents:
            if it.get("op") == "select":
                self._selected_fids = list(it["fids"])
            elif it.get("op") == "internal_drag":
                # M31：拖拽跟随图标的数据（QML 自绘；拖出窗口由 QDrag 系统接管）
                fids = it.get("fids") or []
                it["count"] = len(fids)
                ext = ""
                if fids:
                    i = self._model.index_of_fid(fids[0])
                    if i >= 0:
                        ext = str(self._model.rows[i].get("kind") or "")
                it["ext"] = ext
            elif it.get("op") == "external_drag":
                self._start_drag_out(list(it["fids"]))
        return json.dumps({"intents": intents,
                           "selected": self._selected_fids})

    def _select_range_fn(self, anchor: int):
        """shift 范围选择（Tk extended：anchor=上次单选/锚点行 index）。"""
        def fn(row_index: int) -> list[str]:
            i0 = anchor if anchor >= 0 else row_index
            lo, hi = sorted((i0, row_index))
            rows = self._model.rows
            return [rows[i]["fid"] for i in range(lo, min(hi + 1, len(rows)))]
        return fn

    @Slot(result=str)
    def getSelection(self) -> str:
        """QML 侧选择镜像回读（B13 恢复后同步）。"""
        return json.dumps(self._selected_fids)

    @Slot(result=str)
    def lastView(self) -> str:
        """最近一次 refresh 的视图信息（空态/命中行/计数——B10/B11 消费）。"""
        return json.dumps(self._last_view)

    @Slot(result=str)
    def storeDir(self) -> str:
        """M29：侧栏库信息卡展示用（只读，绝不修改库）。"""
        return str(self._store.store_dir)

    @Slot(result=str)
    def currentFileInfo(self) -> str:
        """M29：检查器头部展示用的只读投影（纯展示，不改任何业务状态）。

        数据全部来自已加载的 _current_meta（setSelection 维护），无磁盘 IO。
        返回 {} 表示当前没有选中文件（右栏显示空态）。
        """
        meta = self._current_meta
        if not meta:
            return json.dumps({})
        vers = meta.get("versions") or []
        latest = vers[-1] if vers else {}
        cat = meta.get("category")
        return json.dumps({
            "fid": meta.get("fid", ""),
            "name": meta.get("name", ""),
            "ext": _ext_of(meta.get("name", "")),
            "size": int(latest.get("size") or 0),
            "count": len(vers),
            "star": bool(latest.get("star")),
            "category": ("/".join(self._store.collection_path(cat))
                         if cat else "未分类"),
        }, ensure_ascii=False)

    @Slot(str, result=str)
    def pointerOutsideRoot(self, pos_json: str) -> str:
        """_pointer_outside_root 平移（越界判定在 controller，陷阱 d）。"""
        ev = json.loads(pos_json)
        sm = self._sm
        out = sm._outside_root(ev["gx"], ev["gy"], ev["winX"], ev["winY"],
                               ev["winW"], ev["winH"])
        return json.dumps({"outside": bool(out)})

    # ---------------- 拖出（E1 骨架；U3 实测归 M5）----------------
    def _start_drag_out(self, fids: list[str]) -> None:
        """选中集 → 各自最新版本物化（E2）→ QDrag exec；结束必发 dragOutFinished。"""
        pairs = []
        for fid in fids:
            meta = self._store.load_meta(fid)
            if not meta:
                continue
            ver = self._store.latest_version(meta)
            if ver is not None:
                pairs.append((meta, ver))
        if not pairs:
            self.dragOutFinished.emit()
            return
        # M77-6：在 materialize 之前就通知 QML 收卡片——物化文件要花时间，
        # 这段时间正好够界面重绘一次；放到 exec 前就来不及了。
        self.internalDragStarted.emit()
        paths = self._share.materialize_share(pairs)   # E2：一次拖拽一个会话目录
        if not paths:
            self.dragOutFinished.emit()
            return
        self.status(f"正在拖出 {len(paths)} 个文件…", "info")
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(p) for p in paths])
        mime.setText("\n".join(Path(p).name for p in paths))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(self._drag_pixmap(len(paths), paths))
        # M77：记录载荷，拖回窗口内落在分类树上时就能改分类（而不是必须
        # 先松手再重新拖）。finally 保证任何路径下都不会残留。
        self._drag_payload = {"kind": "files", "fids": list(fids)}
        try:
            drag.exec(Qt.DropAction.CopyAction)
        finally:
            self._drag_payload = None
            # 模态返回 → 复位状态机 + 20s 延迟清理（E2 口径）
            self._share.on_drag_end()
            self.dragOutFinished.emit()
        self.status(f"已拖出 {len(paths)} 个文件（20 秒后自动清理临时副本）", "ok")

    @staticmethod
    def _drag_font(point_size: float, bold: bool = False) -> QFont:
        """拖影专用字体（point_size 用磅值，可带小数——QML 那边是
        `font.pointSize: Theme.pt(12.5)`，两边要能对上同一个物理字号）。

        为什么要显式给族名：QPainter 在 QImage 上画字用的是"默认字体"，
        默认字体能不能显示中文取决于调用方有没有 app.setFont（main.py 里
        设了，但测试/探针环境未必）。不显式指定时，缺中文字形就会画出
        一排豆腐块——拖起来像一堆空方格。这里给带回退的族列表。
        """
        f = QFont()
        f.setFamilies(["PJM Sans SC", "Microsoft YaHei UI", "Microsoft YaHei",
                       "Noto Sans SC", "SimHei", "SimSun"])
        f.setPointSizeF(float(point_size))
        f.setBold(bold)
        return f

    # 两张拖影共用的"落点偏移"：界面内的自绘 ghost 出现在光标右下
    # (14,12)/(14,8) 处；系统拖影的热点在位图左上角，所以这里给位图
    # 补同尺寸透明边距，让可见卡片正好落在同一个位置。
    _GHOST_PAD_L = 14
    _GHOST_PAD_T_FILE = 12
    _GHOST_PAD_T_CAT = 8

    # 文件类型图标的配色（与 Theme.qml 的 C_TYPE_* 逐字一致）
    _TYPE_STYLES = {
        "DOCX": ("#EEF3FF", "#4E6BFF"),
        "XLSX": ("#EAF7F1", "#0E9F6E"),
        "PPTX": ("#FFF2E8", "#F97316"),
        "PDF": ("#FCE8E9", "#E5484D"),
        "IMG": ("#F0E9FD", "#8B5CF6"),
        "TXT": ("#EFF2F7", "#8892A6"),
    }

    @staticmethod
    def _type_of(kind: str) -> str:
        k = str(kind or "").lower().lstrip(".")
        if k in ("docx", "doc"):
            return "DOCX"
        if k in ("xlsx", "xls", "csv"):
            return "XLSX"
        if k in ("pptx", "ppt", "pps"):
            return "PPTX"
        if k == "pdf":
            return "PDF"
        if k in ("png", "jpg", "jpeg", "gif", "bmp", "webp", "svg", "ico"):
            return "IMG"
        return "TXT"

    @staticmethod
    def _draw_type_icon(p: QPainter, kind: str, x0: float, y0: float,
                        size: int = 22) -> None:
        """在 QPainter 上复刻 FileTypeIcon.qml 的 22px 类型图标。

        ⚠️ 几何与配色必须和 QML 组件逐项对齐：拖出窗口时系统画的是这张
        位图、窗口内画的是 QML 组件，越过边界时图标不能变样。
        规格：类型底 22×22 圆角 7 + 白色纸片（66% 宽高的 46%/58%）+
        左侧竖条 + 两条内容线；图片类型换成圆点 + 山形。
        """
        t = AppController._type_of(kind)
        bg, fg = AppController._TYPE_STYLES[t]
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(bg))
        p.drawRoundedRect(x0, y0, size, size, 7, 7)

        # 白纸
        pw = round(size * 0.46)
        ph = round(size * 0.58)
        px = x0 + (size - pw) / 2.0
        py = y0 + (size - ph) / 2.0
        p.setBrush(QColor("#FFFFFF"))
        edge = QColor(fg)
        edge.setAlphaF(0.22)
        pen = QPen(edge)
        pen.setWidthF(0.5)
        p.setPen(pen)
        p.drawRoundedRect(QRectF(px, py, pw, ph), 2, 2)
        p.setPen(Qt.PenStyle.NoPen)

        line_h = max(1.0, size * 0.06)
        if t == "IMG":
            r = max(2.0, size * 0.12) / 2.0
            p.setBrush(QColor(fg))
            p.drawEllipse(QPointF(px + pw * 0.22 + r, py + ph * 0.24 + r), r, r)
            mw = pw * 0.52
            mh = pw * 0.36
            c2 = QColor(fg)
            c2.setAlphaF(0.85)
            p.setBrush(c2)
            p.drawRect(QRectF(px + (pw - mw) / 2.0, py + ph - ph * 0.18 - mh,
                              mw, mh))
        else:
            bw = max(1.5, size * 0.09)
            p.setBrush(QColor(fg))
            p.drawRoundedRect(QRectF(px + pw * 0.20, py + ph * 0.18,
                                     bw, ph * 0.64), bw / 2, bw / 2)
            c1 = QColor(fg)
            c1.setAlphaF(0.75)
            p.setBrush(c1)
            p.drawRoundedRect(QRectF(px + pw * 0.48, py + ph * 0.30,
                                     pw * 0.34, line_h), 0.6, 0.6)
            c3 = QColor(fg)
            c3.setAlphaF(0.55)
            p.setBrush(c3)
            p.drawRoundedRect(QRectF(px + pw * 0.48, py + ph * 0.52,
                                     pw * 0.24, line_h), 0.6, 0.6)
        p.restore()

    @staticmethod
    def _drag_pixmap(n: int, names: list | None = None) -> QPixmap:
        """文件拖出窗口时的系统拖影。

        ⚠️ 必须和 Main.qml 里那张自绘 ghostCard **同款同位置**：
        拖出后图像由 Windows 的 OLE 拖放子系统绘制，一旦开始就无法中途
        撤掉。如果两张长得不一样，拖回来时用户会同时看到两个拖影。
        做成同款后，越过边界时视觉上就是同一个东西。
        （尺寸/圆角/文案/字号全部对齐 QML：44 高、圆角 12、白底 + 10%
         主色叠层、22px 图标、文案「移动这个文件 / 移动 N 个文件」）
        """
        text = "移动这个文件" if n <= 1 else f"移动 {n} 个文件"
        font = AppController._drag_font(9.375)          # = Theme.pt(12.5)
        fm = QFontMetrics(font)
        card_w = 22 + 8 + fm.horizontalAdvance(text) + 24
        card_h = 44
        pad_l, pad_t = AppController._GHOST_PAD_L, AppController._GHOST_PAD_T_FILE
        w, h = card_w + pad_l + 12, card_h + pad_t + 12

        img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        # 卡片：白底 + 边框 + 10% 主色叠层（与 QML 完全一致）
        p.setPen(QColor("#DCE3EF"))
        p.setBrush(QColor("#FFFFFF"))
        p.drawRoundedRect(pad_l, pad_t, card_w - 1, card_h - 1, 12, 12)
        tint = QColor(ACCENT)
        tint.setAlphaF(0.10)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(tint)
        p.drawRoundedRect(pad_l, pad_t, card_w - 1, card_h - 1, 12, 12)

        # 左侧类型图标：完全复刻 FileTypeIcon（按扩展名配色 + 形状）
        kind = Path(names[0]).suffix if names else ""
        ix, iy, isz = pad_l + 12, pad_t + (card_h - 22) // 2, 22
        AppController._draw_type_icon(p, kind, ix, iy, isz)

        # 文案
        p.setPen(QColor("#1F2937"))
        p.setFont(font)
        p.drawText(ix + isz + 8, pad_t, card_w - (isz + 8) - 12, card_h,
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   text)
        p.end()
        return QPixmap.fromImage(img)
    # ---------------- 双击（B7）----------------
    @Slot(str)
    def fileDoubleClicked(self, fid: str) -> None:
        """_on_file_double 平移：回收站行不打开；多选时先收敛到该行再打开。"""
        if fid.startswith("trash#"):
            self.status("回收站行双击不打开", "info")
            return
        self._selected_fids = [fid]
        self.setSelection(json.dumps(self._selected_fids))
        self.openEditSession()          # G1：最新版编辑会话（setSelection 已同步 _current_meta）

    # ---------------- A1/A2/A3（M1 已有，保留）----------------
    @Slot(int, result=str)
    def uiRestore(self, total: int) -> str:
        ui = self._store.config.get("ui", {}) or {}
        sash = ui.get("sash")
        pane_w = ui.get("pane_w")
        l = r = None
        if isinstance(sash, (list, tuple)) and len(sash) in (1, 2):
            try:
                s0 = int(sash[0])
                l = (int(round(s0 / float(pane_w) * total))
                     if isinstance(pane_w, (int, float)) and pane_w > 0 else s0)
            except (TypeError, ValueError):
                l = None
            if len(sash) == 2:
                try:
                    s1 = int(sash[1])
                    r = (int(round(s1 / float(pane_w) * total))
                         if isinstance(pane_w, (int, float)) and pane_w > 0 else s1)
                except (TypeError, ValueError):
                    r = None
        if l is None:
            l = LEFT_DEFAULT_W
        if not self._right_collapsed and r is None:
            r = total - RIGHT_DEFAULT_W
        if not ui.get("right_narrow_r8") and r is not None:
            r = max(r, total - RIGHT_DEFAULT_W)
        # M83：默认版本栏改窄是一次性迁移——老库存过 sash，只改 default
        # 对老用户不生效。缺这个标记时强行按最窄算，之后用户自己拖宽会
        # 正常持久化（标记在 appClosing 里补写）。
        if not ui.get("right_min_v2") and not self._right_collapsed:
            r = total - RIGHT_DEFAULT_W
        if not self._right_collapsed and r is not None:
            b1 = json.loads(self._sash_bounds_impl(1, total, l))
            if b1["hi"] >= b1["lo"]:
                r = max(b1["lo"], min(r, b1["hi"]))
        b0 = json.loads(self._sash_bounds_impl(0, total, l))
        if b0["hi"] >= b0["lo"]:
            l = max(b0["lo"], min(l, b0["hi"]))
        return json.dumps({"l": int(l), "r": (int(r) if r is not None else None),
                           "collapsed": self._right_collapsed})

    def _sash_bounds_impl(self, idx: int, total: int, cur_l: int) -> str:
        """_sash_bounds 平移（单一来源；设计 px=QML 逻辑像素）。"""
        if total <= 1:
            return json.dumps({"lo": 0, "hi": 0})
        if self._right_collapsed:
            if idx != 0:
                return json.dumps({"lo": 0, "hi": 0})
            min_l, min_m = SASH_MIN_L, SASH_MIN_M
            if total < min_l + min_m:
                ratio = total / float(min_l + min_m)
                min_l, min_m = int(min_l * ratio), int(min_m * ratio)
            return json.dumps({"lo": min_l, "hi": total - min_m})
        min_l, min_m, min_r = SASH_MIN_L, SASH_MIN_M, SASH_MIN_R
        if total < min_l + min_m + min_r:
            ratio = total / float(min_l + min_m + min_r)
            min_l, min_m, min_r = (int(min_l * ratio), int(min_m * ratio),
                                   int(min_r * ratio))
        if idx == 0:
            return json.dumps({"lo": min_l, "hi": total - min_m - min_r})
        if idx == 1:
            l2 = max(min_l, min(cur_l, total - min_m - min_r))
            return json.dumps({"lo": l2 + min_m, "hi": total - min_r})
        return json.dumps({"lo": 0, "hi": 0})

    @Slot(int, int, int, result=str)
    def sash_bounds(self, idx: int, total: int, cur_l: int) -> str:
        return self._sash_bounds_impl(idx, total, cur_l)

    @Slot(int, int, int, int, result=str)
    def clampSash(self, idx: int, pos: int, total: int, cur_l: int = 0) -> str:
        lo_hi = json.loads(self._sash_bounds_impl(idx, total, cur_l))
        lo, hi = lo_hi["lo"], lo_hi["hi"]
        if hi >= lo:
            pos = max(lo, min(pos, hi))
        return json.dumps({"pos": int(pos)})

    @Slot(bool, int, int, int)
    def toggleCollapseRight(self, collapsed: bool, l: int, r: int, total: int) -> None:
        self._right_collapsed = bool(collapsed)
        self.rightCollapsedChanged.emit(self._right_collapsed)
        self.saveUiState(l, r, total)
        self._store.config["ui"]["right_collapsed"] = self._right_collapsed
        self._write_ui_config()
        self.status("右栏已收纳" if self._right_collapsed else "右栏已展开", "info")

    @Slot(int, int, int)
    def saveUiState(self, l: int, r: int, total: int) -> None:
        ui = self._store.config.get("ui", {}) or {}
        if self._right_collapsed:
            ui["sash"] = [int(l)]
        else:
            ui["sash"] = [int(l), int(r)] if r is not None else [int(l)]
        ui["pane_w"] = int(total)
        self._store.config["ui"] = ui

    @Slot(int, int, int)
    def savePaneWidths(self, l: int, r: int, total: int) -> None:
        """M97：分区拖动结束后立刻落库。

        旧实现只在 appClosing 写，会话中途崩溃/强杀就丢了；而且拖动带来的
        宽度变化本来就是「用户此刻的意图」，没有理由拖到退出才存。
        """
        self.saveUiState(l, r, total)
        self._write_ui_config()

    @Slot(str, bool, int, int, int)
    def appClosing(self, geometry: str, zoomed: bool, l: int, r: int, total: int) -> None:
        self.saveUiState(l, r, total)
        ui = self._store.config.get("ui", {}) or {}
        ui["px_aware"] = True
        ui["right_collapsed"] = bool(self._right_collapsed)
        ui["right_narrow_r7"] = True
        ui["right_narrow_r8"] = True
        ui["right_min_v2"] = True
        if zoomed:
            ui["zoomed"] = True
            ui.pop("geometry", None)
        else:
            ui["zoomed"] = False
            ui["geometry"] = geometry
        ui["col_open"] = dict(self._col_open)      # D2：展开态持久化
        self._store.config["ui"] = ui
        self._write_ui_config()
        self._share.clear_share_dir()

    def _write_ui_config(self) -> None:
        try:
            self._store._save_json(self._store.config_file, self._store.config)
        except OSError as e:
            self.warnSaveFailed(str(e))


    # ================= 左栏分类树（D1–D6，M3）=================
    # 生产对拍锚点：refresh() L6865 / _insert_collections L6903 / _collect_open_state
    # L6890 / on_collection_click L8180 / on_collection_double L8141 /
    # _resolve_drop_target L8256 / _perform_collection_drop L8335 /
    # on_collection_menu L8083 / on_rename_collection L8395 / _commit_rename_inline L8500

    catsChanged = Signal()

    def _rebuild_categories(self) -> None:
        """refresh() 树段平移：内置头两个 + 用户分类 DFS（按展开态）+ 回收站末尾红字。

        展开态：_col_open 有记录用记录；无记录新节点默认折叠（_insert_collections
        注释口径——新分类的"立刻可见"反馈由新建入口显式展开父节点）。
        """
        self._col_branch_ids = {p for p in self._store._col_parent.values()
                                if p is not None}
        # M29（纯展示，不改业务）：侧栏计数胶囊的数据源。
        # 直接数索引里的受管文件（file_list 读内存 config，无磁盘 IO），
        # 父分类按子树求和（设计图里父项计数 = 自身 + 后代）。
        _files = self._store.file_list()
        _direct: dict[str, int] = {}
        _unfiled = 0
        for _e in _files:
            _c = _e.get("category")
            if _c:
                _direct[_c] = _direct.get(_c, 0) + 1
            else:
                _unfiled += 1
        # M83：_kids/_subtree 已随「徽标改直属数」一并移除（原用于子树求和）。

        _total = len(_files)
        _trash_n = len(self._store.trash_items())
        rows: list[dict] = [
            {"cid": CID_ALL, "name": "全部文件", "depth": 0, "open": False,
             "hasChildren": False, "isBuiltin": True, "isTrash": False,
             "count": _total},
            {"cid": CID_UNFILED, "name": "未分类", "depth": 0, "open": False,
             "hasChildren": False, "isBuiltin": True, "isTrash": False,
             "count": _unfiled},
        ]

        def walk(parent, depth: int) -> None:
            for ch in self._store.collection_children(parent):
                cid = ch.get("id")
                if not cid:
                    continue
                has_ch = cid in self._col_branch_ids
                rows.append({
                    "cid": cid, "name": ch.get("name", ""), "depth": depth,
                    "open": bool(self._col_open.get(cid, False)),
                    "hasChildren": has_ch, "isBuiltin": False, "isTrash": False,
                    # M83：徽标改为「直属文件数」，与点进来看到的列表一致。
                    # 原来显示子树总数（_subtree），改完过滤后会出现
                    # "徽标 12、列表 3" 的矛盾。_direct 上面已经算好了。
                    "count": _direct.get(cid, 0),
                })
                if has_ch and self._col_open.get(cid, False):
                    walk(cid, depth + 1)

        walk(None, 0)
        rows.append({"cid": CID_TRASH, "name": "回收站", "depth": 0, "open": False,
                     "hasChildren": False, "isBuiltin": True, "isTrash": True,
                     "count": _trash_n})
        # M17：增量同步（reset 会销毁 delegate → 双击手势落空，见
        # CategoriesModel.sync_rows 文档）
        self._cat_model.sync_rows(rows)
        if self._selected_collection not in [r["cid"] for r in rows]:
            self._selected_collection = CID_ALL
            self.reload_files()
        self.catsChanged.emit()

    @Slot(str)
    def treePress(self, cid: str) -> str:
        """on_collection_click 平移（单击部分）：选中 + 分支切换/展开一级 +
        回滚记录 + 拖拽候选武装。编辑中点树任意处 = 提交（生产口径）。

        M17：开合仍保留（旧版单击即展开，硬指标不退化）；配套把
        CategoriesModel 从 beginResetModel 换成增量 sync_rows，开合时
        既有行 delegate（含其内 MouseArea）存活，双击手势不再落空。"""
        if self._col_edit_cid is not None:
            self.commitRename()
            return json.dumps({"intents": [{"op": "commit_edit"}]})
        intents = []
        row = self._cat_row(cid)
        if row is None:
            return json.dumps({"intents": []})
        self._col_drag_row = None
        self._col_drag_hit = False
        self._col_click_restore = None
        self._col_pending_toggle = None
        # 选中（browse 单选）
        self._selected_collection = cid
        # M54：真实点击走 treePress（不经过 selectCollection）——回收站清理
        # 必须在这里也执行，否则版本栏残留上一个文件、右栏也不收。
        if cid == CID_TRASH:
            self._enter_trash_state()
        self.reload_files()
        intents.append({"op": "select", "cid": cid})
        # M76：单击行**不再展开/收起**（用户反馈：单击展开会和选中、拖拽、
        # 双击改名撞车，手感很别扭）。开合只由行左侧的三角按钮触发
        # （QML → treeToggle）。这里刻意不再设 _col_pending_toggle，
        # _tree_drag_release 的 pending 分支自然就不执行了。
        if not row["isBuiltin"]:
            self._col_drag_row = cid                 # 拖拽候选武装
        return json.dumps({"intents": intents,
                           "selected": self._selected_collection})

    def _cat_row(self, cid: str) -> dict | None:
        for r in self._cat_model.rows:
            if r["cid"] == cid:
                return r
        return None

    @Slot(str, result=str)
    def treeEvent(self, ev_json: str) -> str:
        """QML 树原始事件入口：press 之外的 move/release/doubleClick。"""
        ev = json.loads(ev_json)
        op = ev.get("op")
        if op == "move":
            return self._tree_drag_move(ev)
        if op == "release":
            return self._tree_drag_release(ev)
        if op == "doubleClick":
            return self._tree_double_click(ev)
        return json.dumps({"intents": []})

    def _tree_drag_move(self, ev: dict) -> str:
        """on_collection_drag_motion 平移：阈值 → 回滚首按 toggle → 落点反馈。"""
        if self._col_edit_cid is not None:
            return json.dumps({"intents": []})
        cid = self._col_drag_row
        if not cid:
            return json.dumps({"intents": []})
        sx, sy = self._col_drag_start
        x, y = ev.get("x", 0), ev.get("y", 0)
        if not self._col_drag_hit:
            if abs(x - sx) < 4 and abs(y - sy) < 4:
                return json.dumps({"intents": []})
            self._col_drag_hit = True
            self._col_pending_toggle = None           # 拖拽不该顺势展开/折叠
            if self._col_click_restore:
                r, before = self._col_click_restore
                self._col_open[r] = before
                self._rebuild_categories()
                self._col_click_restore = None
        mode, ref = self._resolve_drop_target(cid, ev)
        self._drop_indicator = {"mode": mode, "ref": ref}
        return json.dumps({"intents": [{"op": "indicator", "mode": mode,
                                        "ref": ref}]})

    def _tree_drag_release(self, ev: dict) -> str:
        """on_collection_click_release 平移：拖拽态落地；非拖拽仅复位。

        注意（生产注释）：非拖拽分支**不能**清 _col_click_restore——
        双击序列 Button1→Release→Double1 还要靠它回滚 press1 的开合副作用。
        """
        if self._col_edit_cid is not None:
            return json.dumps({"intents": []})
        if self._col_drag_hit:
            self._col_pending_toggle = None          # 拖动过：不开合
            intents = self._perform_collection_drop()
            self._col_drag_row = None
            self._col_drag_hit = False
            self._drop_indicator = {}
            return json.dumps({"intents": intents})
        pending = self._col_pending_toggle
        self._col_pending_toggle = None
        self._col_drag_row = None
        self._col_drag_hit = False
        if pending:
            cid2, already2, before2 = pending
            new_open = (not before2) if already2 else True
            if new_open != before2:
                self._col_open[cid2] = new_open
                self._rebuild_categories()
                return json.dumps({"intents": [{"op": "toggle",
                                                "cid": cid2,
                                                "open": new_open}]})
        return json.dumps({"intents": []})

    def _tree_double_click(self, ev: dict) -> str:
        """on_collection_double 平移：进入重命名（**不动开合态**）。

        M17：恢复回滚块——treePress 仍会在首按时展开（旧版口径），双击时
        必须把这次 toggle 撤销（_col_click_restore），使双击不改开合态。
        增量 sync_rows 保证回滚期间父行 delegate 存活，改名框能正常挂上。"""
        if self._col_edit_cid is not None:
            return json.dumps({"intents": []})
        cid = ev.get("cid", "")
        row = self._cat_row(cid)
        if row is None or row["isBuiltin"]:
            return json.dumps({"intents": []})
        self._col_pending_toggle = None           # 双击不进开合
        if self._col_click_restore:
            r, before = self._col_click_restore      # 回滚双击首按 toggle
            self._col_open[r] = before
            self._rebuild_categories()
            self._col_click_restore = None
        return self.beginRename(cid)

    # ---- D4：落点解析（_resolve_drop_target 平移；off 比例由 QML 传）----
    @staticmethod
    def resolve_drop_target(cid: str, off: float, is_builtin: bool) -> tuple[str, str | None]:
        """返回 (mode, ref)。mode ∈ {into, before, after, end}。

        生产口径（L8256）：行间空白/内置节点 → ("end", None)（移到顶层末尾，
        回收站恒最后且不是分类）；off<0.30 → before；>0.70 → after；否则 into。
        """
        if not cid or is_builtin:
            return ("end", None)
        if off < 0.30:
            return ("before", cid)
        if off > 0.70:
            return ("after", cid)
        return ("into", cid)

    def _resolve_drop_target(self, src: str, ev: dict) -> tuple[str, str | None]:
        cid = ev.get("cid", "")
        off = float(ev.get("off", 0.5))
        row = self._cat_row(cid)
        is_builtin = (row["isBuiltin"] if row else True) or not cid
        return self.resolve_drop_target(cid, off, is_builtin)

    def _perform_collection_drop(self) -> list[dict]:
        """_perform_collection_drop 平移：into/before/after/end → Store API。"""
        src = self._col_drag_row
        if not src:
            return []
        mode = self._drop_indicator.get("mode", "end")
        ref = self._drop_indicator.get("ref")
        try:
            if mode in ("before", "after"):
                # M60：子分类允许借「插到两个上级分类之间」改层级；
                # 顶层分类只能在顶层之间换序（不能借排序掉进别人下面）。
                p_src = self._store.collection_parent(src)
                p_ref = self._store.collection_parent(ref)
                if p_src is None and p_ref is not None:
                    self.status("顶层分类不能这样改层级；"
                                "要放进某个分类里，请拖到那个分类的中间。", "err")
                    return []
            if mode == "into":
                if ref == src:
                    return []
                self._store.move_collection(src, ref)
            elif mode == "before":
                parent = self._store.collection_parent(ref)
                self._store.reorder_collection(src, parent, before_cid=ref)
            elif mode == "after":
                parent = self._store.collection_parent(ref)
                sibs = [c.get("id") for c in self._store.collection_children(parent)]
                try:
                    i = sibs.index(ref)
                except ValueError:
                    i = -1
                after_ref = sibs[i + 1] if 0 <= i < len(sibs) - 1 else None
                self._store.reorder_collection(src, parent, before_cid=after_ref)
            else:                                    # end：移到顶层末尾
                self._store.reorder_collection(src, None, before_cid=None)
        except ValueError as e:
            self.status("无法移动：" + str(e), "err")   # 防循环等拒绝（C14 红字）
            return [{"op": "drop_failed", "reason": str(e)}]
        # into 成功后展开目标（数据已正确，补可见性——生产同口径）
        if mode == "into" and ref:
            self._col_open[ref] = True
        self._rebuild_categories()
        self.reload_files()
        return [{"op": "dropped", "mode": mode, "ref": ref}]

    # ---- D3：内联重命名（_begin_rename_inline/_commit/_cancel 平移）----
    @Slot(str, result=str)
    def beginRename(self, cid: str) -> str:
        """on_rename_collection 平移：内置节点拒绝；重名收口由 commit 处理。"""
        if not cid or cid in BUILTIN_CIDS:
            return json.dumps({"ok": False, "reason": "builtin"})
        if self._col_edit_cid is not None:       # 已在编辑 → 先落定上一次
            self.commitRename()
        self._col_edit_cid = cid
        self._col_edit_at = time.monotonic()
        old = self._store.collection_name(cid) or ""
        return json.dumps({"ok": True, "cid": cid, "old": old})

    @Slot(str, result=str)
    def commitRename(self, new_name: str = "") -> str:
        """_commit_rename_inline 平移：空名=放弃；重名/非法=保持编辑态；
        成功=关编辑态→refresh→恢复选中。"""
        cid = self._col_edit_cid
        if cid is None:
            return json.dumps({"ok": False})
        name = (new_name or "").strip()
        if not name:
            self._cancelRename()
            return json.dumps({"ok": True, "cancelled": True})
        try:
            self._store.rename_collection(cid, name)
        except ValueError as e:
            # 重名/非法：提示并**保持编辑态**（不销毁输入框——生产口径）
            self.status(str(e), "err")
            return json.dumps({"ok": False, "keepEditing": True, "reason": str(e)})
        self._col_edit_cid = None
        self._selected_collection = cid
        self._rebuild_categories()
        self.reload_files()
        return json.dumps({"ok": True, "cid": cid})

    @Slot(result=str)
    def cancelRename(self) -> str:
        self._cancelRename()
        return json.dumps({"ok": True})

    def _cancelRename(self) -> None:
        self._col_edit_cid = None

    # ---- D3/K3：F2 分派器雏形（左栏分支）----

    @Slot(result=str)
    def selectedCollectionCid(self) -> str:
        return self._selected_collection

    @Slot(str, result=str)
    def collectionName(self, cid: str) -> str:
        return self._store.collection_name(cid) or ""

    @Slot(str, result=str)
    def treeToggle(self, cid: str) -> str:
        """glyph 箭头点击 = 纯开合切换（不选中、不进拖拽——生产
        on_collection_click 的 identify_element == indicator 分支）。"""
        row = self._cat_row(cid)
        if row is None or not row["hasChildren"]:
            return json.dumps({"intents": []})
        self._col_open[cid] = not row["open"]
        self._rebuild_categories()
        return json.dumps({"intents": [{"op": "toggled"}]})

    @Slot(result=bool)
    def isInternalDrag(self) -> bool:
        """M77：当前是否有「本应用发起」的拖拽在飞行中。

        QML 的窗口级 DropArea 用它当闸门：内部拖拽不能走「外部文件拖入」那条
        链路（否则拖回窗口会被当成新文件 → 提交新版本）。
        """
        return self._drag_payload is not None

    @Slot(result=str)
    def internalDragKind(self) -> str:
        """内部拖拽的类型：'files' / 'collection' / ''（无拖拽）。"""
        p = self._drag_payload
        return str(p.get("kind") or "") if p else ""

    @Slot(result=int)
    def internalDragCount(self) -> int:
        """内部拖拽携带的文件个数（0 表示不是文件拖拽）。"""
        p = self._drag_payload
        if not p or p.get("kind") != "files":
            return 0
        return len([f for f in (p.get("fids") or []) if f])

    @Slot(result=str)
    def internalDragLabel(self) -> str:
        """内部拖拽的显示名（拖影卡片上写的字）。"""
        p = self._drag_payload
        if not p:
            return ""
        if p.get("kind") == "collection":
            return self._store.collection_name(p.get("cid") or "") or "分类"
        fids = p.get("fids") or []
        if len(fids) == 1:
            meta = self._store.load_meta(fids[0])
            return (meta or {}).get("name") or "1 个文件"
        return f"{len(fids)} 个文件"

    @Slot(str)
    def internalDropOnTree(self, target_cid: str) -> None:
        """M77：拖出窗口后又拖回、松手落在分类树上 → 按原来的界面行为处理。

        目前只处理文件（= 改分类）。分类拖回不处理：分类拖出就是「导出」，
        拖回来等于取消，什么都不做才是对的。
        """
        p = self._drag_payload
        if not p or p.get("kind") != "files" or not target_cid:
            return
        fids = [f for f in (p.get("fids") or []) if f]
        if not fids:
            return
        try:
            r = json.loads(self.fileTransfer(json.dumps(fids), target_cid))
        except Exception as e:  # noqa: BLE001
            self.status(f"移动失败：{e}", "err")
            return
        if r.get("conflicts"):
            cf = r["conflicts"][0]
            src = self._store.load_meta(cf["srcFid"])
            dst = self._store.load_meta(cf["dstFid"])
            if src and dst:
                self.open_transfer_conflict(src, target_cid, dst)

    @Slot(str)
    def expandCollection(self, cid: str) -> None:
        """M76：把分类展开（幂等——已展开/无子级/内置行都直接返回）。

        用途：拖文件悬停在某个分类上时自动展开，这样才能继续往下拖进子分类。
        与 treeToggle 的差别是语义单向：只开不合，不会因为重复触发把用户
        刚展开的又收回去。
        """
        row = self._cat_row(cid)
        if row is None or row["isBuiltin"] or not row["hasChildren"]:
            return
        if row["open"]:
            return
        self._col_open[cid] = True
        self._rebuild_categories()

    @Slot(str, result=str)
    def collectionMenuSpec(self, cid: str) -> str:
        """on_collection_menu 三分支平移（D6；文案逐字对齐生产）。"""
        row = self._cat_row(cid)
        acts: list[dict] = []
        if row is not None and row["isTrash"]:
            # 回收站：只给还原/打开目录/清空，绝不出现"删除分类"
            sel_items = [f for f in self._selected_fids
                         if f.startswith("trash#")]
            n, size = self._store.trash_summary()
            acts.append({"label": (f"还原选中项（{len(sel_items)} 项）" if sel_items
                                   else "还原选中项"), "key": "restore_trash",
                         "state": "normal" if sel_items else "disabled",
                         "danger": False, "accel": "",
                         "arg": json.dumps(sel_items)})
            acts.append({"sep": True})
            acts.append({"label": "在资源管理器中打开回收站目录",
                         "key": "open_trash_dir", "state": "normal",
                         "danger": False, "accel": "", "arg": ""})
            acts.append({"label": f"清空回收站（{n} 项，{self._fmt_size(size)}）",
                         "key": "empty_trash", "state": "normal",
                         "danger": True, "accel": "", "arg": ""})
        elif row is None or row["isBuiltin"]:
            # 空白处/内置节点：上下文感知菜单（绝不只剩"新建一级分类"）
            acts.append({"label": "新建一级分类…", "key": "new", "arg": "",
                         "state": "normal", "danger": False, "accel": ""})
            label, target = self._subcollection_label()
            acts.append({"label": label, "key": "new", "arg": target or "",
                         "state": "normal" if target else "disabled",
                         "danger": False, "accel": ""})
        else:
            acts.append({"label": "新建子分类…", "key": "new", "arg": cid,
                         "state": "normal", "danger": False, "accel": ""})
            acts.append({"label": "新建一级分类…", "key": "new", "arg": "",
                         "state": "normal", "danger": False, "accel": ""})
            acts.append({"sep": True})
            acts.append({"label": "重命名", "key": "rename", "arg": cid,
                         "state": "normal", "danger": False, "accel": "F2"})
            acts.append({"label": "移动到…", "key": "move", "arg": cid,
                         "state": "normal", "danger": False, "accel": ""})
            acts.append({"label": "导出为文件夹…", "key": "export_folder",
                         "arg": cid, "state": "normal", "danger": False,
                         "accel": ""})
            acts.append({"sep": True})
            acts.append({"label": "删除…", "key": "delete", "arg": cid,
                         "state": "normal", "danger": True, "accel": "Del"})
        return json.dumps({"actions": acts})

    def _subcollection_label(self) -> tuple[str, str | None]:
        """_subcollection_label 平移（上下文感知的新建子分类文案）。"""
        sel = self._selected_collection
        if sel and sel not in BUILTIN_CIDS:
            pname = self._store.collection_name(sel)
            if pname and pname != "?":
                return f"新建子分类（存到「{pname}」下）", sel
            return "新建子分类（存到当前选中分类下）", sel
        return "新建子分类（请先在左侧选中一个分类）", None

    @staticmethod
    def _fmt_size(n: float) -> str:
        """生产 _fmt_size 口径（trash_summary 显示用）。"""
        n = float(n or 0)
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024 or unit == "GB":
                return (f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}")
            n /= 1024
        return f"{n:.1f} GB"

    # ---- M40：回收站行内「清除」（单条永久删除，二次确认）----
    @Slot(str, str)
    def purgeTrashItem(self, fid: str, name: str) -> None:
        raw = fid.split("#", 1)[1] if str(fid).startswith("trash#") else fid
        self.confirm(
            "彻底删除",
            (f"彻底删除「{name}」？\n\n"
             "·该条目及其全部版本将从磁盘永久删除\n"
             "·此操作不可恢复（不是移入回收站）"),
            ok_text="彻底删除", danger=True,
            on_result=lambda yes: self._purge_trash_done(raw, yes))

    def _purge_trash_done(self, raw_id: str, yes: bool) -> None:
        if not yes:
            return
        ok, msg = self._store.purge_trash_item(raw_id)
        self.reload_files()
        self.status("已彻底删除 1 项" if ok
                    else f"删除失败：{msg or '未知原因'}",
                    "ok" if ok else "err")

    # ================= 分类导出为文件夹（M75）=================
    @Slot(str)
    def exportCollectionAsFolder(self, cid: str) -> None:
        """右键「导出为文件夹…」：选目录 → 按分类树建文件夹 → 只导出最新版本。

        重名口径（产品定稿）：目标已有同名**文件夹**就改用「名称(2)」，
        不合并；文件夹内部不再查重——因为单分类内本来不允许文件重名，
        每次导出又都落在全新目录里，天然不会撞。
        """
        if not cid or cid in BUILTIN_CIDS:
            return
        name = self._store.collection_name(cid) or "未命名分类"
        self.ask_directory(
            f"导出分类「{name}」到…",
            lambda dest: self._do_export_collection(cid, dest))

    def _do_export_collection(self, cid: str, dest: str | None) -> None:
        if not dest:
            return
        base = Path(dest)
        if not base.is_dir():
            self.status("导出位置无效", "err")
            return
        self._set_busy(True, "正在导出分类…")
        try:
            top = self._export_collection_tree(cid, base)
        except Exception as e:                       # noqa: BLE001
            self.status(f"导出失败：{e}", "err")
            return
        finally:
            self._set_busy(False)
        if top:
            self.status(f"已导出到 {top}", "ok")

    @staticmethod
    def _safe_name(s: str) -> str:
        """Windows 文件名净化：非法字符换下划线，去掉末尾的点与空格。"""
        bad = '\\/:*?"<>|'
        out = "".join("_" if ch in bad else ch for ch in (s or "").strip())
        out = out.rstrip(". ")
        return out or "未命名"

    @staticmethod
    def _unique_dir(parent: Path, name: str) -> Path:
        """目标已有同名文件夹时改用「名称(2)」「名称(3)」…，绝不合并。"""
        d = parent / name
        n = 2
        while d.exists():
            d = parent / f"{name}({n})"
            n += 1
        return d

    def _export_collection_tree(self, cid: str, parent: Path) -> Path | None:
        """递归导出：建本分类文件夹 → 导出本分类各文件最新版本 → 递归子分类。"""
        name = self._store.collection_name(cid) or "未命名分类"
        target = self._unique_dir(parent, self._safe_name(name))
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self.status(f"无法创建文件夹 {target}：{e}", "err")
            return None

        # M75-3：原实现把 `config["files"]` 当 dict 用（`.values()`），但库里
        # 它是**索引 list**（元素含 fid / name / category / latest_time…），
        # 必然抛 AttributeError；异常被上层吞掉 → 表现为「拖出毫无反应」。
        # 现在按索引筛「直接归属本分类」的文件（父文件夹不放子分类的文件，
        # 否则镜像出来的树会和分类树不一致），实体与最新版本交给 Store 接口。
        for entry in self._store.config.get("files", []):
            if not isinstance(entry, dict) or entry.get("category") != cid:
                continue
            meta = self._store.load_meta(entry.get("fid") or "")
            if not meta:
                continue
            ver = self._store.latest_version(meta)
            if ver is None:
                continue
            try:
                src = self._store.version_file(meta, ver)
            except (OSError, FileNotFoundError):
                continue
            fname = self._safe_name(meta.get("name") or "未命名")
            dst = target / fname
            if dst.exists():                     # 兜底，正常不会走到
                stem, ext = os.path.splitext(fname)
                n = 2
                while dst.exists():
                    dst = target / f"{stem}({n}){ext}"
                    n += 1
            try:
                _copy2_writable(src, dst)
            except OSError:
                continue

        for child in self._store.collection_children(cid):
            child_id = child.get("id")
            if child_id:
                self._export_collection_tree(child_id, target)
        return target

    # ===== M75-2：拖分类出窗口 → 直接落到用户放下的位置 =====
    @staticmethod
    def _collection_drag_pixmap(name: str, n_files: int, n_subs: int) -> QPixmap:
        """分类拖出窗口时的系统拖影。

        ⚠️ 与 QML 的 catGhost **同款同位置**（148 上限宽 × 26 高、圆角 7、
        主色 94%、只写分类名、字号 12px）。原因同文件拖影：拖出后的图像由
        Windows OLE 绘制且无法中途撤掉，两张必须长得一样才不会"叠两个"。

        n_files / n_subs 保留在签名里（调用方已在传），但不画到卡片上——
        拖拽时要尽量安静，只留分类名。
        """
        font = AppController._drag_font(9.0)          # = 12px
        fm = QFontMetrics(font)
        card_w = min(148, max(78, fm.horizontalAdvance(name) + 20))
        card_h = 26
        pad_l, pad_t = AppController._GHOST_PAD_L, AppController._GHOST_PAD_T_CAT
        w, h = card_w + pad_l + 10, card_h + pad_t + 10

        img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        bg = QColor(ACCENT)
        bg.setAlphaF(0.94)
        p.setBrush(bg)
        p.drawRoundedRect(pad_l, pad_t, card_w - 1, card_h - 1, 7, 7)

        p.setPen(QColor("#FFFFFF"))
        p.setFont(font)
        p.drawText(pad_l + 10, pad_t, card_w - 20, card_h,
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   fm.elidedText(name, Qt.TextElideMode.ElideRight, card_w - 20))
        p.end()
        return QPixmap.fromImage(img)

    @staticmethod
    def _drag_dbg(msg: str) -> None:
        """拖拽诊断日志（定位"拖出没反应"用，稳定后应移除）。"""
        try:
            base = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "井然"
            base.mkdir(parents=True, exist_ok=True)
            with open(base / "drag_debug.log", "a", encoding="utf-8") as f:
                f.write("%s %s\n" % (time.strftime("%H:%M:%S"), msg))
        except OSError:
            pass

    @Slot(str)
    def startCollectionDragOut(self, cid: str) -> None:
        """把分类导出到临时目录，再交给系统拖放。

        与右键「导出为文件夹…」的区别（用户明确要求）：
          · 右键 = 先选目录再导出，适合精确指定位置；
          · 拖出 = 落到哪就复制到哪，不再弹「选目录」对话框。

        ⚠️ 这里**不能**同步 exec：本槽由 QML 的 onPositionChanged 直接调用，
        此时处于输入事件的分发栈里，QDrag 需要自己的模态循环，重入会直接
        失败（1.1.14 的"拖出毫无反应"就是这么来的）。所以先把活排到下一个
        事件循环 tick，等当前输入处理返回后再启动拖放。
        """
        if not cid or cid in BUILTIN_CIDS:
            return
        self._drag_dbg("request cid=%s" % cid)
        QTimer.singleShot(0, lambda: self._collection_drag_out_now(cid))

    def _collection_drag_out_now(self, cid: str) -> None:
        """真正启动系统拖放（在独立 tick 里执行）。"""
        name = self._store.collection_name(cid) or "未命名分类"
        # M77-6：导出要花时间，先让 QML 把自绘卡片收走（这段时间够重绘）
        self.internalDragStarted.emit()

        # 一次拖拽一个会话目录（同文件拖出，避开 20s 窗口内的重名竞态）
        try:
            session = self._share.new_share_dir()
        except OSError as e:
            self._drag_dbg("new_share_dir failed: %s" % e)
            self.status("拖出失败：无法创建临时目录", "err")
            return
        self._drag_dbg("export start -> %s" % session)
        try:
            top = self._export_collection_tree(cid, session)
        except Exception as e:  # noqa: BLE001
            self._drag_dbg("export raised: %r" % e)
            self.status(f"「{name}」导出失败：{e}", "err")
            return

        if top is None or not top.is_dir():
            self._drag_dbg("export returned None")
            self.status(f"「{name}」导出失败", "err")
            return

        # 统计，仅用于拖影文案
        n_files = 0
        for root, _dirs, fnames in os.walk(top):
            n_files += len(fnames)
        n_subs = max(0, len(self._store.collection_children(cid)))
        self._drag_dbg("export done files=%d subs=%d" % (n_files, n_subs))

        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(top))])
        mime.setText(name)
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(self._collection_drag_pixmap(name, n_files, n_subs))
        self._drag_dbg("exec begin")
        self._drag_payload = {"kind": "collection", "cid": cid}
        try:
            act = drag.exec(Qt.DropAction.CopyAction)
        finally:
            self._drag_payload = None
        try:
            self._drag_dbg("exec end action=%d" % int(act.value))
        except Exception:  # noqa: BLE001
            self._drag_dbg("exec end")
        # 模态返回 → 20s 后清理临时副本（与文件拖出同一口径）
        self._share.on_drag_end()
        self.collectionDragOutFinished.emit()
        self.status(f"已拖出分类「{name}」", "ok")

    @Slot(str, str, str)
    def collectionMenuAction(self, key: str, arg: str, trash_sel_json: str) -> None:
        """菜单动作分派：新建/重命名（D3）本批通；移动到…/删除级联确认与
        回收站动作按范围接线（空/还原本批通，删除确认 F8 在 M6）。"""
        if key == "new":
            # M33：走生产口径命名弹窗（on_new_collection → _ask_text），
            # 取代 M3 遗留的「自动命名无反馈」偏差（m3_report §6 记账项）。
            self.open_new_collection_dialog(arg or None)
        elif key == "rename":
            self.beginRename(arg)
            self.catsChanged.emit()
        elif key == "export_folder":
            self.exportCollectionAsFolder(arg)
        elif key == "restore_trash":
            # P1：QML 目前传的是 specData.fids（collectionMenuSpec 无此键
            # → 恒为 []），选中项真正在 arg 里（collectionMenuSpec 塞的
            # 是同一份 sel_items JSON）。两处都读不到就别报「已还原 0 项」。
            items: list = []
            for raw_json in (trash_sel_json, arg):
                try:
                    got = json.loads(raw_json) if raw_json else []
                except (ValueError, TypeError):
                    got = []
                if isinstance(got, list) and got:
                    items = [str(x) for x in got if x]
                    break
            if not items:
                self.status("请先在列表里选中要还原的项", "info")
                return
            ok_n = 0
            last_msg = ""
            for iid in items:
                # iid 带 "trash#" 前缀（_fill_trash_rows 口径），store 侧要裸 id
                raw = iid.split("#", 1)[1] if str(iid).startswith("trash#") \
                    else iid
                ok, msg = self._store.restore_trash_item(raw)
                if ok:
                    ok_n += 1
                else:
                    last_msg = msg
            self.reload_files()
            if ok_n == len(items):
                self.status(f"已还原 {ok_n} 项", "ok")
            else:
                self.status(f"还原 {ok_n}/{len(items)} 项：{last_msg or '部分失败'}",
                            "err" if ok_n == 0 else "info")
        elif key == "open_trash_dir":
            d = self._store.trash_dir if hasattr(self._store, "trash_dir") else None
            if d and Path(d).is_dir():
                os.startfile(str(d))  # noqa: S606
        elif key == "empty_trash":
            # 生产 on_empty_trash 口径：空提示；确认弹窗/清空复用 open_empty_trash
            n, size = self._store.trash_summary()
            if not n:
                self.status("回收站已经是空的。", "info")
                return
            self.open_empty_trash()
        elif key == "delete":
            self._delete_collection_flow(arg)
        elif key == "move":
            self._move_collection_flow(arg)

    # ---- M55：分类删除 / 移动到（旧版 on_delete_collection / on_move_collection 平移）----
    def _delete_collection_flow(self, cid: str) -> None:
        if not cid or cid in BUILTIN_CIDS:
            return
        name = self._store.collection_name(cid)
        victims = [cid] + self._store.collection_descendants(cid)
        vset = set(victims)
        n_files = sum(1 for m in self._store.file_list()
                      if m.get("category") in vset)
        n_desc = len(victims) - 1
        extra = ""
        if n_desc:
            extra += f"\n该分类下还有 {n_desc} 个子分类，将一并删除。"
        if n_files:
            extra += (f"\n其中的 {n_files} 个文件会一并移入回收站，"
                      "可在回收站里还原。")
        else:
            extra += "\n该分类下没有文件。"
        self.show_dialog({
            "title": "删除分类",
            "message": f"确定删除分类「{name}」吗？" + extra,
            "buttons": [{"label": "删除", "key": "ok", "accent": True,
                         "danger": True},
                        {"label": "取消", "key": "cancel"}],
        }, lambda v: self._delete_collection_done(cid, v))

    def _delete_collection_done(self, cid: str, v: dict) -> None:
        if v.get("__btn", "cancel") != "ok":
            return
        name = self._store.collection_name(cid)
        victims = [cid] + self._store.collection_descendants(cid)
        vset = set(victims)
        # M57：产品要求「删分类 → 其下文件也进回收站」（可还原），
        # 而不是像旧版那样把文件留成未分类。
        n_trashed = 0
        fails: list[str] = []
        for m in list(self._store.file_list()):
            if m.get("category") not in vset:
                continue
            try:
                self._store.delete_file_record(m["fid"])
                n_trashed += 1
            except OSError as e:
                fails.append(f"{m.get('name') or m.get('fid')}: {e}")
        removed = self._store.delete_collection(cid)
        if not removed:
            self.status("分类已不存在。", "err")
            return
        if self._selected_collection in vset:
            self._selected_collection = CID_ALL
        self._selected_fids = []
        self._current_meta = None
        self._ver_model.reset_rows([])
        self._rebuild_categories()
        self.reload_files()
        msg = f"已删除分类「{name}」（{len(removed)} 个分类"
        if n_trashed:
            msg += f"，{n_trashed} 个文件移入回收站"
        msg += "）"
        if fails:
            msg += f"；{len(fails)} 个文件未能移入回收站：{fails[0]}"
        self.status(msg, "err" if fails else "ok")

    def _move_collection_flow(self, cid: str) -> None:
        if not cid or cid in BUILTIN_CIDS:
            return
        # 子孙集合：移到自己子孙下会成环 → 直接从候选里剔除
        desc = set(self._store.collection_descendants(cid))
        opts = [{"cid": None, "label": "（移到顶层）"}]
        labels = self._store.collection_labels()
        for lcid, disp, depth in labels:
            if lcid == cid or lcid in desc:
                continue
            opts.append({"cid": lcid, "label": ("　" * depth) + disp})
        self.show_dialog({
            "title": f"移动分类「{self._store.collection_name(cid)}」",
            "message": "选择新的上级分类（「移到顶层」= 变回一级分类）。",
            "fields": [self._field("combo", "target", "移动到：", 0,
                                   options=opts)],
            "buttons": [{"label": "移动", "key": "ok", "accent": True},
                        {"label": "取消", "key": "cancel"}],
        }, lambda v: self._move_collection_done(cid, opts, v))

    def _move_collection_done(self, cid: str, opts: list, v: dict) -> None:
        if v.get("__btn", "cancel") != "ok":
            return
        idx = v.get("target")
        if not isinstance(idx, int) or not (0 <= idx < len(opts)):
            idx = 0
        target = opts[idx]["cid"]
        try:
            self._store.move_collection(cid, target)
        except ValueError as e:
            self.status(f"无法移动：{e}", "err")
            return
        self._rebuild_categories()
        self.reload_files()
        self.status("已移动分类。", "ok")

    @Slot(str, result=str)
    def addCollection(self, parent: str | None = None) -> str:
        """on_new_collection 平移（Store API + 展开 + 选中反馈——生产口径）。"""
        name = f"新建分类"
        try:
            r = self._store.add_collection(name, parent if parent else None)
        except ValueError as e:
            self.status(str(e), "err")
            return json.dumps({"ok": False, "reason": str(e)})
        cid = r["id"] if isinstance(r, dict) else r
        # 新分类默认折叠（_insert_collections 注释口径）→ 立刻可见需展开父节点
        if parent:
            self._col_open[parent] = True
        self._col_open[cid] = True
        self._selected_collection = cid
        self._rebuild_categories()
        return json.dumps({"ok": True, "cid": cid})

    @Slot(result=str)
    def takeRevealCid(self) -> str:
        """M33：取出并清除「待滚动可见」cid（新建分类后 QML 滚动定位用）。"""
        cid = self._reveal_cid
        self._reveal_cid = ""
        return cid

    def open_new_collection_dialog(self, parent: str | None = None) -> None:
        """on_new_collection 平移（生产口径：_ask_text 自绘输入窗）。

        标题/标签随 parent 变化（一级 vs 子级）；校验失败（空名/重名）
        → err 提示后回到弹窗并保留刚输入的内容（生产 while 循环口径）。
        创建成功 → 展开祖先 + 选中 + reveal（左栏滚动可见，生产 see(cid)）。
        """
        if parent:
            pname = self._store.collection_name(parent)
            title = f"在「{pname}」下新建子分类"
            label = "子分类名称："
        else:
            title = "新建一级分类"
            label = "分类名称："

        def done(v: dict) -> None:
            if v.get("__btn", "cancel") != "ok":
                self._new_col_initial = ""
                return
            name = (v.get("name") or "").strip()
            if not name:
                self.status("分类名不能为空", "err")
                self._new_col_initial = name
                self.open_new_collection_dialog(parent)
                return
            try:
                cid = self._store.add_collection(name, parent=parent)
            except ValueError as e:
                self.status(str(e), "err")
                self._new_col_initial = name
                self.open_new_collection_dialog(parent)
                return
            self._new_col_initial = ""
            self._reveal_cid = cid
            if parent:
                self._col_open[parent] = True
            self._col_open[cid] = True
            self._persist_col_open()
            self._selected_collection = cid
            self._rebuild_categories()
            self.reload_files()
            self.status(f"已创建分类「{name}」。", "ok")

        self.show_dialog({
            "title": title,
            "fields": [self._field("text", "name", label,
                                   self._new_col_initial,
                                   hint="提示：名称不能为空，同一层级下不能重名")],
            "buttons": [{"label": "创建", "key": "ok", "accent": True},
                        {"label": "取消", "key": "cancel"}],
        }, done)

    @Slot(result=str)
    def hotkeyRename(self) -> str:
        """_on_file_hotkey_rename/on_rename_collection 分派：内置静默返回。"""
        cid = self._selected_collection
        if not cid or cid in BUILTIN_CIDS:
            return json.dumps({"ok": False, "reason": "builtin"})
        return self.beginRename(cid)

    @Slot(result=str)
    def colEditState(self) -> str:
        return json.dumps({"editing": self._col_edit_cid})

    # ---- D5：树内拖拽进入点（QML Drag.active 驱动时仅记录候选行）----
    @Slot(str)
    def treeDragArmed(self, cid: str) -> None:
        self._col_drag_row = cid

    @Slot(result=str)
    def dropIndicator(self) -> str:
        return json.dumps(self._drop_indicator)

    @Slot(result=str)
    def colOpenState(self) -> str:
        return json.dumps(self._col_open)

    # ---- D2：展开态持久化（ui.col_open 新键；与 file_col_w 同判例）----
    def _persist_col_open(self) -> None:
        ui = self._store.config.get("ui", {}) or {}
        ui["col_open"] = dict(self._col_open)
        self._store.config["ui"] = ui


    # ================= 右栏版本区（C1–C10，M4）+ Diff（H2）=================
    # 生产对拍锚点：_render_versions L7829 / _sort_ver_tree L7103 / _chip_clip
    # L1965 / _on_ver_click L10399 / _toggle_star L10434 / _ver_jump L10364 /
    # _clear_detail L7894 / _set_ver_empty L7927 / _show_detail L7956 /
    # on_version_menu L10895 / _open_version_diff L10503 / _diff_build_payload
    # L10658 / on_version_double L10377

    verChanged = Signal()
    detailChanged = Signal(str)               # C9：详情文本（三态由 verEmpty 决定）
    diffReady = Signal(str)                   # H2：payload JSON（主线程回填）

    @Slot(result=str)
    def currentMetaJson(self) -> str:
        """当前选中文件 meta（右栏 C9/对比选择器消费）。"""
        return json.dumps(self._current_meta or {})

    def render_versions(self) -> None:
        """_render_versions 平移（无 Tk）。

        C1：vN 按提交时间正序编号；显示序按 _ver_sort（star=星标行恒聚前）。
        C2②：「最新」=版本号着 C_ACCENT（isLatest role），无背景无后缀。
        C6：时间列显示 [:10] 到日、排序用完整时间。
        """
        meta = self._current_meta
        if not meta:
            self._ver_model.reset_rows([])
            self._set_ver_empty("nofile")
            self.verChanged.emit()
            return
        versions = meta.get("versions", [])
        chrono = sorted(versions, key=lambda v: str(v.get("time") or ""))
        number = {v.get("id"): i + 1 for i, v in enumerate(chrono)}
        scol, sdesc = self._ver_sort
        if scol == "star":
            _kt = lambda v: str(v.get("time") or "")
            starred = sorted((v for v in versions if v.get("star")), key=_kt,
                             reverse=sdesc)
            others = sorted((v for v in versions if not v.get("star")), key=_kt,
                            reverse=sdesc)
            ordered = starred + others
        else:
            ordered = sorted(versions, key=lambda v: str(v.get("time") or ""))
            ordered = list(reversed(ordered)) if sdesc else ordered
        latest_id = chrono[-1].get("id") if chrono else None
        rows = []
        for ver in ordered:
            vid = ver.get("id")
            reason = ver.get("reason") or ""
            source = ver.get("source") or ""
            chip_full = (" ".join(f"{reason} {source}".split())).strip()
            rows.append({
                "vid": vid,
                "vNo": f"v{number.get(vid, '?')}",
                "timeDisplay": (ver.get("time") or "")[:10],   # C6 显示到日
                "timeSort": ver.get("time") or "",
                "star": bool(ver.get("star")),
                "chip": diffworker.chip_clip(reason or source, 8),  # C3 截断
                "chipFull": chip_full,
                "isLatest": vid == latest_id,                  # C2②（无背景无后缀）
                "auto": bool(ver.get("auto")),
                "tooltip": self._ver_row_tip(vid),
            })
        self._ver_model.reset_rows(rows)
        # C8：nofile / nover / none（_set_ver_empty 口径：看版本列表是否真空）
        self._set_ver_empty(None if rows else "nover")
        self.verChanged.emit()

    def _set_ver_empty(self, mode: str | None) -> None:
        """C8 三态：nofile=未选文件；nover=选了但无（可见）版本；None=隐藏。
        （_clear_detail L7894 口径：必须看版本列表是否真的为空——D2 修过的
        老 bug，禁退化。）"""
        if not self._current_meta and not self._selected_fids:
            mode = "nofile"
        self._ver_empty_mode = mode
        if mode is None and self._current_meta:
            versions = self._current_meta.get("versions", [])
            if not versions:
                mode = "nover"
        self._ver_empty_state = mode

    _ver_empty_state: str | None = "nofile"

    @Slot(result=str)
    def verEmptyState(self) -> str:
        return json.dumps({"state": self._ver_empty_state or "none",
                           "sortCol": self._ver_sort[0],
                           "sortDesc": self._ver_sort[1]})

    def _ver_row_tip(self, vid: str) -> str:
        """_ver_row_tip 平移：chip（修改原因）全文——行内截断，全文只在
        tooltip 与详情可得。纯元数据派生，零解析。"""
        meta = self._current_meta
        if not meta:
            return ""
        ver = next((v for v in meta.get("versions", [])
                    if v.get("id") == vid), None)
        if ver is None:
            return ""
        reason = (ver.get("reason") or "").strip()
        src = (ver.get("source") or "").strip()
        if reason and src:
            return f"{reason}\n来源：{src}"
        return reason or src or ""

    # ---- C5：整行 B1 语义（复用 M2 状态机；C4 星标热区 QML z:1 拦截）----
    @Slot(str, result=str)
    def versionEvent(self, ev_json: str) -> str:
        """右栏事件：press/release/doubleClick。星标格由 QML z:1 热区拦截
        （陷阱 c 兑现），不进入本状态机。拖出候选→C11 归 M5（如实提示）。"""
        ev = json.loads(ev_json)
        op = ev.get("op")
        if op == "press":
            vid = ev.get("vid", "")
            intents = []
            ctrl, shift = ev.get("ctrl", False), ev.get("shift", False)
            # C11：右栏拖出候选武装（B1 SM 同构；≥阈值 → external）
            self._ver_sm.press(
                vid, ev.get("x", 0), ev.get("y", 0), ctrl=ctrl, shift=shift,
                selection=list(self._selected_vids), is_trash=False,
                select_range=lambda i: list(self._selected_vids), row_index=0)
            if ctrl:
                sel = list(self._selected_vids)
                if vid in sel:
                    sel.remove(vid)
                else:
                    sel.append(vid)
                self._selected_vids = sel
                intents.append({"op": "select", "vids": sel})
            elif shift:
                # M64：Shift+点击 = 从锚点到本行的范围选择（此前是空操作）
                n = self._ver_model.rowCount()
                i = self._ver_model.index_of_vid(vid)
                a = self._ver_anchor
                if a < 0 or a >= n or i < 0:
                    sel = [vid]
                else:
                    lo, hi = min(a, i), max(a, i)
                    sel = [self._ver_model.row_at(k).get("vid")
                           for k in range(lo, hi + 1)]
                self._selected_vids = [v for v in sel if v]
                intents.append({"op": "select",
                                "vids": list(self._selected_vids)})
            else:
                # 生产 on_version_menu/单击口径：browse 单选
                self._selected_vids = [vid]
                self._ver_anchor = self._ver_model.index_of_vid(vid)
                intents.append({"op": "select", "vids": [vid]})
            # 选择后详情联动（on_version_selected 平移）
            self._emit_detail()
            return json.dumps({"intents": intents,
                               "selected": self._selected_vids})
        if op == "release":
            return json.dumps({"intents": [{"op": "none"}]})
        if op == "doubleClick":
            vid = ev.get("vid", "")
            self._ver_sm.reset()          # 双击第二次 press 重置基点（陷阱 e）
            # on_version_double 平移：星标格 QML 已拦；选中 + 打开该版本编辑
            self._selected_vids = [vid]
            self._emit_detail()
            self.openEditSession(vid)     # G1：指定版本编辑会话
            return json.dumps({"intents": [{"op": "select", "vids": [vid]}],
                               "selected": self._selected_vids})
        return json.dumps({"intents": []})

    @Slot(str)
    def setVersionSelection(self, vids_json: str) -> None:
        try:
            self._selected_vids = list(json.loads(vids_json))
        except ValueError:
            self._selected_vids = []
        self._emit_detail()

    @Slot(result=str)
    def selectedVersionVids(self) -> str:
        """C5 右栏选择的**权威回读**（M17）。

        旧 VersionPane 用 getSelection() 初始化 selectedVids，而 getSelection
        返回的是中栏的**文件 fid 列表**——把 fid 塞进 vid 镜像，语义全错
        （indexOf(model.vid) 恒不成立 → 右栏选中背景永不亮）。右栏从此只读
        自己这份 _selected_vids。
        """
        return json.dumps(list(self._selected_vids))

    def _emit_detail(self) -> None:
        """C9 详情三态（_show_detail/_clear_detail 平移）。"""
        meta = self._current_meta
        vids = [v for v in self._selected_vids if not v.startswith("trash#")]
        if len(vids) == 1 and meta:
            ver = next((v for v in meta.get("versions", [])
                        if v.get("id") == vids[0]), None)
            if ver:
                versions = sorted(meta.get("versions", []),
                                  key=lambda v: str(v.get("time") or ""))
                number = {v.get("id"): i + 1 for i, v in enumerate(versions)}
                vno = number.get(ver.get("id"), "?")
                text = (f"版本 v{vno}    "
                        f"{'★ 已星标' if ver.get('star') else '☆ 未星标'}\n"
                        f"时间：{ver.get('time') or ''}    "
                        f"类型：{'自动备份' if ver.get('auto') else '手动提交'}\n"
                        f"修改原因：\n{ver.get('reason') or ''}\n"
                        f"意见来源：\n{ver.get('source') or '（未填写）'}\n")
                idx = next((i for i, v in enumerate(versions)
                            if v.get("id") == ver.get("id")), -1)
                self.detailChanged.emit(text)
                return
        # 未选/多选 → 引导文案（_clear_detail 分层口径）
        if meta or self._selected_fids:
            hint = ("\n选择上方任一版本，这里显示它的完整信息\n"
                    "时间 · 类型 · 修改原因 · 意见来源")
        else:
            hint = ("\n先在上方文件列表里选择一个文件\n"
                    "选中后这里会显示它的版本信息")
        self.detailChanged.emit(hint)

    # ---- C4 星标（_toggle_star 平移；QML 星标热区拦截后调用）----
    @Slot(str)
    def toggleStar(self, vid: str) -> None:
        meta = self._current_meta
        if not meta:
            return
        ver = next((v for v in meta.get("versions", [])
                    if v.get("id") == vid), None)
        if ver is None:
            return
        try:
            self._store.set_version_star(meta, vid, not ver.get("star"))
        except OSError as e:
            self.status(f"保存星标失败：{e}", "err")
            return
        self._current_meta = self._store.load_meta(meta.get("fid"))
        self.render_versions()
        self._emit_detail()

    # ---- C6 排序（_sort_ver_tree 平移；时间列显示到日、排序用完整时间）----
    @Slot(str, result=str)
    def sortVersions(self, col: str) -> str:
        cur_col, cur_desc = self._ver_sort
        self._ver_sort = (col, (not cur_desc) if cur_col == col else True)
        self.render_versions()
        return json.dumps({"col": self._ver_sort[0], "desc": self._ver_sort[1]})

    # ---- C7 Home/End（_ver_jump 平移：Home=最新=首行，End=最旧=末行）----
    @Slot(str, result=str)
    def verJump(self, which: str) -> str:
        n = self._ver_model.rowCount()
        if not n:
            return json.dumps({"vid": None})
        vid = (self._ver_model.row_at(0) if which == "first"
               else self._ver_model.row_at(n - 1))["vid"]
        self._selected_vids = [vid]
        self._emit_detail()
        return json.dumps({"vid": vid})

    # ---- H2/H3：Diff（后台线程计算 + 主线程信号回填，生产 after 等价）----
    @Slot(str, str)
    def diffRequest(self, vid_a: str, vid_b: str) -> None:
        """_open_version_diff 平移入口（a=旧端，b=新端）。"""
        meta = self._current_meta
        if not meta:
            # M33：guidance 走 info（可见）——dim 会被状态栏隐藏 = 点击无反应
            self.status("请先选择一个文件", "info")
            return
        # M33：标题栏「对比」按选中顺序传入，这里按版本时间归位
        # （a=旧端 b=新端），避免反向后diff 行倒置。
        _va = next((v for v in meta.get("versions", [])
                    if v.get("id") == vid_a), {})
        _vb = next((v for v in meta.get("versions", [])
                    if v.get("id") == vid_b), {})
        if str(_va.get("time") or "") > str(_vb.get("time") or ""):
            vid_a, vid_b = vid_b, vid_a
        try:
            pa = self._store.version_file(meta, {"id": vid_a})
            pb = self._store.version_file(meta, {"id": vid_b})
        except FileNotFoundError:
            self.status("该版本的快照文件不存在，无法对比", "err")
            return
        va = next((v for v in meta.get("versions", []) if v.get("id") == vid_a), {})
        vb = next((v for v in meta.get("versions", []) if v.get("id") == vid_b), {})
        self._diff_seq += 1
        seq = self._diff_seq
        self.status("正在计算差异（本机计算，不会上传）…", "info")

        def work():
            payload = diffworker.build_payload(pa, pb, meta.get("name", ""), va, vb)
            payload["seq"] = seq
            payload["va"] = va
            payload["vb"] = vb
            payload["fileName"] = meta.get("name", "")
            self.diffReady.emit(json.dumps(payload, ensure_ascii=False))

        t = __import__("threading").Thread(target=work, daemon=True)
        t.start()

    @Slot(str, result=str)
    def diffVersionNos(self, vids_json: str) -> str:
        """vN 编号（对比选择器下拉用；_diff_version_no 口径）。"""
        meta = self._current_meta or {}
        chrono = sorted(meta.get("versions", []),
                        key=lambda v: str(v.get("time") or ""))
        number = {v.get("id"): i + 1 for i, v in enumerate(chrono)}
        return json.dumps({"labels": [f"v{i + 1}" for i in range(len(chrono))],
                           "ids": [v.get("id") for v in chrono],
                           "numbers": number})

    @Slot(str, result=str)
    def versionMenuSpec(self, vid: str) -> str:
        """on_version_menu 平移（逐字；R10 #5 已删「查看详情/设为星标」）。"""
        meta = self._current_meta
        acts: list[dict] = []
        sel = [v for v in self._selected_vids if not v.startswith("trash#")]
        if not meta:
            return json.dumps({"actions": [], "vid": vid})
        chrono = sorted(meta.get("versions", []),
                        key=lambda v: str(v.get("time") or ""))
        va = vb = None
        if len(sel) == 2:
            # P1：选中的 vid 可能已被删除/刷新掉——用 None 兜底降级到
            # 单版本菜单，别让 next() 抛 StopIteration 把右键菜单打空。
            va = next((v for v in chrono if v.get("id") == sel[0]), None)
            vb = next((v for v in chrono if v.get("id") == sel[1]), None)
        if va is not None and vb is not None:
            if str(va.get("time") or "") > str(vb.get("time") or ""):
                va, vb = vb, va                      # a=旧端，b=新端
            acts.append({"label": "对比选中的两个版本…", "key": "diff",
                         "vidA": va.get("id"), "vidB": vb.get("id"),
                         "state": "normal", "danger": False})
        elif len(sel) > 2:
            acts.append({"label": "对比选中的两个版本…",
                         "key": "", "state": "disabled", "danger": False})
        else:
            idx = next((i for i, v in enumerate(chrono) if v.get("id") == vid), -1)
            if idx > 0:
                acts.append({"label": "与上一版本对比…", "key": "diff",
                             "vidA": chrono[idx - 1].get("id"),
                             "vidB": vid, "state": "normal", "danger": False})
            else:
                acts.append({"label": "与上一版本对比…（已是最早版本）",
                             "key": "", "state": "disabled", "danger": False})
        # M66：多选时菜单项与单选一致，但「只对单个版本有意义」的置灰
        n = len(sel) if sel else 1
        one = (n == 1)
        acts.append({"label": "回到此版本（生成新版本）…",
                     "key": "restore_version" if one else "",
                     "state": "normal" if one else "disabled",
                     "danger": False})
        acts.append({"label": (f"另存为选中 {n} 个版本…" if n > 1
                               else "另存为…"),
                     "key": "save_as", "state": "normal", "danger": False})
        acts.append({"label": "编辑修改原因/意见来源…",
                     "key": "edit_info" if one else "",
                     "state": "normal" if one else "disabled",
                     "danger": False})
        acts.append({"sep": True})
        acts.append({"label": (f"删除选中的 {n} 个版本（移入回收站）…" if n > 1
                               else "删除此版本（移入回收站）…"),
                     "key": "delete_version", "state": "normal",
                     "danger": True})
        return json.dumps({"actions": acts, "vid": vid, "selCount": n})


    # ================= M5：拖拽三链路 + 编辑会话（E1–E4/G1–G8）=================
    # 生产对拍锚点：_skip_file L6738 / _walk_dir L6747 / _collect_files L6770 /
    # on_drop L6787 / _finish_file_drag L7486 / _transfer_conflict L7656 /
    # on_open_edit_session L9493 / _exit_edit_sessions_gate L9864 /
    # _restore_edit_sessions L9885 / _start_drag_out（PoC startDragOut 手法）

    # ---- E3：拖入提交（_collect_files/on_drop 平移；F1 弹窗 M6）----
    @staticmethod
    def _skip_file(p: Path) -> bool:
        name = p.name
        if name.startswith(".") or name.startswith("~$"):
            return True
        low = name.lower()
        if low.endswith(".tmp") or low.endswith(".crdownload"):
            return True
        return False

    def _walk_dir(self, folder: Path, out: list, depth: int, cap: int) -> None:
        if depth > 5 or len(out) >= cap:
            return
        try:
            entries = sorted(folder.iterdir())
        except OSError:
            return
        for e in entries:
            if len(out) >= cap:
                return
            if e.name.startswith(".") or e.name.startswith("~$"):
                continue
            try:
                if e.is_dir():
                    if depth < 5:
                        self._walk_dir(e, out, depth + 1, cap)
                elif e.is_file():
                    if self._skip_file(e):
                        continue
                    out.append(e)
            except OSError:
                continue

    def _collect_files(self, paths) -> list[Path]:
        """_collect_files 平移：文件/文件夹展开（深度≤5，单夹≤200）。"""
        out: list[Path] = []
        for p in paths:
            p = Path(p)
            try:
                if p.is_file():
                    if not self._skip_file(p):
                        out.append(p)
                elif p.is_dir():
                    sub: list[Path] = []
                    self._walk_dir(p, sub, 0, 200)
                    out.extend(sub)
            except OSError:
                continue
        return out

    @Slot(str)
    def dropProbe(self, phase: str) -> None:
        """P2：诊断写盘已删（曾把 OLE 到达阶段写进临时目录）。QML 仍在
        调用本 Slot，故保留空实现以维持调用契约。"""

    @Slot(str, result=str)
    def dropInFiles(self, urls_json: str) -> str:
        """E3 拖入提交：urls → collect → 同名则续版本否则新记录 → S7 实时刷新。

        生产 on_drop 走 F1/F2 提交弹窗（M6）；本批按 PoC 语义直接提交，
        弹窗批 M6 接管（差异已在范围声明）。"""
        try:
            raw = list(json.loads(urls_json))
        except ValueError:
            return json.dumps({"ok": False, "reason": "bad urls"})
        import urllib.parse
        raw = [urllib.parse.unquote(u[8:]) if str(u).startswith("file:///")
               else u for u in raw]
        # M49：拖入文件夹 → 按目录结构自动建分类（含子分类），不再走
        # 「选一个分类把整棵树平铺进去」的旧口径；纯文件拖入保持原逻辑。
        _paths = [Path(u) for u in raw]
        _dirs = [p for p in _paths if p.is_dir()]
        if _dirs:
            return self._import_folders(
                _dirs, [p for p in _paths if p.is_file()])
        paths = self._collect_files(raw)
        if not paths:
            return json.dumps({"ok": True, "committed": 0})
        # F1/F2 弹窗接管（生产 on_drop → open_commit_dialog/open_batch_dialog）
        target_cid = (None if self._selected_collection in BUILTIN_CIDS
                      else self._selected_collection)
        self.open_commit_dialog(paths, target_cid)
        return json.dumps({"ok": True, "dialog": True, "count": len(paths)})

    # ---- M49：拖入文件夹 → 目录结构映射为分类树 ----
    def _ensure_cat(self, name: str, parent):
        """同层级已有同名分类则复用，否则新建。返回 (cid, 是否新建)。"""
        name = (name or "").strip() or "未命名"
        for ch in self._store.collection_children(parent):
            if ch.get("name") == name:
                return ch["id"], 0
        return self._store.add_collection(name, parent), 1

    def _import_folders(self, dirs: list, loose_files: list) -> str:
        """把每个拖入的文件夹映射成一棵分类树：根名=一级分类，子目录=子分类，
        文件按其相对路径落位；同名文件自动续版本（保留历史，不打断导入）。"""
        base_parent = (None if self._selected_collection in BUILTIN_CIDS
                       else self._selected_collection)
        created = imported = nexted = skipped = 0
        fails: list[str] = []
        roots: list[str] = []

        def _commit(f: Path, cid) -> None:
            nonlocal imported, nexted
            hit = self._store.find_in_category(cid, f.name)
            if hit is not None:
                self._store.commit_next_version(hit["fid"], str(f),
                                                "文件夹导入", "拖入文件夹")
                nexted += 1
            else:
                self._store.commit_new(f, "文件夹导入",
                                       source="拖入文件夹", category=cid)
                imported += 1

        for d in dirs:
            root_cid, c = self._ensure_cat(d.name, base_parent)
            created += c
            roots.append(root_cid)
            cid_by_rel = {(): root_cid}
            for cur, subdirs, files in os.walk(d):
                cur_p = Path(cur)
                rel = cur_p.relative_to(d).parts
                cid = cid_by_rel.get(rel)
                if cid is None:                      # 兜底（理论上 walk 有序）
                    cid = root_cid
                    for part in rel:
                        cid, c2 = self._ensure_cat(part, cid)
                        created += c2
                    cid_by_rel[rel] = cid
                for sd in sorted(subdirs):
                    sub_rel = rel + (sd,)
                    sub_cid, c2 = self._ensure_cat(sd, cid)
                    created += c2
                    cid_by_rel[sub_rel] = sub_cid
                for fn in sorted(files):
                    f = cur_p / fn
                    if self._skip_file(f):
                        skipped += 1
                        continue
                    try:
                        _commit(f, cid)
                    except (ValueError, OSError) as e:
                        fails.append(f"{fn}: {e}")

        for f in loose_files:
            if self._skip_file(f):
                skipped += 1
                continue
            try:
                _commit(f, base_parent)
            except (ValueError, OSError) as e:
                fails.append(f"{f.name}: {e}")

        self.reload_files()
        if roots:
            self.selectCollection(roots[0])
        msg = f"已导入 {imported} 个文件，新建 {created} 个分类"
        if nexted:
            msg += f"，{nexted} 个同名文件续了新版本"
        if skipped:
            msg += f"，跳过 {skipped} 个"
        if fails:
            msg += f"，失败 {len(fails)} 个（{fails[0]}）"
        self.status(msg, "err" if fails else "ok")
        return json.dumps({"ok": True, "imported": imported,
                           "created": created, "nexted": nexted,
                           "skipped": skipped, "failed": len(fails)})

    # ---- M39：外部文件拖到某个文件行 → 直接为该文件续版本 ----
    @Slot(str, str, result=str)
    def dropOntoFile(self, fid: str, urls_json: str) -> str:
        """拖到文件行落点：单文件 → 极小确认窗（原因必填，预填「拖拽续版本」）
        → store.commit_next_version。多文件/拖到回收站行在 QML 侧已被挡；
        此处再兜一层：多文件拒绝并提示。类型不同只提示不拦截（与现有
        「全部续版本」口径一致——功能一致性是硬指标）。"""
        try:
            raw = list(json.loads(urls_json))
        except ValueError:
            return json.dumps({"ok": False, "reason": "bad urls"})
        import urllib.parse
        raw = [urllib.parse.unquote(u[8:]) if str(u).startswith("file:///")
               else u for u in raw]
        paths = self._collect_files(raw)
        if not paths:
            return json.dumps({"ok": True, "cancelled": True})
        if len(paths) > 1:
            self.status("拖到某个文件上一次只能续一个版本（本次 "
                        f"{len(paths)} 个），请逐个拖入。", "err")
            return json.dumps({"ok": False, "reason": "multiple"})
        meta = self._store.load_meta(fid)
        if meta is None:
            self.status("目标文件记录不存在（可能已被删除）。", "err")
            return json.dumps({"ok": False, "reason": "no record"})
        p = paths[0]
        src_name = p.name
        dst_name = meta.get("name", "")
        ext_same = (Path(src_name).suffix.lower()
                    == Path(dst_name).suffix.lower())
        msg = (f"将把「{src_name}」作为「{dst_name}」的新版本提交。")
        if not ext_same:
            msg += "\n\n注意：两个文件的类型不同，请确认确实要这样续版本。"
        self.show_dialog({
            "title": "续版本",
            "message": msg,
            "fields": [self._field("text", "reason", "修改原因（必填）：",
                                   "拖拽续版本")],
            "buttons": [{"label": "续版本", "key": "ok", "accent": True},
                        {"label": "取消", "key": "cancel"}],
        }, lambda v: self._drop_onto_done(fid, str(p), v))
        return json.dumps({"ok": True, "dialog": True, "fid": fid})

    def _drop_onto_done(self, fid: str, path: str, v: dict) -> None:
        if v.get("__btn", "cancel") == "cancel":
            return
        reason = (v.get("reason") or "").strip()
        if not reason:
            # 与 _commit_dialog_done 同口径：不偷偷用默认值，提示后作罢
            self.status("请填写修改原因", "err")
            return
        meta = self._store.load_meta(fid)
        name = meta.get("name", "") if meta else ""
        try:
            self._store.commit_next_version(fid, path, reason, "")
        except (ValueError, OSError) as e:
            self.status(f"续版本失败：{e}", "err")
            return
        self.reload_files(keep_selection=True)
        self.setSelection(json.dumps([fid]))
        self.status(f"已为「{name}」续版本（{reason}）。", "ok")

    # ---- E4：拖文件到分类（_finish_file_drag 平移；三选弹窗 M6 视觉）----
    @Slot(str, str, result=str)
    def fileTransfer(self, fids_json: str, target_cid: str) -> str:
        """拖到分类落地：跳过原地/内置，同名冲突记账，set_category 移动。"""
        try:
            fids = list(json.loads(fids_json))
        except ValueError:
            fids = []
        if not fids or target_cid in (CID_ALL, CID_TRASH):
            return json.dumps({"ok": True, "moved": 0, "note": "cancelled"})
        target = None if target_cid == CID_UNFILED else target_cid
        cname = ("未分类" if target is None
                 else self._store.collection_name(target))
        moved = skipped = 0
        fails: list[str] = []
        conflicts: list[tuple] = []      # (src_meta, dst_meta)
        for fid in fids:
            meta = self._store.load_meta(fid)
            if meta is None:
                continue
            if target == meta.get("category"):
                skipped += 1
                continue
            hit = self._store.find_in_category(target, meta.get("name", ""))
            if hit is not None and hit.get("fid") != fid:
                dst_meta = self._store.load_meta(hit.get("fid"))
                if dst_meta is not None:
                    conflicts.append((meta, dst_meta))
                continue
            try:
                self._store.set_category(fid, target)
                moved += 1
            except (ValueError, OSError) as e:
                fails.append(f"{meta.get('name') or fid}: {e}")
        self.reload_files(keep_selection=True)
        # 生产 _reselect 口径：存活目标行重新选上
        alive = [f for f in fids if self._model.index_of_fid(f) >= 0]
        if alive:
            self._selected_fids = alive
            self._sync_detail_state()       # P0：恢复的选中集要同步右栏缓存
        if fails:
            self.status(f"已移动 {moved} 个，{len(fails)} 个失败：{fails[0]}",
                        "err")
        elif moved:
            self.status(f"已移动 {moved} 个文件到「{cname}」。", "ok")
        elif skipped and not conflicts:
            self.status("所选文件本来就在该分类下。", "info")
        if conflicts:
            # M65：同名不再只提示——逐个走「续版本 / 重命名 / 取消」三选
            self._transfer_queue = [(m, target, d) for m, d in conflicts]
            self._next_transfer_conflict()
        return json.dumps({"ok": not fails, "moved": moved,
                           "skipped": skipped, "failed": len(fails),
                           "conflicts": len(conflicts)})

    # ---- E1：中栏/右栏统一拖出入口（B1 SM external_drag 已接）----
    def _start_drag_out_versions(self, vids: list[str]) -> None:
        """C11：右栏选中版本集拖出（payload=那些版本，非最新版语义）。"""
        meta = self._current_meta
        if not meta:
            self.dragOutFinished.emit()
            return
        pairs = []
        for vid in vids:
            ver = next((v for v in meta.get("versions", [])
                        if v.get("id") == vid), None)
            if ver is not None:
                pairs.append((meta, ver))
        if not pairs:
            self.dragOutFinished.emit()
            return
        # M78：和文件拖出走同一套——先收自绘卡片，再记录载荷。
        # 少了这两个，版本拖回窗口会被窗口级 DropArea 当成"外部文件拖入"，
        # 直接提交一个新版本（1.1.22 实测现象）。
        self.internalDragStarted.emit()
        paths = self._share.materialize_share(pairs)   # E2：原名_vN.ext
        if not paths:
            self.dragOutFinished.emit()
            return
        self.status(f"正在拖出 {len(paths)} 个版本文件…", "info")
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(p) for p in paths])
        mime.setText("\n".join(Path(p).name for p in paths))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(self._drag_pixmap(len(paths), paths))
        self._drag_payload = {"kind": "versions", "vids": list(vids)}
        try:
            drag.exec(Qt.DropAction.CopyAction, Qt.DropAction.CopyAction)
        finally:
            self._drag_payload = None
            self._share.on_drag_end()
            self.dragOutFinished.emit()

    @Slot(str, result=str)
    def versionDragEvent(self, ev_json: str) -> str:
        """C11：右栏拖出 move（持久 _ver_sm；≥阈值 → external_drag → 拖出）。"""
        ev = json.loads(ev_json)
        intents = self._ver_sm.move(
            ev.get("x", 0), ev.get("y", 0),
            gx=ev.get("gx", 0), gy=ev.get("gy", 0),
            win_x=ev.get("winX", 0), win_y=ev.get("winY", 0),
            win_w=ev.get("winW", 0), win_h=ev.get("winH", 0))
        for it in intents:
            if it.get("op") == "external_drag":
                self._start_drag_out_versions(list(self._selected_vids))
        return json.dumps({"intents": intents})

    # ---- G1/G3：编辑会话入口与询问 ----
    @Slot(str, result=str)
    def openEditSession(self, vid: str = "") -> str:
        """G1：双击中栏=最新版；双击右栏版本行=指定版。"""
        meta = self._current_meta
        if not meta:
            return json.dumps({"ok": False, "reason": "请先选择一个文件"})
        ver = None
        if vid:
            ver = next((v for v in meta.get("versions", [])
                        if v.get("id") == vid), None)
            if ver is None:
                return json.dumps({"ok": False, "reason": "版本不存在"})
        r = self._edit_sessions.open(meta, ver)
        if r.get("ok"):
            try:
                os.startfile(r["path"])  # noqa: S606（生产 on_open_edit_session 口径）
            except OSError as e:
                return json.dumps({"ok": False, "reason": f"启动外部程序失败：{e}"})
            self.status(f"已打开「{meta.get('name', '')}」的编辑副本"
                        "（改动会被检测并询问是否保存为新版本）。", "ok")
        else:
            self.status(f"打开失败：{r.get('reason', '')}", "err")
        return json.dumps(r)

    def _poll_edit_sessions(self) -> None:
        """G2/G3：轮询 tick（EditSessions 内部代次续链 + on_ask 回调）。"""
        self._edit_sessions.poll()

    @Slot(str, str, result=str)
    def resolveEditAsk(self, key: str, choice: str) -> str:
        r = self._edit_sessions.resolve_ask(key, choice)
        if r.get("ok") and r.get("action") in ("committed", "discarded"):
            self.reload_files(keep_selection=True)
        return json.dumps(r)

    # ---- A8：关窗闸门（on_close 平移；M6 弹窗渲染 pending）----
    @Slot(result=bool)
    def requestClose(self) -> bool:
        ok, pending = self._edit_sessions.exit_gate()
        if not ok:
            self.closeRejected.emit(json.dumps(pending, ensure_ascii=False))
            self.status("有未提交的编辑会话，关闭已拦截（M6 弹窗接线）", "err")
            return False
        self._edit_sessions.stop_polling()
        return True

    @Slot(result=str)
    def pendingEditAsks(self) -> str:
        return json.dumps(self._edit_sessions.asks, ensure_ascii=False)


    # ================= M6：F 组弹窗引擎 + K 快捷键 + T2 =================
    # 生产对拍锚点：open_commit_dialog L9082 / open_batch_dialog L9235 /
    # _ask_batch_conflict L9360 / _transfer_conflict L7656 / _ask_text L7580 /
    # _pending_edits_dialog L9766 / _handle_orphan_session L9718 /
    # _open_edit_version_info L10949 / on_rename_file L8775 /
    # on_delete_file_record(_confirm) / _EDIT_VERSION_INFO R14

    def show_dialog(self, spec: dict, on_result: callable) -> None:
        """弹窗引擎：spec 纯数据（可单测），QML DialogHost 渲染；
        用户点按钮 → dialogResult(values) → 回调结算。"""
        self._dialog_seq += 1
        rid = f"d{self._dialog_seq}"
        self._pending_dialogs[rid] = on_result
        spec = dict(spec, rid=rid)
        self.dialogRequested.emit(json.dumps(spec, ensure_ascii=False))

    @Slot(str)
    def dialogResult(self, res_json: str) -> None:
        try:
            res = json.loads(res_json)
        except ValueError:
            return
        fn = self._pending_dialogs.pop(res.get("rid", ""), None)
        if fn is not None:
            fn(res.get("values", {}))

    def _field(self, ftype: str, key: str, label: str, value="",
               options=None, hint: str = "", readonly: bool = False) -> dict:
        d = {"type": ftype, "key": key, "label": label, "value": value}
        if options is not None:
            d["options"] = options
        if hint:
            d["hint"] = hint
        if readonly:
            d["readonly"] = True
        return d

    def _col_options(self, default_cid=None) -> tuple[list[dict], int]:
        """分类下拉（含 未分类=None，生产 _init_col_vars 口径）。"""
        opts = [{"cid": None, "label": "未分类"}]
        for ch in self._store.collections():
            opts.append({"cid": ch["id"], "label": ch["name"]})
        idx = 0
        for i, o in enumerate(opts):
            if o["cid"] == default_cid:
                idx = i
        return opts, idx

    # ---- F1/F2：提交 / 批量提交 ----
    @Slot()
    def openCommitDialog(self) -> None:
        """工具栏「提交新版本」/F1：无预选路径（弹窗内可编辑，粘贴即用）。
        拖入文件仍走 dropInFiles → open_commit_dialog(paths)。"""
        self.open_commit_dialog([])

    def open_commit_dialog(self, paths: list, default_cid=None) -> None:
        opts, idx = self._col_options(default_cid)
        many = len(paths) > 1
        fields = []
        if many:
            fields.append(self._field("list", "paths", "文件清单",
                                      [str(p) for p in paths[:200]]))
        elif paths:
            fields.append(self._field("text", "path", "文件：", str(paths[0]),
                                      readonly=True))
        else:
            # 工具栏「提交新版本」/F1 入口：无预选路径 → 可编辑（生产旧版
            # open_commit_dialog("") 口径：Entry 可编辑 + 浏览）。
            fields.append(self._field("file", "path", "文件：", "",
                                      hint="点「选择…」挑选文件，也可直接粘贴路径"))
        fields.append(self._field("combo", "category", "分类：", idx,
                                  options=opts))
        if many:
            # M83：批量入口原来 reason 空着，用户每次都要手打。与单文件
            # 入口一样预填「首次提交」（仍可编辑）。
            fields.append(self._field("text", "reason",
                                      "修改原因（必填，会自动附加「（文件：xxx）」）：",
                                      "首次提交"))
            fields.append(self._field("text", "source", "意见来源（选填）：", ""))
        else:
            fields.append(self._field("text", "reason", "修改原因（必填）：",
                                      "首次提交"))   # R8 #4 预填
            fields.append(self._field("text", "source", "意见来源（选填）", "无",
                                      hint="如：评审意见"))
        self.show_dialog({
            "title": "批量提交新版本" if many else "提交新版本",
            "fields": fields,
            # M50：路径为空时「保存版本」置灰（否则点一下弹窗就关、用户会懵）
            "okRequire": ["path"] if not many else [],
            "buttons": [{"label": "保存版本", "key": "ok", "accent": True},
                        {"label": "取消", "key": "cancel"}],
        }, lambda v: self._commit_dialog_done(paths, v))

    def _commit_dialog_done(self, paths: list, v: dict) -> None:
        if v.get("__btn", "cancel") == "cancel":
            return
        if not paths:
            # 工具栏/F1 可编辑路径模式：解析并校验用户填的路径
            raw = (v.get("path") or "").strip().strip('"').strip("'")
            if not raw:
                self.status("请填写要提交的文件路径", "err")
                return
            p = Path(os.path.expandvars(os.path.expanduser(raw)))
            if not p.is_file():
                self.status(f"文件不存在：{p}", "err")
                return
            paths = [str(p)]
        opts, _ = self._col_options()
        # M47：QML 侧 combo 可能回传 索引(int) / 数字串 / cid / 显示名，
        # 统一解析——实测「选了分类仍进未分类」就是这里只认 int 导致的。
        raw = v.get("category")
        cid = None
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            i = int(raw)
            cid = opts[i]["cid"] if 0 <= i < len(opts) else None
        elif isinstance(raw, str):
            s = raw.strip()
            if s.isdigit() and 0 <= int(s) < len(opts):
                cid = opts[int(s)]["cid"]
            else:
                hit = next((o for o in opts if o["cid"] == s), None) \
                    or next((o for o in opts if o["label"] == s), None)
                cid = hit["cid"] if hit else None
        if raw not in (None, "") and cid is None:
            print(f"[commit] 分类值无法解析：{raw!r}，按未分类提交",
                  file=sys.stderr)
        reason = (v.get("reason") or "").strip()
        if not reason:
            self.status("请填写修改原因", "err")
            return
        source = (v.get("source") or "").strip()
        conflicts, fresh = [], []
        seen: set = set()
        for p in paths:
            nm = Path(p).name
            if self._store.find_in_category(cid, nm) is not None \
                    or nm.lower() in seen:
                conflicts.append(p)
            else:
                seen.add(nm.lower())
                fresh.append(p)
        if conflicts:
            self.show_dialog({
                "title": "同名文件",
                "message": (f"有 {len(conflicts)} 个文件与库中现有文件"
                            "（或彼此）同名。\n\n"
                            "·全部续版本：同名文件作为现有文件的新版本提交\n"
                            "·跳过重名，仅提交其余\n"
                            "·取消：一个都不提交"),
                "buttons": [{"label": "全部续版本", "key": "merge", "accent": True},
                            {"label": "跳过重名，仅提交其余", "key": "skip"},
                            {"label": "取消", "key": "cancel"}],
            }, lambda v2: self._batch_conflict_done(
                paths, fresh, cid, reason, source, v2))
            return
        self._commit_files(paths, cid, reason, source)

    def _batch_conflict_done(self, paths, fresh, cid, reason, source, v) -> None:
        btn = v.get("__btn", "cancel")
        if btn == "cancel":
            return
        self._commit_files(paths if btn == "merge" else fresh,
                           cid, reason, source)

    def _commit_files(self, todo: list, cid, reason: str, source: str) -> None:
        ok_n, fail, nexted = 0, [], 0
        many = len(todo) > 1
        self._set_busy(True, "正在提交 %d 个文件…" % len(todo))
        try:
            ok_n, fail, nexted = self._commit_files_inner(
                todo, cid, reason, source, many)
        finally:
            self._set_busy(False)
        self.reload_files()
        if fail:
            if len(fail) == 1:
                self.status("提交失败：%s" % fail[0], "err")
            else:
                self.status("提交完成：成功 %d 个，失败 %d 个"
                            % (ok_n + nexted, len(fail)), "err")
                self.show_dialog({
                    "title": "有 %d 个文件没能提交" % len(fail),
                    "message": ("逐个原因：\n\n"
                                + "\n".join("· " + f for f in fail[:50])
                                + ("\n\n（只列前 50 条）" if len(fail) > 50 else "")),
                    "buttons": [{"label": "知道了", "key": "ok", "accent": True}],
                }, lambda v: None)
            return
        self.status("已提交 %d 个新文件"
                    % ok_n
                    + ("，%d 个续了新版本" % nexted if nexted else "") + "。",
                    "ok")

    def _commit_files_inner(self, todo, cid, reason, source, many):
        ok_n, fail, nexted = 0, [], 0
        for p in todo:
            r = reason if not many else f"{reason}（文件：{Path(p).name}）"
            try:
                hit = self._store.find_in_category(cid, Path(p).name)
                if hit is not None:
                    self._store.commit_next_version(hit["fid"], str(p), r, source)
                    nexted += 1
                else:
                    self._store.commit_new(p, r, source=source, category=cid)
                    ok_n += 1
            except (ValueError, OSError) as e:
                fail.append(f"{Path(p).name}: {e}")
        return ok_n, fail, nexted

    # ---- F4：转移冲突三选（_transfer_conflict 平移）----
    def _next_transfer_conflict(self) -> None:
        """M65：批量同名冲突逐个结算（每结算完一个弹下一个）。"""
        q = getattr(self, "_transfer_queue", None) or []
        if not q:
            self._transfer_queue = []
            self.reload_files(keep_selection=True)
            return
        src_meta, target_cid, dst_meta = q.pop(0)
        self._transfer_queue = q
        self.open_transfer_conflict(src_meta, target_cid, dst_meta)

    def open_transfer_conflict(self, src_meta: dict, target_cid, dst_meta: dict) -> None:
        tname = ("未分类" if target_cid is None
                 else self._store.collection_name(target_cid))
        self.show_dialog({
            "title": "同名文件",
            "message": (f"「{tname}」下已有同名文件「{dst_meta.get('name')}」。\n\n"
                        "·续版本：把本文件最新版并入该文件，"
                        "本记录整体移入回收站（可找回）\n"
                        "·重命名：换个名字后移入该分类\n"
                        "·取消：不做任何改动"),
            "fields": [self._field("text", "newName", "新文件名：",
                                   src_meta.get("name", ""),
                                   hint="名称里不能包含 \\ / : * ? \" < > |")],
            "buttons": [
                {"label": f"续版本到「{dst_meta.get('name')}」",
                 "key": "merge", "accent": True},
                {"label": "重命名后移动", "key": "rename"},
                {"label": "取消", "key": "cancel"},
            ],
        }, lambda v: self._transfer_conflict_done(src_meta, target_cid,
                                                  dst_meta, v))

    def _transfer_conflict_done(self, src_meta, target_cid, dst_meta, v) -> None:
        btn = v.get("__btn", "cancel")
        src_fid = src_meta["fid"]
        if btn == "cancel":
            self._next_transfer_conflict()
            return
        if btn == "merge":
            try:
                latest = self._store.latest_version(src_meta)
                snap = self._store.files_dir / src_fid / latest["id"]
                self._store.commit_next_version(
                    dst_meta["fid"], snap,
                    f"自「{src_meta.get('name')}」转移并入")
                self._store.delete_file_record(src_fid)
            except (ValueError, OSError) as ex:
                self.status(f"合并失败：{ex}", "err")
                return
            self._edit_sessions.drop_for_fid(src_fid)   # A13 联动
            self.reload_files()
            self.status(f"已并入「{dst_meta.get('name')}」，原记录移入回收站。", "ok")
            self._next_transfer_conflict()
            return
        elif btn == "rename":
            new = (v.get("newName") or "").strip()
            if not new:
                return
            try:
                self._store.rename_record(src_fid, new)
                self._store.set_category(src_fid, target_cid)
            except (ValueError, OSError) as ex:
                self.status(str(ex), "err")
                return
            self.reload_files()
            self.status(f"已移动并重命名为「{new}」。", "ok")
            self._next_transfer_conflict()
            return

    # ---- F3：文本询问（_ask_text 平移）----
    # ---- M66：系统「另存为 / 选目录」对话框（tk 版是文件对话框，QML 版
    # 之前用文本框让用户手打完整路径，点了像没反应，统一改为原生对话框）----
    def ask_save_path(self, title: str, default_name: str, on_done) -> None:
        from PySide6.QtWidgets import QFileDialog
        start = str(Path.home() / (default_name or "导出文件"))
        try:
            path, _ = QFileDialog.getSaveFileName(None, title, start)
        except Exception as e:                       # noqa: BLE001
            self.status(f"无法打开另存对话框：{e}", "err")
            return
        on_done(path or None)

    def ask_directory(self, title: str, on_done) -> None:
        from PySide6.QtWidgets import QFileDialog
        try:
            path = QFileDialog.getExistingDirectory(None, title,
                                                    str(Path.home()))
        except Exception as e:                       # noqa: BLE001
            self.status(f"无法打开目录选择：{e}", "err")
            return
        on_done(path or None)

    def ask_text(self, title: str, label: str, initial: str = "",
                 hint: str = "", ok_text: str = "确定",
                 on_result: callable = None) -> None:
        self.show_dialog({
            "title": title,
            "fields": [self._field("text", "value", label, initial, hint=hint)],
            "buttons": [{"label": ok_text, "key": "ok", "accent": True},
                        {"label": "取消", "key": "cancel"}],
        }, lambda v: on_result(
            (v.get("value") or "").strip() if v.get("__btn") == "ok" else None))

    # ---- F8：确认类 ----
    def confirm(self, title: str, message: str, ok_text: str = "确定",
                danger: bool = False, on_result: callable = None) -> None:
        self.show_dialog({
            "title": title, "message": message,
            "buttons": [{"label": ok_text, "key": "ok",
                         "danger": danger, "accent": not danger},
                        {"label": "取消", "key": "cancel"}],
        }, lambda v: on_result(v.get("__btn") == "ok"))

    def open_delete_file_record(self, fids: list) -> None:
        n = len(fids)
        self.confirm(
            "删除文件记录",
            (f"删除 {n} 个文件记录（移入回收站）？\n\n"
             "·记录与全部版本一起进入回收站，可找回\n"
             "·磁盘上不会删除任何文件"),
            ok_text=f"删除 {n} 个记录", danger=True,
            on_result=lambda yes: self._delete_file_record_done(fids, yes))

    def _delete_file_record_done(self, fids: list, yes: bool) -> None:
        if not yes:
            return
        for fid in fids:
            self._store.delete_file_record(fid)
            self._edit_sessions.drop_for_fid(fid)    # A13 联动
        self.reload_files()
        self.status(f"已删除 {len(fids)} 个文件记录（移入回收站）。", "ok")

    def open_delete_version(self, ver_id: str) -> None:
        meta = self._current_meta
        if not meta:
            return
        ver = next((v for v in meta.get("versions", [])
                    if v.get("id") == ver_id), None)
        if ver is None:
            return
        self.confirm(
            "删除版本",
            (f"删除版本 {ver.get('time', '')[:16]}（移入回收站）？\n\n"
             "·只删这一个版本，文件记录与其他版本不受影响\n"
             "·可在回收站找回"),
            ok_text="删除此版本", danger=True,
            on_result=lambda yes: self._delete_version_done(ver_id, yes))

    def _delete_version_done(self, ver_id: str, yes: bool) -> None:
        if not yes or not self._current_meta:
            return
        try:
            self._store.delete_version(self._current_meta["fid"], ver_id)
        except (ValueError, OSError) as e:
            self.status(str(e), "err")
            return
        self._current_meta = self._store.load_meta(self._current_meta["fid"])
        # P1：被删版本不能再留在选中集里（否则详情会指向不存在的版本）
        if ver_id in self._selected_vids:
            self._selected_vids.remove(ver_id)
        self.render_versions()
        self._emit_detail()
        self.status("已删除此版本（移入回收站）。", "ok")

    def open_empty_trash(self) -> None:
        n, size = self._store.trash_summary()
        self.confirm("清空回收站",
                     f"清空回收站全部 {n} 项（{self._fmt_size(size)}）？\n"
                     "此操作不可找回。",
                     ok_text="清空", danger=True,
                     on_result=lambda yes: self._empty_trash_done(yes))

    def _empty_trash_done(self, yes: bool) -> None:
        reopen = getattr(self, "_settings_reopen_after", False)
        self._settings_reopen_after = False
        if not yes:
            if reopen:
                self.open_settings()           # 取消也回到设置（旧版弹窗不关）
            return
        self._store.empty_trash()
        self.reload_files()
        self.status("回收站已清空。", "ok")
        if reopen:
            self.open_settings()

    # ---- F9：编辑版本信息（R14：只改元数据）----
    def open_edit_version_info(self, ver_id: str) -> None:
        meta = self._current_meta
        if not meta:
            return
        ver = next((v for v in meta.get("versions", [])
                    if v.get("id") == ver_id), None)
        if ver is None:
            return
        self.show_dialog({
            "title": "编辑修改原因 / 意见来源",
            "message": "只修改元数据：不动快照文件、不新增版本、不改版本时间。",
            "fields": [
                self._field("textarea", "reason", "修改原因：",
                            ver.get("reason") or ""),
                self._field("text", "source", "意见来源：",
                            ver.get("source") or ""),
            ],
            "buttons": [{"label": "保存", "key": "ok", "accent": True},
                        {"label": "取消", "key": "cancel"}],
        }, lambda v: self._edit_version_info_done(ver_id, v))

    def _edit_version_info_done(self, ver_id: str, v: dict) -> None:
        if v.get("__btn", "cancel") != "ok" or not self._current_meta:
            return
        meta = self._store.load_meta(self._current_meta["fid"])
        ver = next((x for x in meta.get("versions", [])
                    if x.get("id") == ver_id), None)
        if ver is None:
            return
        ver["reason"] = (v.get("reason") or "").strip()
        ver["source"] = (v.get("source") or "").strip()
        self._store._save_json(self._store._meta_path(meta["fid"]), meta)
        self._current_meta = meta
        self.render_versions()
        self._emit_detail()
        self.status("已更新版本信息。", "ok")

    # ---- G3/G6：保存询问与退出兜底弹窗（消费 M5 信号）----
    def open_edit_save_ask(self, ask: dict) -> None:
        self.show_dialog({
            "title": "检测到未保存的修改",
            "message": (f"「{ask.get('name', '')}」的编辑副本内容已变化。\n\n"
                        "·提交新版本：以当前副本内容提交\n"
                        "·放弃修改：删除副本（不提交）\n"
                        "·取消：暂不处理（内容再变会重新询问）"),
            "buttons": [{"label": "提交新版本", "key": "commit", "accent": True},
                        {"label": "放弃修改", "key": "discard", "danger": True},
                        {"label": "取消", "key": "cancel"}],
        }, lambda v: self.resolveEditAsk(ask["key"], v.get("__btn", "cancel")))

    def open_pending_edits_dialog(self, pending: list) -> None:
        """_pending_edits_dialog 平移：批量提交（共用一个修改原因）/放弃/取消退出。"""
        lines = []
        for p in pending:
            meta = self._store.load_meta(p.get("fid") or "")
            versions = (meta or {}).get("versions", []) or []
            chrono = sorted(versions, key=lambda v: str(v.get("time") or ""))
            vno = next((i + 1 for i, v in enumerate(chrono)
                        if v.get("id") == p.get("verId")), None)
            lines.append(f"·{p.get('name', '')}"
                         + (f"（编辑 v{vno}）" if vno else ""))
        self.show_dialog({
            "title": "未提交修改",
            "message": "以下文件的编辑副本有未保存的修改：",
            "fields": [
                self._field("list", "files", "", lines[:20]),
                self._field("text", "reason", "修改原因（必填）：", ""),
            ],
            "buttons": [{"label": "全部提交", "key": "commit", "accent": True},
                        {"label": "放弃修改", "key": "discard", "danger": True},
                        {"label": "取消退出", "key": "cancel"}],
        }, lambda v: self._pending_edits_done(pending, v))

    def _pending_edits_done(self, pending: list, v: dict) -> None:
        btn = v.get("__btn", "cancel")
        reason = (v.get("reason") or "").strip()
        if btn == "commit":
            if not reason:
                self.status("请填写修改原因", "err")
                self.open_pending_edits_dialog(pending)
                return
            for p in pending:
                self._edit_sessions.resolve_ask(p["key"], "commit")
            self.reload_files()
            self.status(f"已提交 {len(pending)} 个编辑副本。", "ok")
        elif btn == "discard":
            for p in pending:
                self._edit_sessions.resolve_ask(p["key"], "discard")
            self.reload_files()
            self.status("已放弃全部未提交修改。", "ok")

    # ---- G4：孤儿会话清理（_handle_orphan_session 平移）----
    def open_orphan_session(self, key: str, s: dict) -> None:
        s["orphan"] = True
        self._store.save_edit_sessions(self._edit_sessions.sessions)
        self.show_dialog({
            "title": "编辑工作副本",
            "message": (f"「{s.get('name', '')}」的编辑工作副本还在，"
                        "但库中对应的记录/版本已不存在。\n"
                        "可以打开它所在的文件夹自行处理，或删除工作副本；"
                        "也可以以后再说。"),
            "buttons": [{"label": "打开所在文件夹", "key": "open"},
                        {"label": "删除工作副本", "key": "drop", "danger": True},
                        {"label": "以后再说", "key": "later"}],
        }, lambda v: self._orphan_done(key, v))

    def _orphan_done(self, key: str, v: dict) -> None:
        btn = v.get("__btn", "later")
        s = self._edit_sessions.sessions.get(key)
        if btn == "open" and s:
            target = Path(s.get("path") or "")
            d = target.parent if target.is_file() else target
            if Path(d).is_dir():
                os.startfile(str(d))  # noqa: S606
            self.open_orphan_session(key, s)   # 处理完继续问
        elif btn == "drop":
            self._edit_sessions.drop(key)
            self._store.save_edit_sessions(self._edit_sessions.sessions)
            self.status("已删除工作副本。", "ok")

    # ---- F5/F6：设置与库迁移（M17 任务9：按旧版 on_open_settings 四组重建）----
    # 旧版基准：.pyw L10080-10168（库位置/维护/外观/关于 + 关闭）。产品决策：
    # 动作按钮 keepOpen —— 旧版点动作
    # 后弹窗停在原地。文件/目录选择沿用「文本框填路径」形态
    # 一致：QtWidgets/QtQuickDialogs2 在发布包裁剪清单里，原生选框不可用）。
    dialogFieldPicked = Signal(str, str)

    @Slot(str)
    def pickFileForField(self, key: str) -> None:
        """M50：弹窗内的「选择…」——用系统文件对话框挑一个文件回填。"""
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            None, "选择文件", str(Path.home()), "所有文件 (*.*)")
        if path:
            self.dialogFieldPicked.emit(key, path)

    @Slot()
    def open_settings(self) -> None:
        try:
            n_trash, sz_trash = self._store.trash_summary()
        except Exception:                      # 清单异常也不能让弹窗半开（旧版 L10126）
            n_trash, sz_trash = 0, 0
        # M102：每个 group 带 section 标签，弹窗左侧据此出导航（3 个区：
        # 存储 / 界面 / 关于）。点击导航滚动到该区第一张卡片。
        # M35 §4.3：四组卡片（库位置 / 备份与维护 / 回收站 / 外观）+
        # 主题分段控件（type=segment）。渲染契约见 DialogHost.qml：
        #   options[].label/value；点选即 submit("theme_switch", keepOpen)
        #   → _settings_done 里 setThemeMode + open_settings 原地刷新。
        self.show_dialog({
            "title": "设置",
            "groups": [
                {"title": "库位置", "section": "存储", "items": [
                    {"type": "text", "value": str(self._store.store_dir)},
                    {"type": "buttons", "buttons": [
                        {"label": "复制路径", "key": "copy_path", "keepOpen": True},
                        {"label": "更改位置…", "key": "change_dir"},
                    ]},
                ]},
                {"title": "备份与维护", "section": "存储", "items": [
                    {"type": "buttons", "buttons": [
                        {"label": "导出备份…", "key": "export_backup"},
                        {"label": "重建索引", "key": "rebuild_index",
                         "keepOpen": True},
                    ]},
                ]},
                {"title": "回收站", "section": "存储", "items": [
                    {"type": "buttons", "buttons": [
                        {"label": "清空回收站…", "key": "empty_trash",
                         "danger": True}],
                     "note": (f"回收站现有 {n_trash} 项，约 {self._fmt_size(sz_trash)}"
                              if n_trash else "回收站当前为空")},
                ]},
                {"title": "行为", "section": "界面", "items": [
                    {"type": "toggle", "key": "toggle_tray",
                     "label": "关闭窗口时隐藏到托盘",
                     "on": bool(self._close_to_tray)},
                ]},
                {"title": "外观", "section": "界面", "items": [
                    {"type": "segment", "key": "theme",
                     "value": self._theme_mode,
                     "options": [{"label": "浅色", "value": "light"},
                                 {"label": "深色", "value": "dark"}]},
                ]},
                {"title": "关于", "section": "关于", "items": [
                    {"type": "text", "value": f"井然 v{APP_VERSION}"
                                              f"（构建 {APP_BUILD}）"},
                ]},
            ],
            # M31：按产品要求删去右下「关闭」按钮——关闭只走右上 ×（Esc 保留）
            "buttons": [],
        }, lambda v: self._settings_done(v))

    def _settings_done(self, v: dict) -> None:
        btn = v.get("__btn", "cancel")
        if btn == "cancel":
            return
        if btn == "empty_trash":
            # 二次确认；确认/取消后在 _empty_trash_done 回到设置
            self._settings_reopen_after = True
            self.open_empty_trash()
            return
        if btn == "copy_path":
            QGuiApplication.clipboard().setText(str(self._store.store_dir))
            self.status("版本库路径已复制到剪贴板。", "ok")
            self.open_settings()               # 重开（宿主单例，重开即原地刷新）
            return
        if btn == "rebuild_index":
            try:
                self._store.rebuild_index()
                self.status("索引已重建。", "ok")
            except Exception as e:
                self.status(f"重建索引失败：{e}", "err")
            self.open_settings()
            return
        if btn == "toggle_tray":
            self.setCloseToTray(not self._close_to_tray)
            self.status("已开启：关闭窗口后隐藏到托盘"
                        if self._close_to_tray else "已关闭：关闭窗口即退出", "ok")
            self.open_settings()
            return
        if btn == "theme_switch":
            # M35 §4.3：主题分段控件点选即切换（item.key=theme 已把
            # "light"/"dark" 写进 valueMap；非法值退回现模式不变）
            mode = v.get("theme")
            if mode not in ("light", "dark"):
                mode = "light" if self._theme_mode == "dark" else "dark"
            self.setThemeMode(mode)
            self.open_settings()               # 重开（宿主单例，重开即原地刷新）
            return
        if btn == "export_backup":
            self.open_export_backup_dialog()
            return
        if btn == "change_dir":
            self.open_change_dir_dialog()
            return

    # ---- M17 任务9：导出备份（旧版 on_export_backup 平移，.pyw L10050-10067）----
    @Slot()
    def open_export_backup_dialog(self) -> None:
        default_zip = str(Path.home() / "Documents"
                          / f"井然备份_{time.strftime('%Y%m%d')}.zip")
        self.show_dialog({
            "title": "导出备份",
            "message": ("把整个版本库（含全部快照与配置）打包为一个 zip。\n"
                        "·只读导出，不影响当前库\n·目标文件已存在时会被覆盖"),
            "fields": [self._field("text", "destZip", "目标 zip 路径：",
                                   default_zip)],
            "buttons": [{"label": "导出", "key": "ok", "accent": True},
                        {"label": "取消", "key": "cancel"}],
        }, lambda v: self._export_backup_done(v))

    def _export_backup_done(self, v: dict) -> None:
        if v.get("__btn", "cancel") != "ok":
            self.open_settings()
            return
        dest = (v.get("destZip") or "").strip().strip('"')
        if not dest:
            self.status("未填写导出路径。", "err")
            self.open_settings()
            return
        try:
            out = self._store.export_backup(Path(dest))
            self.status(f"已导出备份：{out}", "ok")
        except Exception as e:
            self.status(f"导出备份失败：{e}", "err")
        self.open_settings()

    # ---- M17 任务9：更改版本库位置（旧版 _change_store_dir 平移，L10303）----
    # migrate_store_dir = 整库复制+校验+失败回滚+位置指针原子切换；
    # 铁律：旧库保留不删。
    @Slot()
    def open_change_dir_dialog(self) -> None:
        self.show_dialog({
            "title": "更改版本库位置",
            "message": ("把当前版本库完整迁移到新位置。\n"
                        "·整库复制并逐文件校验，失败自动回滚\n"
                        "·旧位置的原库保留不删，可随时迁回"),
            "fields": [self._field("text", "newDir", "新库目录：",
                                   str(self._store.store_dir))],
            "buttons": [{"label": "开始迁移", "key": "ok", "accent": True},
                        {"label": "取消", "key": "cancel"}],
        }, lambda v: self._change_dir_done(v))

    def _change_dir_done(self, v: dict) -> None:
        if v.get("__btn", "cancel") != "ok":
            self.open_settings()
            return
        new_dir = (v.get("newDir") or "").strip().strip('"')
        if not new_dir:
            self.status("未填写新库目录。", "err")
            self.open_settings()
            return
        # M64：整库复制改后台（原来在 UI 线程同步 copy，库大桥接假死）
        self._migrate_start(new_dir)

    # ---- M47：后台驻留（关闭隐藏到托盘）----
    @Slot(result=bool)
    def closeToTray(self) -> bool:
        return self._close_to_tray

    @Slot(bool)
    def setCloseToTray(self, on: bool) -> None:
        self._close_to_tray = bool(on)
        ui = self._store.config.get("ui", {}) or {}
        ui["closeToTray"] = self._close_to_tray
        self._store.config["ui"] = ui
        self._write_ui_config()

    @Slot()
    def notifyHidden(self) -> None:
        """QML 隐藏到托盘后调用 → main.py 弹托盘气泡。"""
        self.hiddenToTray.emit()

    @Slot(result=bool)
    def forceQuit(self) -> bool:
        return self._force_quit

    @Slot()
    def requestQuit(self) -> None:
        """托盘菜单「退出」：置标志后真正退出（绕过关闭即隐藏）。"""
        self._force_quit = True
        QGuiApplication.quit()

    @Slot(str)
    def setThemeMode(self, mode: str) -> None:
        if mode not in ("light", "dark"):
            return
        self._theme_mode = mode
        ui = self._store.config.get("ui", {}) or {}
        ui["theme"] = mode
        self._store.config["ui"] = ui
        self._write_ui_config()
        self.themeChanged.emit(mode)

    @Slot(result=str)
    def themeMode(self) -> str:
        return self._theme_mode

    # ---- F7：帮助（P1，M7 补齐）----
    @Slot()
    def open_help(self) -> None:
        """D2：帮助 + 数据说明。承诺必须写准——Diff 会按白名单读内容，
        所以不能说「绝不解析」，只能说「提交时不解析，唯一例外是文本对比」。

        M98：照着当前实现逐条核对，修掉三处**说错**的说明——
          1. 「左栏单击展开/折叠」：M76 起单击只选中，开合只认行首三角
          2. 「Del 删除」：QML 里根本没有 Del 键绑定，删除在右键菜单
          3. 「把版本卡片拖回中栏可另存」：没有这个落点，另存为在右键菜单
        另外补上版本号、栏宽拖动、右栏收纳、回收站这些用户实际会问的。
        """
        from app_version import BUILD_DATE, VERSION as APP_VER
        store_dir = str(self._store.store_dir)

        def done(v):
            if (v or {}).get("__btn") == "open":
                try:
                    os.startfile(store_dir)  # noqa: S606
                except OSError as e:
                    self.status("打开数据目录失败：%s" % e, "err")

        self.show_dialog({
            "title": "使用帮助与数据说明",
            "message": (
                "井然 %s　·　构建于 %s\n\n" % (APP_VER, BUILD_DATE)
                + "提交\n"
                "· 把文件或文件夹拖进窗口即提交；同一分类内不能重名，"
                "重名时可选择「续版本」\n"
                "· 也可以按 F1 或点顶栏右侧的提交按钮\n\n"
                "找文件\n"
                "· Ctrl+F 搜索（Ctrl+K 同效）\n"
                "· 左栏单击即选中该分类；点分类行左侧的小三角展开/收起子分类\n"
                "· 双击分类名可重命名，把文件拖到分类上即移动过去\n"
                "· 中栏单击选中，双击打开；Ctrl 多选、Shift 连选\n"
                "· 右键里还有导出分类、删除分类、列显示设置等\n"
                "· 回收站常驻左栏底部，删除的东西先落到那里，可随时还原\n\n"
                "看版本\n"
                "· 右栏是版本时间轴：单击星标格收藏，双击打开该版本\n"
                "· 右键版本卡片可「另存为…」，把任一版本导出成普通文件\n"
                "· 选中两个版本可以对比差异（文本按白名单行内对比）\n\n"
                "分享\n"
                "· 把版本卡片拖到微信 / 资源管理器 / SVN 即分享"
                "（临时副本 20 秒后自动清理）\n\n"
                "调整界面\n"
                "· 拖动三栏之间的分隔条即可改宽度，松手立刻记住\n"
                "· 顶栏最右依次是：右栏收纳 / 设置 / 帮助\n"
                "· 浅色与深色主题在「设置」里切换\n\n"
                "快捷键\n"
                "Ctrl+F 搜索 · F1 提交新版本 · F2 重命名 · F5 刷新 · "
                "Esc 逐级取消\n\n"
                "关于你的文件（重要）\n"
                "· 提交时只做字节级复制：不打开、不解析、不索引文件内容\n"
                "· 唯一的例外：你主动点「文本对比」时，才会按白名单读取这两个版本\n"
                "· 数据全部保存在本机当前用户目录下，不上传、不联网；"
                "卸载只删除程序，不动数据\n"
                "· 想找到数据目录，点下面的「打开数据目录」按钮即可\n"
                "· 换电脑或换用户时，数据不会跟着走——"
                "需要带走请用「设置 → 导出备份」"
            ),
            "buttons": [{"label": "打开数据目录", "key": "open"},
                        {"label": "关闭", "key": "ok", "accent": True}],
        }, done)

    # ---- F6：库迁移（后台线程 + 完成信号）----
    def _migrate_start(self, new_dir) -> None:
        if not new_dir:
            return
        self.status("正在迁移版本库（不中断、不覆盖原库）…", "info")
        import threading as _th

        def work():
            try:
                self._store.migrate_store_dir(new_dir)
                self.migrationDone.emit(json.dumps(
                    {"ok": True, "dir": str(new_dir)}))
            except (ValueError, OSError) as e:
                self.migrationDone.emit(json.dumps(
                    {"ok": False, "reason": str(e)}))

        _th.Thread(target=work, daemon=True).start()

    def _on_migration_done(self, payload: str) -> None:
        """M64：迁移结束（后台线程 emit）→ 刷新视图并提示。"""
        try:
            d = json.loads(payload)
        except ValueError:
            d = {"ok": False, "reason": "未知错误"}
        if d.get("ok"):
            self.reload_files()
            self.status(f"版本库已迁移到：{d.get('dir', '')}", "ok")
        else:
            self.status(f"迁移失败（原库未动）：{d.get('reason', '')}", "err")

    # ---- K3：F2 焦点分派（中栏文件 / 左栏分类；QML 传 focus 上下文）----
    @Slot(str, result=str)
    def hotkeyF2(self, focus: str) -> str:
        """K3（P0）：F2 焦点分派——左栏=重命名分类（内置拒绝），
        中栏=重命名文件（F3 弹窗）。"""
        if focus == "tree":
            # P2：@Slot(result=str) 必须回字符串——hotkeyRename 本身返回 JSON 串
            return self.hotkeyRename()
        fids = [f for f in self._selected_fids if not f.startswith("trash#")]
        if len(fids) != 1:
            self.status("重命名需要先选中一个文件", "info")
            return json.dumps({"ok": False, "reason": "selection"})
        meta = self._store.load_meta(fids[0])
        old = meta.get("name", "") if meta else ""
        self.ask_text(
            "重命名文件", "新文件名：", old,
            hint="名称里不能包含 \\ / : * ? \" < > |",
            ok_text="重命名",
            on_result=lambda new: self._rename_file_done(fids[0], new))
        return json.dumps({"ok": True})

    def _rename_file_done(self, fid: str, new) -> None:
        if not new:
            return
        try:
            self._store.rename_record(fid, new)
        except (ValueError, OSError) as e:
            self.status(str(e), "err")
            return
        self.reload_files(keep_selection=True)
        self.status(f"已重命名为「{new}」。", "ok")

    # ---- M85：版本拖到界面内 → 另存为文件 ----
    def _version_no(self, meta: dict, vid: str) -> int:
        """版本号（按时间升序，v1 = 最旧）——与右栏显示口径一致。"""
        versions = sorted(meta.get("versions", []),
                          key=lambda v: str(v.get("time") or ""))
        ids = [v.get("id") for v in versions]
        return ids.index(vid) + 1 if vid in ids else 0

    def _dest_label(self, dest: str) -> str:
        return "未分类" if not dest else (self._store.collection_name(dest) or "未分类")

    @Slot(str, str)
    def saveVersionAsFile(self, kind: str, cid: str) -> None:
        """版本卡片在界面内松手：kind="cid"（落在分类行）/ "list"（落在文件区）。"""
        vids = [v for v in self._selected_vids if not v.startswith("trash#")]
        meta = self._current_meta
        if not meta or not vids:
            self.status("另存为需要先选中一个版本", "info")
            return
        vid = vids[0]
        if kind == "cid" and cid:
            dest = cid
        else:
            cur = self._selected_collection
            dest = "" if cur in BUILTIN_CIDS else cur
        vno = self._version_no(meta, vid)
        stem, ext = os.path.splitext(meta.get("name") or "未命名")
        default = f"{stem}_v{vno}{ext}" if vno else f"{stem}_另存{ext}"
        self._save_as_ctx = {"vid": vid, "dest": dest, "vno": vno,
                             "default": default}
        self._ask_save_version_as()

    def _ask_save_version_as(self) -> None:
        ctx = self._save_as_ctx
        if not ctx:
            return
        self.ask_text(
            "另存为文件",
            "存到「%s」，文件名：" % self._dest_label(ctx["dest"]),
            ctx["default"],
            hint="名称里不能包含 \\ / : * ? \" < > |",
            ok_text="另存",
            on_result=self._save_version_as_done)

    def _save_version_as_done(self, new_name) -> None:
        ctx = self._save_as_ctx
        name = (new_name or "").strip()
        if not ctx or not name:
            return
        meta = self._store.load_meta(ctx.get("fid") or
                                     (self._current_meta or {}).get("fid", ""))
        if not meta:
            self.status("文件记录不存在", "err")
            return
        ver = next((v for v in meta.get("versions", [])
                    if v.get("id") == ctx["vid"]), None)
        if ver is None:
            self.status("版本不存在", "err")
            return
        try:
            src = self._store.version_file(meta, ver)
        except FileNotFoundError as e:
            self.status(str(e), "err")
            return
        tmpdir = Path(tempfile.mkdtemp(prefix="jingran_saveas_"))
        try:
            dst = tmpdir / name
            shutil.copyfile(src, dst)
            self._store.commit_new(str(dst), "从版本 v%d 另存" % ctx["vno"], "",
                                   ctx["dest"])
        except (ValueError, OSError) as e:
            self.status(str(e), "err")
            ctx["default"] = name
            self._ask_save_version_as()          # 重名 / 名字非法：原样回填让用户改
            return
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
        self._save_as_ctx = None
        self.reload_files(keep_selection=True)
        self.status("已另存为「%s」，在「%s」下" % (name, self._dest_label(ctx["dest"])),
                    "ok")

    # ---- K4：Esc 两级层级（QML 逐级调用；这里提供终级动作）----
    @Slot()
    def clearSelection(self) -> None:
        """K4 终级：清空中栏+右栏选择（生产 _on_hotkey_escape 口径）。"""
        self._selected_fids = []
        self._selected_vids = []
        self._current_meta = None
        self.render_versions()
        self._emit_detail()

    # ---- 分派点消费（M4/M5 占位全部转正）----
    @Slot(str, str)
    def fileMenuAction(self, key: str, fids_json: str) -> None:  # noqa: F811
        """F 组转正：move/delete 走弹窗；open 编辑会话（G1）。"""
        try:
            fids = list(json.loads(fids_json))
        except ValueError:
            fids = []
        if key == "copy":
            for fid in fids:
                self._store.copy_file(fid)
            self.status(f"已创建 {len(fids)} 个副本", "ok")
            self.reload_files(keep_selection=True)
        elif key == "save_as":
            self._file_save_as(fids)
        elif key == "open":
            if len(fids) == 1:
                self.setSelection(json.dumps(fids))
                self.openEditSession()
            else:
                self.status("打开需要单个文件", "info")
        elif key == "move":
            self.open_move_dialog(fids)
        elif key == "rename":
            if len(fids) == 1:
                self.hotkeyF2("files")
        elif key == "delete":
            self.open_delete_file_record(fids)

    def _file_save_as(self, fids: list) -> None:
        """M66：文件另存为——导出最新版本（与版本区「另存为」同语义）。"""
        metas = [self._store.load_meta(f) for f in fids]
        metas = [m for m in metas if m]
        if not metas:
            return

        def export(meta: dict, dest: Path) -> bool:
            latest = self._store.latest_version(meta)
            if latest is None:
                return False
            self._store.save_version_as(meta, latest, dest)
            return True

        if len(metas) == 1:
            m = metas[0]
            name = m.get("name") or "导出文件"

            def one(dest) -> None:
                if not dest:
                    return
                try:
                    if export(m, Path(dest)):
                        self.status(f"已另存为：{dest}", "ok")
                    else:
                        self.status("该文件没有任何版本可导出。", "err")
                except (ValueError, OSError) as e:
                    self.status(f"另存为失败：{e}", "err")

            self.ask_save_path("文件另存为", name, one)
            return

        def many(dest_dir) -> None:
            if not dest_dir:
                return
            ok_n, fails = 0, []
            for m in metas:
                name = m.get("name") or f"{m.get('fid')}.bin"
                out = Path(dest_dir) / name
                stem, suffix = Path(name).stem, Path(name).suffix
                n = 2
                while out.exists():
                    out = Path(dest_dir) / f"{stem} ({n}){suffix}"
                    n += 1
                try:
                    if export(m, out):
                        ok_n += 1
                except (ValueError, OSError) as e:
                    fails.append(f"{name}: {e}")
            if fails:
                self.status(f"已导出 {ok_n} 个，{len(fails)} 个失败：{fails[0]}",
                            "err")
            else:
                self.status(f"已导出 {ok_n} 个文件到：{dest_dir}", "ok")

        self.ask_directory("选择导出目录", many)

    def open_move_dialog(self, fids: list) -> None:
        """F3 移动到分类（on_move_to_category 平移）。"""
        opts, _ = self._col_options()
        self.show_dialog({
            "title": "移动到分类…",
            "message": f"将移动 {len(fids)} 个文件记录（不改磁盘文件）。",
            "fields": [self._field("combo", "category", "目标分类：", None,
                                   options=opts)],
            "buttons": [{"label": "移动", "key": "ok", "accent": True},
                        {"label": "取消", "key": "cancel"}],
        }, lambda v: self._move_dialog_done(fids, v))

    def _move_dialog_done(self, fids: list, v: dict) -> None:
        if v.get("__btn", "cancel") != "ok":
            return
        opts, _ = self._col_options()
        idx = v.get("category")
        cid = opts[idx]["cid"] if isinstance(idx, int) and 0 <= idx < len(opts) else None
        r = json.loads(self.fileTransfer(json.dumps(fids),
                                         cid if cid else "__unfiled__"))
        if r.get("conflicts"):
            # F4 三选弹窗（逐个处理第一个，其余保持记账）
            cf = r["conflicts"][0]
            src = self._store.load_meta(cf["srcFid"])
            dst = self._store.load_meta(cf["dstFid"])
            if src and dst:
                target = None if cid in (None, "__unfiled__") else cid
                self.open_transfer_conflict(src, target, dst)

    @Slot(str, str)
    def _restore_version(self, vid: str) -> None:
        """M50：把某个历史版本的内容恢复成「新版本」（不改写历史）。"""
        meta = self._current_meta
        if not meta:
            return
        ver = next((v for v in meta.get("versions", [])
                    if v.get("id") == vid), None)
        if ver is None:
            self.status("找不到该版本（可能已被删除）。", "err")
            return
        try:
            _i = meta["versions"].index(ver)
        except ValueError:
            _i = -1
        lab = ver.get("no") or (f"v{_i + 1}" if _i >= 0 else "该版本")
        self.show_dialog({
            "title": "回到此版本",
            "message": (f"把「{lab}」的内容恢复出来，作为这个文件的**新版本**。\n\n"
                        "·原有历史不会被改写或丢弃\n"
                        "·恢复后可以继续在这个版本上编辑提交"),
            "buttons": [{"label": "恢复为新版本", "key": "ok", "accent": True},
                        {"label": "取消", "key": "cancel"}],
        }, lambda v: self._restore_version_done(meta, ver, v))

    def _restore_version_done(self, meta: dict, ver: dict, v: dict) -> None:
        if v.get("__btn", "cancel") != "ok":
            return
        try:
            src = self._store.version_file(meta, ver)
            try:
                _i = meta["versions"].index(ver)
            except ValueError:
                _i = -1
            lab = ver.get("no") or (f"v{_i + 1}" if _i >= 0 else "旧版本")
            self._store.commit_next_version(
                meta["fid"], str(src), f"回到{lab}", "版本恢复")
            self.reload_files()
            self.status(f"已把「{lab}」恢复为新版本。", "ok")
        except Exception as e:  # noqa: BLE001
            self.status(f"恢复失败：{e}", "err")

    @Slot(str, str)
    def versionMenuAction(self, key: str, spec_json: str) -> None:  # noqa: F811
        """F 组转正：diff/save_as(另存为=save_version_as 需路径→F6 风格 ask)/
        edit_info(F9)/delete_version(F8)。

        ⚠️ `@Slot(str, str)` 不能丢：该函数历史上定义过两次（F811），后一次
        覆盖时漏了装饰器 → QML 调 controller.versionMenuAction(...) 直接报
        "is not a function"，表现为**版本区右键菜单点了毫无反应**（菜单本身
        能弹出，因为 versionMenuSpec 还带着 Slot）。
        """
        ev = json.loads(spec_json)
        if key == "restore_version":
            self._restore_version(ev.get("vid", ""))
        elif key == "diff":
            self.diffRequest(ev.get("vidA", ""), ev.get("vidB", ""))
        elif key == "save_as":
            self._version_save_as(ev.get("vid", ""))
        elif key == "edit_info":
            self.open_edit_version_info(ev.get("vid", ""))
        elif key == "delete_version":
            sel = [v for v in self._selected_vids
                   if not v.startswith("trash#")]
            if len(sel) > 1:
                self.show_dialog({
                    "title": "删除多个版本",
                    "message": (f"将把选中的 {len(sel)} 个版本移入回收站"
                                "（可在回收站还原）。"),
                    "buttons": [{"label": "删除", "key": "ok",
                                 "accent": True, "danger": True},
                                {"label": "取消", "key": "cancel"}],
                }, lambda v: self._delete_versions_batch(sel, v))
            else:
                self.open_delete_version(ev.get("vid", ""))

    def _delete_versions_batch(self, vids: list, v: dict) -> None:
        if v.get("__btn", "cancel") != "ok":
            return
        meta = self._current_meta
        if not meta:
            return
        ok_n, fails = 0, []
        for vid in vids:
            try:
                ok, msg = self._store.delete_version(meta["fid"], vid)
                if ok:
                    ok_n += 1
                else:
                    fails.append(msg)
            except (ValueError, OSError) as e:
                fails.append(str(e))
        self._selected_vids = [x for x in self._selected_vids
                               if x not in set(vids)]
        self.reload_files(keep_selection=True)
        if fails:
            self.status(f"已删除 {ok_n} 个，{len(fails)} 个失败：{fails[0]}",
                        "err")
        else:
            self.status(f"已删除 {ok_n} 个版本（可在回收站还原）。", "ok")

    def _version_save_as(self, vid: str) -> None:
        """M66：版本另存为——单选用保存对话框；多选先选目录再逐个导出。"""
        meta = self._current_meta
        if not meta:
            return
        chrono = sorted(meta.get("versions", []),
                        key=lambda v: str(v.get("time") or ""))
        sel = [v for v in self._selected_vids
               if not v.startswith("trash#")] or [vid]
        vers = [v for v in chrono if v.get("id") in sel]
        if not vers:
            self.status("找不到要另存的版本。", "err")
            return
        stem = Path(meta.get("name") or "版本").stem
        suffix = Path(meta.get("name") or "").suffix

        def tag(v) -> str:
            try:
                return f"v{chrono.index(v) + 1}"
            except ValueError:
                return "v"

        if len(vers) == 1:
            v = vers[0]
            self.ask_save_path(
                "版本另存为", f"{stem}_{tag(v)}{suffix}",
                lambda dest: self._save_as_done(meta, v.get("id"), dest))
            return

        def run(dest_dir) -> None:
            if not dest_dir:
                return
            ok_n, fails = 0, []
            for v in vers:
                out = Path(dest_dir) / f"{stem}_{tag(v)}{suffix}"
                n = 2
                while out.exists():
                    out = Path(dest_dir) / f"{stem}_{tag(v)} ({n}){suffix}"
                    n += 1
                try:
                    self._store.save_version_as(meta, v, out)
                    ok_n += 1
                except (ValueError, OSError) as e:
                    fails.append(f"{out.name}: {e}")
            if fails:
                self.status(f"已导出 {ok_n} 个，{len(fails)} 个失败：{fails[0]}",
                            "err")
            else:
                self.status(f"已导出 {ok_n} 个版本到：{dest_dir}", "ok")

        self.ask_directory("选择导出目录", run)

    def _save_as_done(self, meta, vid: str, dest) -> None:
        if not dest:
            return
        ver = next((v for v in meta.get("versions", [])
                    if v.get("id") == vid), None)
        if ver is None:
            return
        try:
            out = self._store.save_version_as(meta, ver, Path(dest))
            self.status(f"已另存为：{out}", "ok")
        except (ValueError, OSError) as e:
            self.status(f"另存为失败：{e}", "err")

    @Slot(str)
    def onEditSaveAsk(self, ask_json: str) -> None:
        """M5 editSaveAsk 信号 → F 组三选弹窗（占位消费完毕）。"""
        self.open_edit_save_ask(json.loads(ask_json))

    @Slot(str)
    def onCloseRejected(self, pending_json: str) -> None:
        """M5 closeRejected 信号 → 批量处理弹窗（占位消费完毕）。"""
        self.open_pending_edits_dialog(json.loads(pending_json))

    @Slot()
    def replayOrphans(self) -> None:
        """G4：QML 就绪后补放孤儿清理弹窗（init 期 emit 无监听者）。"""
        for o in list(self._orphan_queue):
            key = o.get("key") or f"{o.get('fid')}|{o.get('ver_id')}"
            sess = self._edit_sessions.sessions.get(key, o)
            self.open_orphan_session(key, sess)
        self._orphan_queue = []

    @Slot(str)
    def orphanResolve(self, req_json: str) -> None:
        """G4：restore 产生的孤儿 → 弹窗清理语义（生产 _handle_orphan_session）。"""
        req = json.loads(req_json)
        self.open_orphan_session(req["key"], req["session"])

    # ---------------- 状态栏 / 定时器 ----------------
    @Slot(result=int)
    def rowCount(self) -> int:
        return self._model.rowCount()

    @Slot()
    def refreshStatus(self) -> None:
        self._emit_status_fit()

    def _after(self, delay_ms: int, fn):
        t = QTimer(self)
        t.setSingleShot(True)
        t.timeout.connect(fn)
        t.start(delay_ms)
        self._timers.append(t)
        # M65：只保留最近 32 个，老的停掉并丢弃（原来只增不减）
        while len(self._timers) > 32:
            old = self._timers.pop(0)
            try:
                old.stop()
                old.deleteLater()
            except RuntimeError:
                pass
        return t

    @property
    def share(self) -> ShareSessions:
        return self._share
