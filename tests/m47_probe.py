# -*- coding: utf-8 -*-
"""M47 验收探针：分类解析（含名称串）/ Ctrl 范围选 / 分类标题 / 页脚 / 托盘开关。"""
import json
import os
import sys
import tempfile
from pathlib import Path

QA = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(QA))
STORE = tempfile.mkdtemp(prefix="m47v_")
os.environ["DOCVER_STORE"] = STORE
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtQuick import QQuickItem  # noqa: E402
from PySide6.QtQuickControls2 import QQuickStyle  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

import controller as cm  # noqa: E402

cm.os.startfile = lambda p, *a, **k: None
app = QGuiApplication(sys.argv)
QQuickStyle.setStyle("Basic")
c = cm.AppController(STORE)
st = c._store
PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("PASS " if ok else "FAIL ") + name
          + ("  " + str(detail) if detail else ""), flush=True)


a_id = st.add_collection("甲类")
b_id = st.add_collection("乙类")
tmp = Path(tempfile.mkdtemp(prefix="m47v_src_"))
for i in range(6):
    f = tmp / f"g{i}.txt"
    f.write_text(str(i), encoding="utf-8")
    st.commit_new(f, "v1", category=a_id)
c.reload_files()
c.selectCollection(a_id)
QTest.qWait(200)

# ④ 标题
v = json.loads(c.lastView())
check("V4 viewInfo.collection = 当前分类名", v.get("collection") == "甲类", v.get("collection"))

# ① 分类解析：传「名称字符串」也要落到正确分类（QML 可能的回传形态）
specs = []
c.dialogRequested.connect(lambda js: specs.append(json.loads(js)))
for i, form in enumerate(("名称", "cid", "索引串", "索引")):
    f = tmp / f"form{i}.txt"
    f.write_text("x", encoding="utf-8")
    c.open_commit_dialog([str(f)])
    rid = specs[-1]["rid"]
    opts, _ = c._col_options()
    idx = next(k for k, o in enumerate(opts) if o["cid"] == b_id)
    val = {"名称": "乙类", "cid": b_id, "索引串": str(idx), "索引": idx}[form]
    c.dialogResult(json.dumps({"rid": rid, "values": {
        "path": str(f), "category": val, "reason": "x", "__btn": "ok"}}))
    QTest.qWait(120)
    meta = next((m for m in st.all_files() if m.get("name") == f.name), None)
    check(f"V1 分类回传形态「{form}」→ 落到乙类",
          (meta or {}).get("category") == b_id,
          (meta or {}).get("category"))

# ③ Ctrl 范围选择
c.selectCollection("__all__")
QTest.qWait(150)
c.setSelection("[]")
ids = [r["fid"] for r in c.model.rows]


def press(i, ctrl=False, shift=False, anchor=1):
    ev = {"op": "press", "row": ids[i], "x": 10, "y": 10, "ctrl": ctrl,
          "shift": shift, "isTrash": False, "rowIndex": i, "modsAnchor": anchor}
    return json.loads(c.fileEvent(json.dumps(ev)))["selected"]


s1 = press(1)
# M65：整段选择统一为 Shift（Ctrl 只做加减选）
s2 = press(4, shift=True)
check("V3 Shift+点第5行 = 2~5 全选（4 个）", len(s2) == 4, f"anchor 点击后 {len(s1)} → {len(s2)}")
s3 = press(4, ctrl=True, anchor=0)   # 已选中再 Ctrl 点 → 退化为取消
check("V3b 已选中行 Ctrl 再点 = 取消该行", len(s3) < len(s2), f"{len(s2)} → {len(s3)}")

# ② 页脚（QML 层）
engine = QQmlApplicationEngine()
for k, val in (("controller", c), ("filesModel", c.model),
               ("categoriesModel", c.catModel), ("verModel", c.verModel)):
    engine.rootContext().setContextProperty(k, val)
engine.addImportPath(QA.as_uri())
engine.load(QUrl.fromLocalFile(str(QA / "qml" / "Main.qml")))
win = engine.rootObjects()[0]
win.resize(1400, 860)
win.show()
QTest.qWait(700)
pane = next(i for i in win.findChildren(QQuickItem)
            if i.metaObject().className().startswith("FileListPane"))
footer = next((i for i in pane.findChildren(QQuickItem)
               if i.property("objectName") == "paneFooter"), None)
check("V2 页脚高 24（M96 由 56→40→32→28→24）且始终可见",
      footer is not None and bool(footer.property("visible"))
      and footer.property("height") == 24,
      f"h={footer.property('height') if footer else None}")

# ⑤ 托盘开关
d0 = c.closeToTray()
c.setCloseToTray(False)
d1 = c.closeToTray()
c.setCloseToTray(True)
check("V5 closeToTray 默认开 → 可关可开且落盘", d0 is True and d1 is False
      and c.closeToTray() is True, f"{d0} -> {d1} -> {c.closeToTray()}")
check("V5b 配置已写入库 config", "closeToTray" in
      (st.config.get("ui", {}) or {}), st.config.get("ui", {}))

# ⑥ 帮助文案（M98 逐条核对过，这里锁住「不许再退回错误说法」）
_calls = []
_c_show = c.show_dialog
c.show_dialog = lambda payload, cb: _calls.append(payload)
c.open_help()
c.show_dialog = _c_show
_help = _calls[0]["message"] if _calls else ""

from app_version import VERSION as _APPVER          # noqa: E402
check("V6 帮助顶部显示当前版本号", _APPVER in _help, _APPVER)
check("V6b 帮助不含已过时的错误说明（左栏单击展开 / Del 删除）",
      "单击展开" not in _help and "Del 删除" not in _help)
check("V6c 帮助补齐了栏宽拖动与右栏收纳",
      "分隔条" in _help and "右栏收纳" in _help)
check("V6d 帮助里没有残留的格式化占位符",
      "%s" not in _help and "None" not in _help)
# M99：软件要给同事用、还要开源，帮助里不能出现本机绝对路径
check("V6e 帮助里不含本机绝对路径",
      "C:\\" not in _help and "Users\\" not in _help and ":\\" not in _help,
      "含盘符" if ":\\" in _help else "干净")

print(f"\n===== M47 探针：{len(PASS)} PASS / {len(FAIL)} FAIL =====")
sys.exit(1 if FAIL else 0)
