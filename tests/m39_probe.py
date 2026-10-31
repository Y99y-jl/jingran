# -*- coding: utf-8 -*-
"""M39 集成探针（源码级，offscreen）：拖入文件行续版本 + 库目录去 QML 化。

覆盖（对应 M39 施工单）：
  J1 行命中：文件区 hitFileRowFrom 命中首行 fid；空白处返回空；
     回收站行拒绝（源码事实——isTrash 判定）；
  J2 拖到行 → 极小确认窗：标题「续版本」、文案含两文件名、原因预填
     「拖拽续版本」、按钮 accent=续版本；提交后版本数 2、原因落库、
     该文件被选中；
  J3 取消不落库；多文件拖一行被拒绝（提示，不弹窗）；
  J4 库目录去 QML：main.py 生产分支指向 项目文件管家/store，且带
     旧目录一次性复制迁移（legacy_store）；不再以 项目文件管家QML
     作为主路径。
沙箱铁律同 M35-M38：一次性库；真实库零接触（DOCVER_STORE 指向 tmp）。
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

QA_APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(QA_APP))

STORE = tempfile.mkdtemp(prefix="m39_integ_")
os.environ["DOCVER_STORE"] = STORE
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QPointF, QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import (QQmlApplicationEngine,  # noqa: E402
                           QQmlExpression, QQmlEngine)
from PySide6.QtQuick import QQuickItem  # noqa: E402
from PySide6.QtQuickControls2 import QQuickStyle  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

import controller as ctrl_mod  # noqa: E402

STARTED = []
ctrl_mod.os.startfile = lambda p, *a, **k: STARTED.append(str(p))

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


# ================= 造数 =================
tmp = Path(tempfile.mkdtemp(prefix="m39_src_"))
src0 = tmp / "原文件.txt"
src0.write_text("v1 内容\n", encoding="utf-8")
v1 = store.commit_new(src0, "首版", "M39探针")
fid = v1.get("fid") or store.all_files()[0]["fid"]
controller.reload_files()
QTest.qWait(400)

drop1 = tmp / "拖入.txt"
drop1.write_text("v2 内容\n", encoding="utf-8")
drop2 = tmp / "拖入2.txt"
drop2.write_text("另一个\n", encoding="utf-8")

check("J0 造数：一个文件入库",
      len(store.all_files()) == 1 and len(store.load_meta(fid)["versions"]) == 1,
      f"fid={fid}")

# ================= J1 行命中 =================
fp = find_by_class(win, "FileListPane")[0]
lv = find_by_name(fp, "fileList")
pt_row = lv.mapToItem(fp, QPointF(20, 24))
pt_empty = lv.mapToItem(fp, QPointF(20, lv.property("height") - 6))
hit = eval_expr(fp, f"hitFileRowAt({pt_row.x()}, {pt_row.y()})")
hit_empty = eval_expr(
    fp, f"hitFileRowAt({pt_empty.x()}, {pt_empty.y()})")
check("J1a 文件行命中：首行中部 → 该文件 fid",
      hit == fid, f"hit={hit} 期望={fid}")
check("J1b 空白处（列表底部）→ 空（回落原提交新版本路径）",
      hit_empty == "", f"hit={hit_empty!r}")
src_flp = (QA_APP / "qml" / "panes" / "FileListPane.qml").read_text(
    encoding="utf-8")
check("J1c 回收站伪行不接收落点（源码事实 isTrash 判定）",
      "row.isTrash === true" in src_flp and "hitFileRowAt" in src_flp)
src_main_qml = (QA_APP / "qml" / "Main.qml").read_text(encoding="utf-8")
check("J1d 主窗拖放已按命中分流（dropOntoFile / dropInFiles 双路）",
      "dropOntoFile(fid" in src_main_qml
      and "hitFileRowAt(dp.x, dp.y)" in src_main_qml
      and "dropHoverFid" in src_main_qml)

# 落点高亮：设 hover fid → 该行高亮矩形可见；清空 → 隐藏
# （委托在 contentItem.childItems() 里，children() 取不到——M35/M36 老坑）
def find_in_rows(name):
    ci = lv.property("contentItem")
    ci = ci[0] if isinstance(ci, tuple) else ci
    if ci is None:
        return None
    kids = ci.childItems() if hasattr(ci, "childItems") else ci.children()
    for ch in kids:
        for it in walk(ch):
            if it.property("objectName") == name:
                return it
    return None


eval_expr(fp, f'dropHoverFid = "{fid}"')
QTest.qWait(150)
hover_item = find_in_rows("fileDropHover")
hover_on = hover_item is not None and pbool(hover_item, "visible") is True
eval_expr(fp, 'dropHoverFid = ""')
QTest.qWait(150)
hover_off = hover_item is not None and pbool(hover_item, "visible") is False
check("J1e 拖过该行 → 落点高亮可见；离开 → 隐藏（视觉可预期）",
      hover_on and hover_off,
      f"on={hover_on} off={hover_off} item={hover_item is not None}")

# ================= J2 拖到行 → 极小确认窗 =================
dh = find_by_name(win, "dialogHost")
check("J2 dialogHost 可定位", dh is not None)
r = json.loads(controller.dropOntoFile(fid, json.dumps([drop1.as_uri()])))
QTest.qWait(350)
spec = jsval(dh.property("specData")) or {}
vm = jsval(dh.property("valueMap")) or {}
reason0 = vm.get("reason")
btns = jsval(dh.property("footerBtns")) or []
check("J2a 落下后弹极小确认窗（标题「续版本」+ 文案点名两文件）",
      r.get("dialog") is True and pbool(dh, "visible") is True
      and spec.get("title") == "续版本"
      and "拖入.txt" in (spec.get("message") or "")
      and "原文件.txt" in (spec.get("message") or ""),
      f"title={spec.get('title')} msg={(spec.get('message') or '')[:40]}")
check("J2b 原因字段预填「拖拽续版本」（改不改随用户，直接回车即完成）",
      reason0 == "拖拽续版本", reason0)
acc = [b for b in btns if b.get("accent") is True]
check("J2c 主动作为「续版本」（Enter 直接确认，非取消）",
      len(acc) == 1 and acc[0].get("label") == "续版本",
      [(b.get("label"), b.get("accent")) for b in btns])
eval_expr(dh, "submit('ok')")
QTest.qWait(500)
meta = store.load_meta(fid)
vers = meta["versions"]
check("J2d 提交后：版本数 1→2，最新版原因=拖拽续版本",
      len(vers) == 2 and vers[-1].get("reason") == "拖拽续版本",
      f"n={len(vers)} reason={vers[-1].get('reason')}")
check("J2e 提交后该文件被选中（右栏即显新版本，无需再点）",
      list(jsval(controller._selected_fids)) == [fid],
      list(jsval(controller._selected_fids)))
check("J2f 版本模型同步刷新（2 行）",
      controller.verModel.rowCount() == 2, controller.verModel.rowCount())

# ================= J3 取消 / 多文件 =================
n_before = len(store.load_meta(fid)["versions"])
controller.dropOntoFile(fid, json.dumps([drop2.as_uri()]))
QTest.qWait(300)
eval_expr(dh, "submit('cancel')")
QTest.qWait(300)
n_after = len(store.load_meta(fid)["versions"])
check("J3a 取消 → 不落库（版本数不变）", n_after == n_before,
      f"{n_before}→{n_after}")

r2 = json.loads(controller.dropOntoFile(
    fid, json.dumps([drop1.as_uri(), drop2.as_uri()])))
QTest.qWait(250)
check("J3b 多个文件拖到一行 → 拒绝并提示（不弹确认窗）",
      r2.get("ok") is False and r2.get("reason") == "multiple"
      and pbool(dh, "visible") is False,
      r2)

# ================= J4 库目录去 QML 化 =================
src_main = (QA_APP / "main.py").read_text(encoding="utf-8")
# M41：产品更名井然 → 生产库目录随之变成 井然/store，历史目录进 legacy 列表
check("J4a 生产库目录 = 井然/store（M41 更名后口径）",
      '"井然" / "store"' in src_main)
check("J4b 历史目录一次性复制迁移在岗（两代旧名都在 legacy 列表，旧库保留）",
      "legacy_dirs" in src_main
      and 'root / "项目文件管家" / "store"' in src_main
      and 'root / "项目文件管家QML" / "store"' in src_main
      and "shutil.copytree(legacy_store, qml_store)" in src_main)
check("J4c 迁移幂等（新目录已存在则不覆盖）",
      "if not qml_store.exists():" in src_main)

# ================= F 全程无 QML 运行时 Error 级警告 =================
err_warns = [w for w in WARNS if "TypeError" in w or "Error" in w
             or "is not a" in w or "Unable to assign" in w]
check("F 全程 0 个 QML 运行时 Error 级警告", not err_warns,
      err_warns[:3])

# ================= 汇总 =================
print(f"\n===== M39 集成探针：{len(PASS)} PASS / {len(FAIL)} FAIL =====")
for w in WARNS[:6]:
    print("[warn]", w[:130])
shutil.rmtree(STORE, ignore_errors=True)
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(1 if FAIL else 0)
