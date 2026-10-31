# -*- coding: utf-8 -*-
"""M99 弹窗：小屏不截断 + 长内容可滚。

判据都基于真实几何，不是读代码字面量：
  1. 弹窗在窗口内（顶 ≥ 0，底 ≤ 窗口高）
  2. 高度 ≤ maxDialogH
  3. 帮助这种长文本，内容区 contentHeight > 可视高（说明确实走滚动，
     而不是硬撑出一个超高弹窗）
"""
import os
import sys
import tempfile
from pathlib import Path

QA = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(QA))
os.environ["DOCVER_STORE"] = tempfile.mkdtemp(prefix="m99_")
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QUrl                              # noqa: E402
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
c.reloadFiles() if hasattr(c, "reloadFiles") else c.reload_files()
c.selectCollection("__all__")
QTest.qWait(120)

engine = QQmlApplicationEngine()
for k, val in (("controller", c), ("filesModel", c.model),
               ("categoriesModel", c.catModel), ("verModel", c.verModel)):
    engine.rootContext().setContextProperty(k, val)
engine.addImportPath(QA.as_uri())
engine.load(QUrl.fromLocalFile(str(QA / "qml" / "Main.qml")))
win = engine.rootObjects()[0]

# 故意用「小屏」：1366×768 扣掉任务栏后的近似可用高度
SmallW, SmallH = 1100, 620
win.resize(SmallW, SmallH)
win.show()
QTest.qWait(900)

from PySide6.QtCore import QObject
_cands = [o for o in win.findChildren(QObject)
          if o.property("objectName") == "dialogHost"]
print("dialogHost 候选:", [(type(o).__name__) for o in _cands])
dialog = _cands[0] if _cands else None
if dialog is None:
    raise SystemExit("找不到 dialogHost")
print("窗口 %dx%d" % (SmallW, SmallH), flush=True)
print("maxDialogH =", dialog.property("maxDialogH"), flush=True)

# 打开帮助（最长的弹窗）
c.open_help()
QTest.qWait(700)

root = win.contentItem()
h = float(dialog.property("height") or 0)
# Dialog 的 contentItem 才是可见矩形
ci = dialog.property("contentItem")
y_top = ci.mapToItem(root, 0, 0).y() if ci else -1
y_bot = y_top + h

print("弹窗 y=%.0f..%.0f  h=%.0f" % (y_top, y_bot, h), flush=True)

check("D1 弹窗高度不超过 maxDialogH",
      h <= float(dialog.property("maxDialogH")) + 1, "h=%s" % h)
check("D2 弹窗顶部没有跑到屏幕外", y_top >= -1, "y=%s" % y_top)
check("D3 弹窗底部没有超出窗口", y_bot <= SmallH + 1,
      "底=%.0f 窗口高=%d" % (y_bot, SmallH))

# 找内容区 Flickable（M99 加的 scroll）
flicks = [i for i in dialog.findChildren(QQuickItem)
          if "Flickable" in i.metaObject().className()]
check("D4 弹窗里有滚动容器", len(flicks) >= 1, len(flicks))
if flicks:
    f = flicks[0]
    ch = float(f.property("contentHeight") or 0)
    vh = float(f.property("height") or 0)
    print("内容高=%.0f 可视高=%.0f" % (ch, vh), flush=True)
    check("D5 帮助内容确实超出可视区（应当滚动）", ch > vh, "%.0f > %.0f" % (ch, vh))
    check("D6 滚动容器高度是弹窗内剩余空间，不是被内容撑爆",
          vh <= h, "%.0f <= %.0f" % (vh, h))

# 短弹窗不应被撑成高个子（确认框）
c.show_dialog({"title": "确认", "message": "确定要这样做吗？",
               "buttons": [{"label": "取消", "key": "cancel"},
                           {"label": "确定", "key": "ok", "accent": True}]}, None)
QTest.qWait(500)
h2 = float(dialog.property("height") or 0)
print("短弹窗 h=%.0f" % h2, flush=True)
check("D7 短弹窗按内容自适应，不会占满高度", h2 < 300, "h=%.0f" % h2)

# D8：帮助这种长内容弹窗必须被内容撑到接近上限。
# 曾经出过事故：正文（msgLbl）跟着标题一起被提进固定区，弹窗塌成一条、
# 正文直接溢出到弹窗外面画在背景上。只看「高度不超过上限」是抓不到的，
# 必须有下限。
c.open_help()
QTest.qWait(700)
h3 = float(dialog.property("height") or 0)
print("帮助弹窗 h=%.0f" % h3, flush=True)
check("D8 帮助弹窗被内容撑开（塌成一条说明正文跑出了滚动区）",
      h3 >= 300, "h=%.0f" % h3)

print(f"\n===== M99 弹窗：{len(PASS)} PASS / {len(FAIL)} FAIL =====")
sys.exit(1 if FAIL else 0)
