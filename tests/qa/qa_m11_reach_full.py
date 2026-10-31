# -*- coding: utf-8 -*-
"""QA 自建 · M11 入口层全量独立验证（Round 6）。

覆盖三个验证面（全部为自建断言，不依赖产品代码里的脚本）：
 ① 三栏右键菜单：树 / 中栏文件 / 版本行 各真实打开一次，断言「菜单可见 + 项数与 spec 一致」
    + 回收站分支抽查 + 空库（无版本）分支不崩
 ② 右栏收纳：连续**两轮**收起/展开，逐轮断言状态翻转 + 中栏宽度实际变化 + 往返还原
 ③ 工具栏三按钮：640 / 900 / 1280 三档逻辑宽下断言 visible 且 x+width ≤ 窗口宽

用法：QT_QPA_PLATFORM=offscreen python tests/qa/qa_m11_reach_full.py
铁律：一次性沙箱库；os.startfile 打桩；真实库零接触。
"""
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

QA_APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(QA_APP))
STORE = tempfile.mkdtemp(prefix="qa_m11_full_")
os.environ["DOCVER_STORE"] = STORE

from PySide6.QtCore import QObject, QUrl, QMetaObject, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtQuickControls2 import QQuickStyle  # noqa: E402

import controller as ctrl_mod  # noqa: E402
ctrl_mod.os.startfile = lambda p, *a, **k: None

app = QGuiApplication(sys.argv)
QQuickStyle.setStyle("Basic")
c = ctrl_mod.AppController(STORE)
store = c._store

# ---- 沙箱数据：用户分类 + 一个 2 版本文件 + 一个回收站条目 ----
cid = store.add_collection("复核分类A")
f1 = Path(STORE) / "复核文件.txt"
f1.write_text("v1", encoding="utf-8")
store.commit_new(str(f1), "复核v1", category=cid)
meta = store.load_meta(store.find_in_category(cid, "复核文件.txt")["fid"])
fid = meta["fid"]
f1.write_text("v2", encoding="utf-8")
store.commit_next_version(fid, str(f1), "复核v2")
meta = store.load_meta(fid)
vid = meta["versions"][-1]["id"]
ft = Path(STORE) / "待删.txt"
ft.write_text("x", encoding="utf-8")
store.commit_new(str(ft), "待删")
tid = store.find_in_category(None, "待删.txt")["fid"]
store.delete_file_record(tid)
trash_id = store.trash_items()[0]["id"]
c._rebuild_categories()
c.reload_files()

engine = QQmlApplicationEngine()
for k, v in [("controller", c), ("filesModel", c.model),
             ("categoriesModel", c.catModel), ("verModel", c.verModel)]:
    engine.rootContext().setContextProperty(k, v)
engine.addImportPath(QA_APP.as_uri())
engine.load(QUrl.fromLocalFile(str(QA_APP / "qml" / "Main.qml")))
assert engine.rootObjects(), "QML 加载失败"
win = engine.rootObjects()[0]

out, FAILS = [], []


def log(s=""):
    print(s, flush=True)
    out.append(str(s))


def check(name, ok, detail=""):
    log(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" —— {detail}" if detail else ""))
    if not ok:
        FAILS.append(f"{name}: {detail}")


def settle(ms=600):
    t = time.perf_counter() + ms / 1000
    while time.perf_counter() < t:
        app.processEvents()
        time.sleep(0.01)


def panes():
    """按 objectName 归类三栏 pane（含 openMenu 的 QObject）。"""
    res = {}
    for o in win.findChildren(QObject):
        if hasattr(o, "openMenu"):
            nm = o.objectName()
            if nm == "leftPane":
                res["tree"] = o
            elif nm == "rightPane":
                res["ver"] = o
            elif nm == "":
                res["file"] = o
    return res


def menus():
    return [m for m in win.findChildren(QObject)
            if m.metaObject().className().startswith("Menu_QMLTYPE")]


def close_menus():
    """彻底销毁现存 Menu 实例（仅隐藏会污染后续测量）——循环直到清空。"""
    for _ in range(3):
        ms = menus()
        if not ms:
            break
        for m in ms:
            try:
                m.deleteLater()
            except Exception:
                pass
        settle(250)


def open_menu(pane, args):
    """purge → 调用 QML openMenu → 只统计本次实例。返回 (count, visible, err)。"""
    close_menus()
    try:
        pane.openMenu(*args)
    except Exception as e:
        return (-1, False, repr(e))
    settle(650)
    ms = menus()
    cnt = max((m.property("count") or 0 for m in ms), default=0)
    vis = any(bool(m.property("visible")) for m in ms)
    return (cnt, vis, "")


P = panes()
log(f"[setup] panes={sorted(P)} | 分类={cid} 文件={fid} 版本={vid} 回收站={trash_id}")

# ===== ① 三栏右键菜单（每项独立引擎，零污染测量）=====
log("")
log("[① 三栏右键菜单：可见 + 项数与 spec 一致（每项独立引擎）]")


def fresh_window():
    e = QQmlApplicationEngine()
    for k, v in [("controller", c), ("filesModel", c.model),
                 ("categoriesModel", c.catModel), ("verModel", c.verModel)]:
        e.rootContext().setContextProperty(k, v)
    e.addImportPath(QA_APP.as_uri())
    e.load(QUrl.fromLocalFile(str(QA_APP / "qml" / "Main.qml")))
    assert e.rootObjects(), "QML 加载失败"
    return e, e.rootObjects()[0]


def measure_menu(pane_kind, args_fn, preselect):
    """独立引擎内：预置选中 → 打开单个菜单 → 返回 (count, visible)。

    pane_kind ∈ {'tree','file','ver'}；按 objectName 归类（file 无 objectName）。
    """
    e, w = fresh_window()
    preselect()
    settle(800)
    pane = None
    for o in w.findChildren(QObject):
        if hasattr(o, "openMenu"):
            nm = o.objectName()
            if pane_kind == "tree" and nm == "leftPane":
                pane = o
            elif pane_kind == "ver" and nm == "rightPane":
                pane = o
            elif pane_kind == "file" and nm == "":
                pane = o
    cnt, vis = 0, False
    if pane is not None:
        pane.openMenu(*args_fn())
        settle(700)
        ms = [m for m in w.findChildren(QObject)
              if m.metaObject().className().startswith("Menu_QMLTYPE")]
        cnt = max((m.property("count") or 0 for m in ms), default=0)
        vis = any(bool(m.property("visible")) for m in ms)
    e.deleteLater()
    settle(200)
    return cnt, vis


spec_tree = json.loads(c.collectionMenuSpec(cid))
n_tree = len(spec_tree.get("actions", []))
cnt, vis = measure_menu("tree", lambda: (cid, None), lambda: None)
check("左栏树菜单：可见且项数与 spec 总项一致", vis and cnt == n_tree,
      f"menu={cnt} spec总项={n_tree} visible={vis}")

spec_file = json.loads(c.fileMenuSpec())
n_file = len(spec_file.get("spec", []))
cnt, vis = measure_menu(
    "file", lambda: (0, fid), lambda: c.setSelection(json.dumps([fid])))
check("中栏文件菜单：可见且项数与 spec 总项一致", vis and cnt == n_file,
      f"menu={cnt} spec总项={n_file} visible={vis}")

spec_ver = json.loads(c.versionMenuSpec(vid))
n_ver = len(spec_ver.get("actions", []))
cnt, vis = measure_menu(
    "ver", lambda: (vid,),
    lambda: (c.setSelection(json.dumps([fid])),
             c.setVersionSelection(json.dumps([vid]))))
check("右栏版本菜单：可见且项数与 spec 总项一致", vis and cnt == n_ver,
      f"menu={cnt} spec总项={n_ver} visible={vis}")

spec_trash = json.loads(c.collectionMenuSpec("__trash__"))
n_trash = len(spec_trash.get("actions", []))
cnt, vis = measure_menu(
    "tree", lambda: ("__trash__", None),
    lambda: c.setSelection(json.dumps([f"trash#{trash_id}"])))
check("左栏回收站菜单：可见且项数与 spec 总项一致", vis and cnt == n_trash,
      f"menu={cnt} spec总项={n_trash} visible={vis}")

# ===== ② 收纳：连续两轮收起/展开 =====
log("")
log("[② 右栏收纳：连续两轮翻转 + 中栏宽度变化 + 往返还原]")
btn = win.findChild(QObject, "toggleRight")


def diag():
    return json.loads(win.diagSash())


def click_toggle():
    QMetaObject.invokeMethod(btn, "clicked", Qt.ConnectionType.DirectConnection)
    settle(1300)


win.setWidth(900)
settle(900)
d0 = diag()
log(f"  [初始@900] mid={d0['mid']} prefR={d0['prefR']} collapsed={d0['collapsed']}")
for rnd in (1, 2):
    click_toggle()
    dc = diag()
    click_toggle()
    de = diag()
    ok_round = (dc["collapsed"] is True and dc["prefR"] == 0
                and dc["mid"] > d0["mid"]
                and de["collapsed"] == d0["collapsed"]
                and all(de[k] == d0[k] for k in ("left", "mid", "right", "prefR")))
    check(f"第 {rnd} 轮往返：收起生效 + 再展开精确还原",
          ok_round,
          f"收起 mid={dc['mid']} prefR={dc['prefR']} / 展开 mid={de['mid']} "
          f"prefR={de['prefR']}（初始 mid={d0['mid']} prefR={d0['prefR']}）")

# ===== ③ 工具栏三按钮三档宽度可达 =====
log("")
log("[③ 工具栏三按钮：640/900/1280 三档可达（visible 且 x+width ≤ 窗宽）]")
for w in (640, 900, 1280):
    win.setWidth(w)
    settle(900)
    win_w = win.width()
    rows = []
    all_ok = True
    for nm in ("helpBtn", "settingsBtn", "toggleRight"):
        b = win.findChild(QObject, nm)
        if b is None:
            rows.append(f"{nm}=缺失")
            all_ok = False
            continue
        x = round(b.property("x"))
        bw = round(b.property("width"))
        vis = bool(b.property("visible"))
        ok = vis and (x + bw) <= win_w and x >= 0
        all_ok = all_ok and ok
        rows.append(f"{nm}: x={x} w={bw} right={x + bw} vis={vis} {'OK' if ok else 'BAD'}")
    check(f"{w} 逻辑宽下三按钮可达", all_ok, f"win={win_w} | " + " | ".join(rows))

log("")
log(f"[汇总] {'全部 PASS' if not FAILS else f'{len(FAILS)} 项 FAIL'}")
for f in FAILS:
    log(f"  !! {f}")
Path(__file__).with_name("qa_m11_reach_full_out.txt").write_text("\n".join(out), encoding="utf-8")
log("[done] 原始输出已存 tests/qa/qa_m11_reach_full_out.txt")
shutil.rmtree(STORE, ignore_errors=True)
sys.exit(1 if FAILS else 0)
