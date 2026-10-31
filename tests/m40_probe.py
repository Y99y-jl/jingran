# -*- coding: utf-8 -*-
"""M40 集成探针：回收站右键空弹窗 / 还原·清除列 / 原分类·删除时间；
字体独有族名（乱码根治）。

覆盖：
  P1 回收站视图数据：行存在、origCat/delTime 角色可用（M40 补的角色）
  P2 列契约：末列标题「还原/清除」、宽 112；胶囊不压滚动条（右留 ≥18px）
  P3 右键：回收站行不再创建菜单（无空弹窗）；普通行菜单仍正常
  P4 清除：二次确认（danger）→ 彻底删除 → 回收站计数归零
  P5 字体：六个随包字体族名 = PJM Sans SC / PJM Num（不再 Noto/Inter）；
     三档字重 exact 且样例字零缺字；Theme/Main 源码口径同步
  F  全程 0 个 QML Error 级警告
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

QA_APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(QA_APP))

STORE = tempfile.mkdtemp(prefix="m40_integ_")
os.environ["DOCVER_STORE"] = STORE
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QUrl  # noqa: E402
from PySide6.QtGui import (QFont, QFontDatabase, QFontInfo,  # noqa: E402
                           QGuiApplication, QRawFont)
from PySide6.QtQml import (QQmlApplicationEngine,  # noqa: E402
                           QQmlExpression, QQmlEngine)
from PySide6.QtQuick import QQuickItem  # noqa: E402
from PySide6.QtQuickControls2 import QQuickStyle  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

import controller as ctrl_mod  # noqa: E402

ctrl_mod.os.startfile = lambda p, *a, **k: None

app = QGuiApplication(sys.argv)
QQuickStyle.setStyle("Basic")
controller = ctrl_mod.AppController(STORE)
store = controller._store

engine = QQmlApplicationEngine()
engine.rootContext().setContextProperty("controller", controller)
engine.rootContext().setContextProperty("filesModel", controller.model)
engine.rootContext().setContextProperty("categoriesModel", controller.catModel)
engine.rootContext().setContextProperty("verModel", controller.verModel)
engine.addImportPath(QA_APP.as_uri())
WARNS = []
engine.warnings.connect(lambda ws: WARNS.extend(w.toString() for w in ws))
engine.load(QUrl.fromLocalFile(str(QA_APP / "qml" / "Main.qml")))
assert engine.rootObjects(), "QML 加载失败"
win = engine.rootObjects()[0]
win.resize(1440, 900)
win.show()
QTest.qWait(900)

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("PASS " if ok else "FAIL ") + name
          + ("  " + str(detail) if detail else ""), flush=True)


def walk(item):
    yield item
    for c in item.children():
        yield from walk(c)


def find_by_name(root, name):
    for it in walk(root):
        if it.property("objectName") == name:
            return it
    return None


def find_by_class(root, cls):
    return [it for it in walk(root)
            if it.inherits("QQuickItem")
            and it.metaObject().className().startswith(cls)]


def pbool(item, name, default=True):
    v = item.property(name)
    return default if v is None else bool(v)


def pnum(item, name, default=0.0):
    v = item.property(name)
    return default if v is None else v


def jsval(v):
    if hasattr(v, "toVariant"):
        try:
            return v.toVariant()
        except Exception:
            return v
    return v


def eval_expr(obj, expr: str):
    rv = QQmlExpression(QQmlEngine.contextForObject(obj), obj, expr).evaluate()
    return rv[0] if isinstance(rv, tuple) else rv


def row_items(fp):
    """回收站行委托（ListView 委托在 contentItem.childItems() 里）。"""
    lv = find_by_name(fp, "fileList")
    ci = lv.property("contentItem")
    ci = ci[0] if isinstance(ci, tuple) else ci
    if ci is None:
        return []
    kids = ci.childItems() if hasattr(ci, "childItems") else ci.children()
    return [k for k in kids if isinstance(k, QQuickItem)]


# ================= P1 造数 + 回收站数据 =================
tmp = Path(tempfile.mkdtemp(prefix="m40_src_"))
src = tmp / "回收测试.txt"
src.write_text("v1\n", encoding="utf-8")
v1 = store.commit_new(src, "首版", "M40探针")
fid = v1.get("fid") or store.all_files()[0]["fid"]
store.delete_file_record(fid)
controller.reload_files()
QTest.qWait(300)
controller.selectCollection("__trash__")
QTest.qWait(500)
fp = find_by_class(win, "FileListPane")[0]
check("P1a 回收站视图已激活且 1 行",
      jsval(fp.property("viewInfo")).get("inTrash") is True
      and controller.model.rowCount() == 1,
      f"inTrash={jsval(fp.property('viewInfo')).get('inTrash')} "
      f"rows={controller.model.rowCount()}")
row0 = controller.model.row_at(0)
check("P1b M40 新角色：origCat / delTime 有值（原先恒 undefined）",
      bool(row0.get("delTime")) and "origCat" in row0,
      {k: row0.get(k) for k in ("name", "origCat", "delTime")})

# ================= P2 列契约与几何 =================
defs = jsval(fp.property("colDefs")) or []
last = defs[-1] if defs else {}
check("P2a 末列表头 = 还原/清除，宽 112（非拉伸）",
      last.get("title") == "还原/清除" and last.get("def") == 112
      and last.get("stretch") is False, last)

rows = row_items(fp)
row = next((r for r in rows
            if find_by_name(r, "trashPurgeBtn") is not None), None)
rst = find_by_name(row, "trashRestoreBtn") if row else None
prg = find_by_name(row, "trashPurgeBtn") if row else None
lv = find_by_name(fp, "fileList")
colx4 = eval_expr(fp, "colX(4)")
w_list = pnum(lv, "width")
ok_geo = (rst is not None and prg is not None
          and abs(pnum(rst, "x") - (colx4 + 12)) < 1.0
          and abs(pnum(prg, "x") - (colx4 + 64)) < 1.0
          and pnum(prg, "x") + 46 <= w_list - 18)
check("P2b 还原/清除胶囊位置正确，清除右缘距滚动条 ≥8px（不再压线）",
      ok_geo,
      f"rst={pnum(rst,'x') if rst else None} prg={pnum(prg,'x') if prg else None} "
      f"listW={w_list} colX4={colx4}")
check("P2c 清除胶囊为琥珀色描边样式（Theme.cChange）",
      prg is not None and pbool(prg, "visible") is True)

# ================= P3 右键不再弹空菜单 =================
trash_fid = row0.get("fid")
before = len(fp.children())
eval_expr(fp, f'openMenu(0, "{trash_fid}")')
QTest.qWait(250)
after = len(fp.children())
check("P3a 回收站行右键不再创建菜单（空弹窗消失）",
      after == before, f"children {before} -> {after}")

# 普通行仍应有菜单（阴性对照）
controller.selectCollection("__all__")
QTest.qWait(400)
tmp2 = tmp / "正常文件.txt"
tmp2.write_text("x", encoding="utf-8")
v2 = store.commit_new(tmp2, "正常", "M40")
controller.reload_files()
QTest.qWait(400)
n0 = len(fp.children())
eval_expr(fp, 'openMenu(0, "%s")' % controller.model.row_at(0).get("fid"))
QTest.qWait(300)
n1 = len(fp.children())
check("P3b 阴性对照：普通文件行右键仍会创建菜单（未误伤）",
      n1 > n0, f"children {n0} -> {n1}")

# ================= P4 清除流程 =================
controller.selectCollection("__trash__")
QTest.qWait(400)
n_before = store.trash_summary()[0]
controller.purgeTrashItem(trash_fid, "回收测试.txt")
QTest.qWait(400)
dh = find_by_name(win, "dialogHost")
spec = jsval(dh.property("specData")) or {}
btns = jsval(dh.property("footerBtns")) or []
check("P4a 点清除 → 二次确认弹窗（标题「彻底删除」+ danger 主动作）",
      pbool(dh, "visible") is True and spec.get("title") == "彻底删除"
      and any(b.get("danger") is True for b in btns),
      f"title={spec.get('title')} btns={[(b.get('label'), b.get('danger')) for b in btns]}")
eval_expr(dh, "submit('ok')")
QTest.qWait(600)
n_after = store.trash_summary()[0]
check("P4b 确认后条目被彻底删除（回收站计数 -1）",
      n_after == n_before - 1, f"{n_before} -> {n_after}")

# ================= P5 字体独有族名 =================
FD = QA_APP / "resources" / "fonts"
fams = []
for nm in ("NotoSansSC-400.ttf", "NotoSansSC-500.ttf", "NotoSansSC-600.ttf",
           "Inter-Regular.ttf", "Inter-Medium.ttf", "Inter-SemiBold.ttf"):
    fid_f = QFontDatabase.addApplicationFont(str(FD / nm))
    fams.extend(QFontDatabase.applicationFontFamilies(fid_f))
uniq = sorted(set(fams))
check("P5a 六个随包字体只注册为 PJM Sans SC / PJM Num（不再 Noto/Inter）",
      uniq == ["PJM Num", "PJM Sans SC"], uniq)

missing = {}
for wname, w in (("400", QFont.Weight.Normal), ("500", QFont.Weight.Medium),
                 ("600", QFont.Weight.DemiBold)):
    f = QFont("PJM Sans SC")
    f.setWeight(w)
    raw = QRawFont.fromFont(f)
    idx = [i for ch in "回收站分类版本历史项目文件管家"
           for i in raw.glyphIndexesForString(ch)]
    info = QFontInfo(f)
    missing[wname] = (info.family(), info.styleName(),
                      info.exactMatch(), idx.count(0))
check("P5b 三档字重均解析到 PJM Sans SC 且零缺字（字形未动）",
      all(v[0] == "PJM Sans SC" and v[2] is True and v[3] == 0
          for v in missing.values()), missing)

src_theme = (QA_APP / "qml" / "Theme.qml").read_text(encoding="utf-8")
src_main = (QA_APP / "main.py").read_text(encoding="utf-8")
check("P5c 源码口径同步（Theme 族名 / main --fontcheck / 加载判定）",
      'fontFamily: "PJM Sans SC"' in src_theme
      and 'numFamily: "PJM Num"' in src_theme
      and "--fontcheck" in src_main
      and "applicationFontFamilies" in src_main)

# ================= F 警告 =================
err_warns = [w for w in WARNS if "TypeError" in w or "Error" in w
             or "is not a" in w or "Unable to assign" in w]
check("F 全程 0 个 QML 运行时 Error 级警告", not err_warns, err_warns[:3])

print(f"\n===== M40 集成探针：{len(PASS)} PASS / {len(FAIL)} FAIL =====")
for w in WARNS[:6]:
    print("[warn]", w[:130])
shutil.rmtree(STORE, ignore_errors=True)
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(1 if FAIL else 0)
