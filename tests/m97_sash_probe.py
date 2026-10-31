# -*- coding: utf-8 -*-
"""M97 验证：拖右栏松手后宽度要落定；再拖左栏不得把它打回。

用 QTest 真实按住分隔条拖动（不是直接改 preferredWidth ——
那样不经过 SplitView 的拖拽通道，测不出这个 bug）。
"""
import os
import sys
import tempfile
from pathlib import Path

QA = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(QA))
os.environ["DOCVER_STORE"] = tempfile.mkdtemp(prefix="m97_")
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QPoint, Qt, QUrl                  # noqa: E402
from PySide6.QtGui import QFontDatabase, QGuiApplication      # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine              # noqa: E402
from PySide6.QtQuick import QQuickItem                       # noqa: E402
from PySide6.QtQuickControls2 import QQuickStyle             # noqa: E402
from PySide6.QtTest import QTest                             # noqa: E402

import controller as cm                                      # noqa: E402

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("PASS " if ok else "FAIL ") + name
          + ("  " + str(detail) if detail else ""), flush=True)


cm.os.startfile = lambda p, *a, **k: None
app = QGuiApplication(sys.argv)
for _t in sorted((QA / "resources" / "fonts").glob("*.ttf")):
    QFontDatabase.addApplicationFont(str(_t))
QQuickStyle.setStyle("Basic")

c = cm.AppController(os.environ["DOCVER_STORE"])
st = c._store
cid = st.add_collection("演示")
tmp = Path(tempfile.mkdtemp())
for i in range(3):
    f = tmp / ("f%d.txt" % i)
    f.write_text("x", encoding="utf-8")
    st.commit_new(f, "首次提交", category=cid)
c.reload_files()
c.selectCollection("__all__")
QTest.qWait(120)

engine = QQmlApplicationEngine()
for k, val in (("controller", c), ("filesModel", c.model),
               ("categoriesModel", c.catModel), ("verModel", c.verModel)):
    engine.rootContext().setContextProperty(k, val)
engine.addImportPath(QA.as_uri())
engine.load(QUrl.fromLocalFile(str(QA / "qml" / "Main.qml")))
win = engine.rootObjects()[0]
win.resize(1296, 817)
win.show()
QTest.qWait(900)

items = win.findChildren(QQuickItem)
split = next(i for i in items if "SplitView" in i.metaObject().className())
ver = next(i for i in items if i.metaObject().className().startswith("VersionPane"))
cat = next(i for i in items if i.metaObject().className().startswith("CategoryTreePane"))
verWrap = ver.parentItem()

root_item = win.contentItem()
print("splitView 子项:")
for ch in split.childItems():
    p = ch.mapToItem(root_item, 0, 0)
    print("  %-28s x=%6.1f w=%6.1f" % (ch.metaObject().className(), p.x(), ch.width()))


def drag(x_from, x_to, y=300):
    """在 splitView 内水平拖动一根分隔条"""
    QTest.mousePress(win, Qt.LeftButton, Qt.NoModifier, QPoint(int(x_from), y))
    QTest.qWait(60)
    steps = 8
    for i in range(1, steps + 1):
        x = x_from + (x_to - x_from) * i / steps
        QTest.mouseMove(win, QPoint(int(x), y))
        QTest.qWait(25)
    QTest.mouseRelease(win, Qt.LeftButton, Qt.NoModifier, QPoint(int(x_to), y))
    QTest.qWait(400)


def state():
    return (win.property("rightW"), round(cat.width()), round(ver.width()))


print("\n初始 rightW=%s cat=%s ver=%s" % state())
w0, c0, v0 = state()

# ① 拖右分隔条向右**左** 90px（右栏变宽；它已是最窄，向右只会被钳住）
ver_x = verWrap.mapToItem(root_item, 0, 0).x()
drag(ver_x - 3, ver_x - 90)
w1, c1, v1 = state()
print("拖右分隔条 +90 →  rightW=%s cat=%s ver=%s" % (w1, c1, v1))
check("R1 拖右栏后宽度确实变宽", v1 > v0 + 40, "ver %s → %s" % (v0, v1))
check("R2 拖右栏后 rightW 同步跟上（不会被弹回）", w1 > w0 + 40,
      "rightW %s → %s" % (w0, w1))

# ② 再拖左分隔条（位于 leftWrap 右缘）
cat_x = cat.mapToItem(root_item, 0, 0).x() + cat.width()
drag(cat_x + 3, cat_x + 60)
w2, c2, v2 = state()
print("再拖左分隔条 +60 →  rightW=%s cat=%s ver=%s" % (w2, c2, v2))
check("R3 拖左栏后右栏宽度不回弹到最窄", abs(w2 - w1) <= 2,
      "rightW %s → %s（最窄 %s）" % (w1, w2, win.property("rightMinW")))
check("R4 拖左栏后右栏实际宽度基本不变", abs(v2 - v1) <= 40,
      "ver %s → %s" % (v1, v2))

# ③ 配置里是否已落库
ui = c._store.config.get("ui", {})
print("\nconfig ui.sash =", ui.get("sash"))
check("R5 拖动结果已写进 config（不等退出）",
      isinstance(ui.get("sash"), list) and len(ui["sash"]) == 2,
      ui.get("sash"))

print(f"\n===== M97 拖拽回归：{len(PASS)} PASS / {len(FAIL)} FAIL =====")
sys.exit(1 if FAIL else 0)
