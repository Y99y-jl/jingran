# -*- coding: utf-8 -*-
"""M94 验收：页脚 32、查看全部已删、回收站与页脚文字对齐到 3px 内。"""
import json
import os
import sys
import tempfile
from pathlib import Path

QA = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(QA))
STORE = tempfile.mkdtemp(prefix="m94_")
os.environ["DOCVER_STORE"] = STORE
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QUrl                                  # noqa: E402
from PySide6.QtGui import QFontDatabase, QGuiApplication, QImage  # noqa: E402
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


cm.os.startfile = lambda p, *a, **k: None
app = QGuiApplication(sys.argv)
for _t in sorted((QA / "resources" / "fonts").glob("*.ttf")):
    QFontDatabase.addApplicationFont(str(_t))
QQuickStyle.setStyle("Basic")

c = cm.AppController(STORE)
st = c._store
a_id = st.add_collection("项目分类")
tmp = Path(tempfile.mkdtemp(prefix="m94_src_"))
for i, n in enumerate(["季度经营汇报.docx", "供应商合同_Q3.pdf",
                       "成本测算表.xlsx", "需求说明.md", "会议纪要.txt"]):
    f = tmp / n
    f.write_text("v%d" % i, encoding="utf-8")
    st.commit_new(f, "首次提交", category=a_id)
meta0 = st.find_in_category(a_id, "季度经营汇报.docx")
f0 = tmp / "季度经营汇报.docx"
for k in range(3):
    f0.write_text("b%d" % k, encoding="utf-8")
    st.commit_next_version(meta0["fid"], f0, "第%d次修订" % (k + 2))
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
QTest.qWait(900)
rows = c.model.rows
c.setSelection(json.dumps([rows[0]["fid"]]))
QTest.qWait(500)

# ---------- 静态：查看全部入口已消失 ----------
vp = (QA / "qml" / "panes" / "VersionPane.qml").read_text(encoding="utf-8")
check("P1 版本区不再有「查看全部」入口", '"查看全部 ' not in vp and "allMa" not in vp)
check("P2 版本列表高度不再预留 44px", "parent.height - 90 - 34 - 44" not in vp)

# ---------- 几何：页脚 32、回收站贴底 ----------
items = win.findChildren(QQuickItem)
pane = next(i for i in items
            if i.metaObject().className().startswith("FileListPane"))
foot = next((i for i in pane.findChildren(QQuickItem)
             if i.property("objectName") == "paneFooter"), None)
check("P3 页脚高 24", foot is not None and foot.property("height") == 24,
      foot.property("height") if foot else None)

# ---------- 像素：两处文字中心差 ≤ 4px ----------
OUT = QA / "tests" / "artifacts"
OUT.mkdir(parents=True, exist_ok=True)
p = OUT / "m94_align.png"
win.grabWindow().save(str(p))
im = QImage(str(p)).convertToFormat(QImage.Format_RGB32)


def rows_of(x0, x1, y0, y1, dark=140):
    ys = []
    for y in range(y0, y1):
        n = 0
        for x in range(x0, x1):
            v = im.pixel(x, y)
            if ((v >> 16 & 0xFF) + (v >> 8 & 0xFF) + (v & 0xFF)) / 3 < dark:
                n += 1
        if n >= 3:
            ys.append(y)
    return ys


# M95：用户明确要求回退「对齐」——左栏底部 16px 呼吸位保留，回收站不要贴死底边。
# 所以这里不再要求两者对齐，而是**反向锁死**：必须存在约 16px 的错位。
# （若有人"好心"又把它对齐了，这条会 FAIL，提醒去看 CategoryTreePane 的注释。）
rz = rows_of(40, 120, 740, 809)
ft = rows_of(270, 470, 770, 809)
c_rz = (rz[0] + rz[-1]) // 2 if rz else None
c_ft = (ft[0] + ft[-1]) // 2 if ft else None
gap = abs(c_rz - c_ft) if (c_rz and c_ft) else None
check("P4 左栏保留 16px 呼吸位（回收站不与页脚对齐，差 12~32px）",
      gap is not None and 12 <= gap <= 32,
      "回收站中心=%s 页脚中心=%s 差=%s" % (c_rz, c_ft, gap))

print(f"\n===== M94 探针：{len(PASS)} PASS / {len(FAIL)} FAIL =====")
sys.exit(1 if FAIL else 0)
