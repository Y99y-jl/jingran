# -*- coding: utf-8 -*-
"""M92 验收：底部常驻状态条已删除，状态消息并入中栏页脚。

为什么单独锁这条
----------------
删状态条这件事，价值全在「底部不再多出 20px」这一个事实。这种"减法"
最容易在后续改动里被悄悄加回来（谁顺手在 ColumnLayout 末尾再塞一个
`Layout.preferredHeight: 14` 的 RowLayout，界面看起来也"正常"）。
所以这里既锁静态（Main.qml 不许再有状态条），也锁几何（页脚底边必须
紧贴窗口 8px 内距），还锁行为（消息着色、2.6s 回落）。

运行：<venv>/python.exe tests/m92_footer_probe.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

QA = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(QA))
STORE = tempfile.mkdtemp(prefix="m92_")
os.environ["DOCVER_STORE"] = STORE
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QUrl                                  # noqa: E402
from PySide6.QtGui import QFontDatabase, QGuiApplication          # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine                  # noqa: E402
from PySide6.QtQuick import QQuickItem                           # noqa: E402
from PySide6.QtQuickControls2 import QQuickStyle                 # noqa: E402
from PySide6.QtTest import QTest                                 # noqa: E402

import controller as cm                                          # noqa: E402

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("PASS " if ok else "FAIL ") + name
          + ("  " + str(detail) if detail else ""), flush=True)


# ---------- 静态：状态条不许回来 ----------
main_qml = (QA / "qml" / "Main.qml").read_text(encoding="utf-8")
check("S1 Main.qml 不再有 statusText 节点", "statusText" not in main_qml)
check("S2 Main.qml 不再硬编码「就绪」", '"就绪"' not in main_qml)

# ---------- 起界面 ----------
cm.os.startfile = lambda p, *a, **k: None
app = QGuiApplication(sys.argv)
for _t in sorted((QA / "resources" / "fonts").glob("*.ttf")):
    QFontDatabase.addApplicationFont(str(_t))
QQuickStyle.setStyle("Basic")

c = cm.AppController(STORE)
st = c._store
a_id = st.add_collection("项目分类")
tmp = Path(tempfile.mkdtemp(prefix="m92_src_"))
for i in range(4):
    f = tmp / ("file%d.txt" % i)
    f.write_text("x%d" % i, encoding="utf-8")
    st.commit_new(f, "首次提交", category=a_id)
c.reload_files()
c.selectCollection("__all__")
QTest.qWait(150)

engine = QQmlApplicationEngine()
for k, val in (("controller", c), ("filesModel", c.model),
               ("categoriesModel", c.catModel), ("verModel", c.verModel)):
    engine.rootContext().setContextProperty(k, val)
engine.addImportPath(QA.as_uri())
engine.load(QUrl.fromLocalFile(str(QA / "qml" / "Main.qml")))
win = engine.rootObjects()[0]
win.resize(1296, 817)
win.show()
QTest.qWait(800)

items = win.findChildren(QQuickItem)
pane = next(i for i in items
            if i.metaObject().className().startswith("FileListPane"))
label = next((i for i in items if i.property("objectName") == "statusLabel"), None)
check("S3 页脚状态位存在", label is not None)

# ---------- 几何：页脚底边贴窗口 8px 内距 ----------
bottom = pane.mapToItem(win.contentItem(), 0, pane.height()).y()
expect = win.height() - 8
check("S4 三栏底边直接贴窗口内距（底部无第二层）", abs(bottom - expect) <= 1,
      "实测 y=%.0f  期望 y=%d  （差 %.0f → 若差 ≈20 说明状态条又回来了）"
      % (bottom, expect, abs(bottom - expect)))

if label is not None:
    def txt():
        return label.property("text")

    def col():
        v = label.property("color")
        return v.name().upper() if hasattr(v, "name") else str(v).upper()

    check("S5 空闲时完全不显示（无「就绪」占位）", txt() == "", repr(txt()))

    c.status("已提交 3 个文件", "ok")
    QTest.qWait(200)
    check("S6 ok 消息上屏且着色", "已提交 3 个文件" == txt() and col() == "#0E9F6E",
          "%s / %s" % (txt(), col()))

    c.status("提交失败：占用", "err")
    QTest.qWait(200)
    check("S7 err 消息切红", "提交失败：占用" == txt() and col() == "#E5484D",
          "%s / %s" % (txt(), col()))

    QTest.qWait(2900)
    check("S8 2.6s 后回落为空白", txt() == "", repr(txt()))

    # 旧文案是写死的假状态，必须彻底消失（只匹配字符串字面量，注释不算）
    foot = (QA / "qml" / "panes" / "FileListPane.qml").read_text(encoding="utf-8")
    check("S9 假的「本地库正常」文案已移除", '"本地库正常' not in foot)

print(f"\n===== M92 探针：{len(PASS)} PASS / {len(FAIL)} FAIL =====")
sys.exit(1 if FAIL else 0)
