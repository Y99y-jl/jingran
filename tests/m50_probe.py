# -*- coding: utf-8 -*-
"""M50 验收：回到某版本 / 提交弹窗置灰与选路径 / 设置开关 / 回收站版本号。"""
import json
import os
import sys
import tempfile
from pathlib import Path

QA = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(QA))
STORE = tempfile.mkdtemp(prefix="m50_")
os.environ["DOCVER_STORE"] = STORE
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtGui import QGuiApplication  # noqa: E402
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


specs = []
c.dialogRequested.connect(lambda js: specs.append(json.loads(js)))

# ---------- 造两个版本 ----------
tmp = Path(tempfile.mkdtemp(prefix="m50_src_"))
f = tmp / "还原测试.txt"
f.write_text("第一版内容", encoding="utf-8")
v1 = st.commit_new(f, "首版", category=None)
fid = v1.get("fid") or st.all_files()[0]["fid"]
QTest.qWait(50)
f.write_text("第二版内容", encoding="utf-8")
st.commit_next_version(fid, str(f), "改第二版")
c.reload_files()
c.setSelection(json.dumps([fid]))
meta = st.load_meta(fid)
print("版本数 =", len(meta["versions"]))
ver1 = meta["versions"][0]

# ---------- 菜单项 ----------
spec = json.loads(c.versionMenuSpec(ver1["id"]))
keys = [a.get("key") for a in spec.get("actions", []) if not a.get("sep")]
check("R1 版本右键菜单含「回到此版本」", "restore_version" in keys, keys)

# ---------- 执行还原 ----------
c.versionMenuAction("restore_version", json.dumps({"vid": ver1["id"]}))
QTest.qWait(100)
check("R2 弹出二次确认", bool(specs) and specs[-1].get("title") == "回到此版本",
      specs[-1].get("title") if specs else None)
rid = specs[-1]["rid"]
c.dialogResult(json.dumps({"rid": rid, "values": {"__btn": "ok"}}))
QTest.qWait(300)
meta2 = st.load_meta(fid)
check("R3 还原后版本数 +1（历史未改写）", len(meta2["versions"]) == len(meta["versions"]) + 1,
      f'{len(meta["versions"])} -> {len(meta2["versions"])}')
last = meta2["versions"][-1]
ver_file = st.version_file(meta2, last)
content = Path(ver_file).read_text(encoding="utf-8")
check("R4 新版本内容 = 被还原版本内容", content == "第一版内容", content)
check("R5 新版本原因是「回到…」", "回到" in (last.get("reason") or ""), last.get("reason"))

# ---------- 提交弹窗：type=file + okRequire ----------
newf = tmp / "新文件.txt"
newf.write_text("x", encoding="utf-8")
c.openCommitDialog()
QTest.qWait(100)
sp = specs[-1]
path_field = next((x for x in sp["fields"] if x["key"] == "path"), {})
check("D1 路径字段类型 = file（带选择按钮）", path_field.get("type") == "file",
      path_field.get("type"))
check("D2 弹窗声明 okRequire 含 path", sp.get("okRequire") == ["path"],
      sp.get("okRequire"))
# 取消掉，别留下悬挂弹窗
c.dialogResult(json.dumps({"rid": sp["rid"], "values": {"__btn": "cancel"}}))

# ---------- 设置：toggle 项 ----------
specs.clear()
c.open_settings()
QTest.qWait(100)
items = [i for g in specs[-1]["groups"] for i in g["items"]]
tog = next((i for i in items if i.get("type") == "toggle"), None)
check("S1 设置里有 toggle 型开关（文字+已开启/已关闭）",
      tog is not None and tog.get("label") == "关闭窗口时隐藏到托盘"
      and isinstance(tog.get("on"), bool), tog)
c.dialogResult(json.dumps({"rid": specs[-1]["rid"], "values": {"__btn": "cancel"}}))

# ---------- 回收站：单版本条目带版本号 ----------
f2 = tmp / "删除版本.txt"
f2.write_text("a", encoding="utf-8")
st.commit_new(f2, "v1")
fid2 = next(m["fid"] for m in st.all_files() if m["name"] == f2.name)
f2.write_text("b", encoding="utf-8")
st.commit_next_version(fid2, str(f2), "v2")
m2 = st.load_meta(fid2)
st.delete_version(fid2, m2["versions"][0]["id"])
c.selectCollection("__trash__")
QTest.qWait(200)
names = [r["name"] for r in c.model.rows]
check("T1 回收站里单版本条目带版本号", any("（" in n and "版本" in n for n in names), names)

print(f"\n===== M50 探针：{len(PASS)} PASS / {len(FAIL)} FAIL =====")
sys.exit(1 if FAIL else 0)
