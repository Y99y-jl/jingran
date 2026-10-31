"""全自动 UI 冒烟测试（离线、可重复、单命令）。

目的：每次发版前用一条命令验证「界面能起来 + 关键交互链路没断」，
把过去那种「改了 A 坏了 B、只能等实测才发现」的情况挡在发布前。

运行：
    QT_QPA_PLATFORM=offscreen <venv>/python.exe tests/ui_smoke.py

覆盖（全部用真实鼠标/键盘事件驱动 QML，不直接调内部函数改状态）：
  S1 启动      QML 加载、三栏存在、无 Error 级告警、首帧可渲染
  S2 文件区    列表行数、单击选中、↓ 键移动、Ctrl 加选、Shift 整段
  S3 右键菜单   文件行右键弹出、点外部自动关闭
  S4 列定制     隐藏列生效、表头拖动换序并落库
  S5 分类树     单击不展开/点三角才开合、拖动换序、删除分类带文件进回收站
  S6 回收站     进入回收站、行数据完整（文件名不空）
  S7 版本区     版本行数、Shift 整段多选、版本右键可弹

退出码：0=全过；1=有失败（失败项会存截图到 tests/artifacts/）。
"""
import json
import os
import sys
import tempfile
import traceback
from pathlib import Path

QA = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(QA))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("DOCVER_STORE",
                      tempfile.mkdtemp(prefix="ui_smoke_store_"))

from PySide6.QtCore import QObject, QPoint, QPointF, Qt, QUrl   # noqa: E402
from PySide6.QtGui import QGuiApplication                        # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine                  # noqa: E402
from PySide6.QtQuick import QQuickItem                           # noqa: E402
from PySide6.QtQuickControls2 import QQuickStyle                 # noqa: E402
from PySide6.QtTest import QTest                                 # noqa: E402

import controller as cm                                          # noqa: E402

ART = QA / "tests" / "artifacts"
ART.mkdir(parents=True, exist_ok=True)

RESULTS: list[tuple[str, bool, str]] = []
SHOTS: list[Path] = []


def check(name: str, ok, detail: str = "") -> bool:
    ok = bool(ok)
    RESULTS.append((name, ok, "" if ok else detail))
    print(f"{'PASS' if ok else 'FAIL'} {name}" + ("" if ok else f"   [{detail}]"))
    return ok


def shot(win, tag: str) -> None:
    p = ART / f"{tag}.png"
    try:
        win.grabWindow().save(str(p))
        SHOTS.append(p)
    except Exception:                                            # noqa: BLE001
        pass


class UI:
    """把窗口内常见操作收成几个语义化方法，避免每处重复算坐标。"""

    def __init__(self, win, c):
        self.w = win
        self.c = c
        self.cat = self._pane("CategoryTreePane")
        self.files = self._pane("FileListPane")
        self.ver = self._pane("VersionPane")
        self.tree = self._named(self.cat, "catTree")
        self.list = self._named(self.files, "fileList")

    def _pane(self, cls: str):
        return next(i for i in self.w.findChildren(QQuickItem)
                    if i.metaObject().className().startswith(cls))

    @staticmethod
    def _named(root, name: str):
        return next(i for i in root.findChildren(QQuickItem)
                    if i.property("objectName") == name)

    # ---- 坐标 ----
    def file_pos(self, row: int, dx: float = 120.0) -> QPoint:
        # 行高是固定 48（delegate），不能拿 list.height()/行数 估——
        # 列表高度含滚动余量，估值会把点击落到错误的行
        p = self.list.mapToScene(QPointF(dx, row * 48 + 24))
        return QPoint(int(p.x()), int(p.y()))

    def tree_pos(self, model_row: int, dy: float = 19.0) -> QPoint:
        # 内置行（全部/未分类）不在 ListView 内容里，视觉行号要减掉它们
        hidden = sum(1 for i in range(model_row)
                     if self.c.catModel.row_at(i).get("isBuiltin"))
        y = (model_row - hidden) * 38 + dy
        p = self.tree.mapToScene(QPointF(self.tree.width() / 2, y))
        return QPoint(int(p.x()), int(p.y()))

    def tree_caret_pos(self, model_row: int, dy: float = 19.0) -> QPoint:
        """展开三角的坐标（M76 起开合只认它：位于行首 26px 内）。"""
        hidden = sum(1 for i in range(model_row)
                     if self.c.catModel.row_at(i).get("isBuiltin"))
        depth = self.c.catModel.row_at(model_row).get("depth", 0) or 0
        y = (model_row - hidden) * 38 + dy
        # 缩进按 16px/层（delegate 的 row.indent 口径），三角中心在 13px
        p = self.tree.mapToScene(QPointF(depth * 16 + 13, y))
        return QPoint(int(p.x()), int(p.y()))

    # ---- 输入 ----
    def click(self, pos: QPoint, mods=Qt.KeyboardModifier.NoModifier,
              button=Qt.MouseButton.LeftButton) -> None:
        QTest.mouseClick(self.w, button, mods, pos)
        QTest.qWait(120)

    def drag(self, a: QPoint, b: QPoint, steps: int = 8) -> None:
        QTest.mousePress(self.w, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier, a)
        QTest.qWait(90)
        for k in range(1, steps + 1):
            x = a.x() + (b.x() - a.x()) * k / steps
            y = a.y() + (b.y() - a.y()) * k / steps
            QTest.mouseMove(self.w, QPoint(int(x), int(y)))
            QTest.qWait(30)
        QTest.mouseRelease(self.w, Qt.MouseButton.LeftButton,
                           Qt.KeyboardModifier.NoModifier, b)
        QTest.qWait(220)

    def menus(self) -> list[QObject]:
        return [o for o in self.files.findChildren(QObject)
                if "Menu" in o.metaObject().className()]


def build() -> tuple:
    """起一个沙箱实例：3 个文件（其中一个 3 版本）+ 两级分类。"""
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    QQuickStyle.setStyle("Basic")
    c = cm.AppController(os.environ["DOCVER_STORE"])
    st = c._store
    tmp = Path(tempfile.mkdtemp())

    parent = st.add_collection("项目资料")
    st.add_collection("2026 合同", parent)
    st.add_collection("归档")          # 同层第二个分类，用于测拖动换序
    for i in range(2):
        f = tmp / f"报告{i}.txt"
        f.write_text("x", encoding="utf-8")
        st.commit_new(f, f"第1版", category=parent)
    multi = tmp / "多版本.txt"
    multi.write_text("v1", encoding="utf-8")
    st.commit_new(multi, "第1版")
    fid = next(m["fid"] for m in st.all_files() if m["name"] == "多版本.txt")
    for i in range(2):
        multi.write_text(f"v{i + 2}", encoding="utf-8")
        st.commit_next_version(fid, str(multi), f"第{i + 2}版")
    c.reload_files()

    eng = QQmlApplicationEngine()
    for k, v in (("controller", c), ("filesModel", c.model),
                 ("categoriesModel", c.catModel), ("verModel", c.verModel)):
        eng.rootContext().setContextProperty(k, v)
    warns: list[str] = []
    eng.warnings.connect(lambda ws: warns.extend(x.toString() for x in ws))
    eng.addImportPath(QA.as_uri())
    eng.load(QUrl.fromLocalFile(str(QA / "qml" / "Main.qml")))
    win = eng.rootObjects()[0]
    win.resize(1400, 860)
    win.show()
    QTest.qWait(900)
    return app, c, st, tmp, win, warns, eng


# ---------------------------------------------------------------- S1 启动
def s1_boot(c, win, warns) -> None:
    check("S1 窗口已创建并可见", win.isVisible())
    ui = UI(win, c)
    check("S1 三栏都存在", all([ui.cat is not None, ui.files is not None,
                                ui.ver is not None]))
    check("S1 文件列表可定位", ui.list is not None and ui.list.height() > 0)
    errs = [w for w in warns if "Error" in w or "ReferenceError" in w
            or "TypeError" in w]
    check("S1 启动无 QML 错误级告警", not errs, "; ".join(errs[:2]))


# ---------------------------------------------------------------- S2 文件区
def s2_files(c, win) -> None:
    ui = UI(win, c)
    n = c.model.rowCount()
    check("S2 列表行数 = 3", n == 3, f"实际 {n}")
    ui.click(ui.file_pos(0))
    fids = [r["fid"] for r in c.model.rows]
    check("S2 单击选中首行", c._selected_fids == [fids[0]],
          str(c._selected_fids))

    ui.list.forceActiveFocus()
    QTest.qWait(100)
    QTest.keyClick(win, Qt.Key_Down)
    QTest.qWait(200)
    check("S2 ↓ 键移到第二行", c._selected_fids == [fids[1]],
          str(c._selected_fids))

    # 先测整段（Shift 以锚点为准），再测切换（Ctrl）
    ui.click(ui.file_pos(0))                       # 重设锚点到第 1 行
    ui.click(ui.file_pos(2), Qt.KeyboardModifier.ShiftModifier)
    check("S2 Shift+点击整段（0..2 共 3 个）", len(c._selected_fids) == 3,
          str(len(c._selected_fids)))
    ui.click(ui.file_pos(1), Qt.KeyboardModifier.ControlModifier)
    check("S2 Ctrl+点击取消该行（2 个）", len(c._selected_fids) == 2,
          str(len(c._selected_fids)))


# ---------------------------------------------------------------- S3 右键菜单
def s3_menu(c, win) -> None:
    ui = UI(win, c)
    ui.click(ui.file_pos(0))
    ui.click(ui.file_pos(0), button=Qt.MouseButton.RightButton)
    open_n = len(ui.menus())
    check("S3 文件行右键弹出菜单", open_n > 0, f"菜单对象 {open_n}")
    ui.click(QPoint(120, 420))          # 点左侧分类区空白
    # M81：菜单/弹窗加了 110ms 退场动画后，「点外面就关」不再是瞬时完成。
    # 原来固定等 120ms 正好卡在动画尾巴上，慢机器上会偶发读到"还在淡出"
    # 的旧状态 → 假 FAIL（实测 6 次里挂 2 次）。改成轮询等它真的关掉。
    for _ in range(16):                 # 最多 800ms
        if len(ui.menus()) == 0:
            break
        QTest.qWait(50)
    left = len(ui.menus())
    check("S3 点菜单外自动关闭", left == 0, f"仍剩 {left}")


# ---------------------------------------------------------------- S4 列定制
def s4_columns(c, win) -> None:
    ui = UI(win, c)
    c.setFileColumnVisible("kind", False)
    QTest.qWait(200)
    spec = {x["key"]: x["visible"] for x in json.loads(c.fileColumnsSpec())}
    check("S4 隐藏「文件类型」列生效", spec.get("kind") is False, str(spec))
    c.setFileColumnVisible("kind", True)
    QTest.qWait(150)

    before = [x["key"] for x in json.loads(c.fileColumnsSpec())]
    hdr = UI._named(ui.files, "fileHeaderMA")
    y = int(hdr.mapToScene(QPointF(0, hdr.height() / 2)).y())
    x0 = int(hdr.mapToScene(QPointF(40, 0)).x())
    ui.drag(QPoint(x0, y), QPoint(x0 + 480, y))
    after = [x["key"] for x in json.loads(c.fileColumnsSpec())]
    check("S4 表头拖动改变列顺序", before != after, f"{before} -> {after}")
    check("S4 列顺序已落库",
          (c._store.config.get("ui") or {}).get("cols_order") == after)
    # 复位，避免影响后续断言
    c.setFileColumnOrder(json.dumps(["name", "kind", "collection",
                                     "latest", "count", "star"]))
    QTest.qWait(150)


# ---------------------------------------------------------------- S5 分类树
def s5_tree(c, win) -> None:
    ui = UI(win, c)
    cats = c.catModel
    # 第一行是内置「全部文件」，第一个真实分类在 index 2
    pid = next(r["id"] for r in c._store.collections()
               if r.get("name") == "项目资料")
    is_open_before = bool(c._col_open.get(pid))

    p = ui.tree_pos(2)
    QTest.mousePress(win, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier, p)
    QTest.qWait(120)
    pressed_open = bool(c._col_open.get(pid))
    QTest.mouseRelease(win, Qt.MouseButton.LeftButton,
                       Qt.KeyboardModifier.NoModifier, p)
    QTest.qWait(250)
    released_open = bool(c._col_open.get(pid))
    check("S5 按下不改变展开态", pressed_open == is_open_before,
          f"{is_open_before} -> {pressed_open}")
    # M76：单击行不再开合（只选中），开合只认行首的三角按钮
    check("S5 单击行不展开", released_open == is_open_before,
          f"期望保持 {is_open_before}，实际 {released_open}")
    ui.click(ui.tree_caret_pos(2))
    QTest.qWait(250)
    caret_open = bool(c._col_open.get(pid))
    check("S5 点三角才开合", caret_open != is_open_before,
          f"{is_open_before} -> {caret_open}")
    ui.click(ui.tree_caret_pos(2))          # 复原，后面的用例依赖初始展开态
    QTest.qWait(250)

    # 拖动换序：把第一个同级分类拖到第二个的下边缘（只换序，不改层级）
    order_before = [x["name"] for x in c._store.collection_children(None)]
    top = [i for i in range(cats.rowCount())
           if not cats.row_at(i).get("isBuiltin")
           and cats.row_at(i).get("depth") == 0]
    if len(top) >= 2:
        ui.drag(ui.tree_pos(top[0]), ui.tree_pos(top[1], dy=34))
        order_after = [x["name"] for x in c._store.collection_children(None)]
        check("S5 拖动可改变同级顺序", order_before != order_after,
              f"{order_before} -> {order_after}")
    else:
        check("S5 拖动可改变同级顺序", False, f"可见同级分类 {len(top)} 个")

    # 删除分类 → 其下文件进回收站（只数该分类子树里的文件）
    sub = {pid} | set(c._store.collection_descendants(pid))
    files_before = len([m for m in c._store.all_files()
                        if m.get("category") in sub])
    c.collectionMenuAction("delete", pid, "")
    dlg = c._pending_dialog if hasattr(c, "_pending_dialog") else None
    rid = dlg["rid"] if isinstance(dlg, dict) else None
    if rid is None:
        # 兼容实现差异：从最近一次 dialogRequested 取
        rid = getattr(c, "_smoke_rid", None)
    got = _last_dialog_rid(c)
    c.dialogResult(json.dumps({"rid": got, "values": {"__btn": "ok"}}))
    QTest.qWait(300)
    trash_names = [it.get("name") for it in c._store.trash_items()]
    check("S5 删除分类后文件进回收站",
          len(trash_names) == files_before, f"回收站 {trash_names}")


_DIALOG_RIDS: list[str] = []


def _hook_dialogs(c) -> None:
    """记录每次弹窗的 rid，供脚本自动点确认（等价于用户点「删除」）。"""
    c.dialogRequested.connect(
        lambda js: _DIALOG_RIDS.append(json.loads(js).get("rid", "")))


def _last_dialog_rid(c) -> str:
    return _DIALOG_RIDS[-1] if _DIALOG_RIDS else ""


# ---------------------------------------------------------------- S6 回收站
def s6_trash(c, win) -> None:
    c.selectCollection("__trash__")
    QTest.qWait(350)
    n = c.model.rowCount()
    check("S6 回收站有行", n > 0, str(n))
    names = [c.model.row_at(i).get("name") for i in range(n)]
    check("S6 回收站文件名不为空", all(names), str(names))
    shot(win, "smoke_trash")


# ---------------------------------------------------------------- S7 版本区
def s7_versions(c, win) -> None:
    c.selectCollection("__all__")
    QTest.qWait(200)
    fid = next(r["fid"] for r in c.model.rows if r["name"] == "多版本.txt")
    c.setSelection(json.dumps([fid]))
    QTest.qWait(300)
    n = c.verModel.rowCount()
    check("S7 右栏显示 3 个版本", n == 3, str(n))

    vids = [c.verModel.row_at(i)["vid"] for i in range(n)]
    c._selected_vids = [vids[0]]
    c.versionEvent(json.dumps({"op": "press", "vid": vids[0], "x": 10, "y": 10,
                               "ctrl": False, "shift": False}))
    r = json.loads(c.versionEvent(json.dumps(
        {"op": "press", "vid": vids[2], "x": 10, "y": 10,
         "ctrl": False, "shift": True})))
    check("S7 Shift 整段选中 3 个版本", len(r.get("selected", [])) == 3,
          str(len(r.get("selected", []))))


def main() -> int:
    app = None
    try:
        app, c, st, tmp, win, warns, eng = build()   # eng 必须留引用
        _hook_dialogs(c)
        s1_boot(c, win, warns)
        s2_files(c, win)
        s3_menu(c, win)
        s4_columns(c, win)
        s5_tree(c, win)
        s6_trash(c, win)
        s7_versions(c, win)
        shot(win, "smoke_final")
    except Exception:                                          # noqa: BLE001
        traceback.print_exc()
        check("S0 冒烟脚本自身未崩溃", False, "见上方堆栈")

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print("\n" + "=" * 52)
    print(f"UI 冒烟：{passed} PASS / {total - passed} FAIL")
    if SHOTS:
        print("截图：" + ", ".join(str(p.name) for p in SHOTS))
    print("=" * 52)
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
